"""Complete review pipeline orchestration for triumvirate code review.

This module provides the ReviewWorker class that orchestrates the full review
pipeline: PR diff retrieval → parallel reviewer dispatch → verdict parsing →
Verdict Store write → issue creation → notification.

Domain warnings:
⚠️ WARNING: Verdict Store write durability — Write verdicts before attempting issue creation
⚠️ WARNING: Webhook timeout vs review duration — This runs async after 200 response
⚠️ WARNING: All three reviewers dispatch in parallel, blind to each other's output
"""

from pathlib import Path
from typing import Any

import structlog

from github.issues import IssueCreator
from github.pr import PRClient
from notifications.publisher import NotificationPublisher
from reviewers.dispatch import ReviewerDispatcher
from reviewers.verdicts import VerdictParser
from verdict_store.client import FindingRecord, VerdictRecord, VerdictStoreClient

__all__ = ["ReviewWorker", "WorkerError"]

logger = structlog.get_logger(__name__)


class WorkerError(Exception):
    """Raised when review worker fails."""

    pass


class ReviewWorker:
    """Orchestrates the complete review pipeline for triumvirate code review.

    Coordinates PR diff retrieval, parallel reviewer dispatch, verdict parsing,
    Verdict Store writes, GitHub issue creation, and ntfy notifications with
    proper error handling and durability guarantees.
    """

    def __init__(
        self,
        pr_client: PRClient,
        dispatcher: ReviewerDispatcher,
        verdict_parser: VerdictParser,
        verdict_store: VerdictStoreClient,
        issue_creator: IssueCreator,
        notification_publisher: NotificationPublisher,
    ) -> None:
        """Initialize worker with required service dependencies.

        Args:
            pr_client: GitHub API client for PR operations
            dispatcher: Reviewer dispatcher for parallel execution
            verdict_parser: Parser for reviewer responses
            verdict_store: Database client for verdict persistence
            issue_creator: GitHub API client for issue creation
            notification_publisher: ntfy publisher for notifications
        """
        self.pr_client = pr_client
        self.dispatcher = dispatcher
        self.verdict_parser = verdict_parser
        self.verdict_store = verdict_store
        self.issue_creator = issue_creator
        self.notification_publisher = notification_publisher
        logger.info("ReviewWorker initialized")

    async def process_review(
        self,
        delivery_id: str,
        repo: str,
        pr_number: int,
    ) -> None:
        """Process a complete review pipeline for a pull request.

        Pipeline stages:
        1. Retrieve project record and PR diff
        2. Load agent files and project context
        3. Dispatch reviewers in parallel
        4. Parse verdicts and extract findings
        5. Write verdicts to Verdict Store (critical durability point)
        6. Create GitHub issues for findings above threshold
        7. Publish ntfy notification

        Args:
            delivery_id: GitHub webhook delivery ID for deduplication
            repo: Repository in format "owner/name"
            pr_number: Pull request number

        Raises:
            WorkerError: If critical pipeline stages fail
        """
        logger.info(
            "Starting review processing",
            delivery_id=delivery_id,
            repo=repo,
            pr_number=pr_number,
        )

        try:
            # Stage 1: Get project record and PR diff
            project_record = self.verdict_store.get_project_by_repo(repo)
            if not project_record or project_record.id is None:
                raise WorkerError(f"Project not found in registry: {repo}")

            pr_diff = await self.pr_client.get_pr_diff(repo, pr_number)
            logger.info(
                "PR diff retrieved",
                pr_sha=pr_diff.pr_sha[:8],
                pr_size_lines=pr_diff.pr_size_lines,
                changed_files=len(pr_diff.changed_files),
            )

            # Stage 2: Load agent files and project context
            agent_files, project_context = await self._load_project_artifacts(repo, pr_diff.pr_sha)

            # Stage 3: Dispatch reviewers in parallel (blind execution)
            review_results = await self.dispatcher.dispatch_reviewers(
                agent_files, pr_diff, project_context
            )

            if not review_results:
                raise WorkerError("No successful reviewer results")

            logger.info(
                "Reviewers completed",
                successful_reviewers=[r.reviewer for r in review_results],
                total_results=len(review_results),
            )

            # Stage 4: Parse verdicts and extract findings
            parsed_verdicts = []
            all_findings = []

            # Extract invariant list for citation validation
            invariants = project_context.get("invariants", [])
            invariant_ids: list[str] = []
            for inv in invariants:
                if isinstance(inv, dict) and inv.get("id") is not None:
                    invariant_id = inv.get("id")
                    if isinstance(invariant_id, str):
                        invariant_ids.append(invariant_id)
            self.verdict_parser.project_invariants = set(invariant_ids)

            for result in review_results:
                verdict = self.verdict_parser.parse_verdict(result.raw_response, result.reviewer)
                parsed_verdicts.append((verdict, result))
                all_findings.extend(verdict.findings)

            # Determine highest severity
            highest_severity = self._determine_highest_severity(parsed_verdicts)

            logger.info(
                "Verdicts parsed",
                verdict_count=len(parsed_verdicts),
                total_findings=len(all_findings),
                highest_severity=highest_severity,
            )

            # Stage 5: Write verdicts to Verdict Store (CRITICAL: must succeed before issues)
            verdict_ids = []
            for verdict, result in parsed_verdicts:
                verdict_record = VerdictRecord(
                    delivery_id=delivery_id,
                    project_id=project_record.id,
                    pr_number=pr_number,
                    pr_sha=pr_diff.pr_sha,
                    pr_size_lines=pr_diff.pr_size_lines,
                    reviewer=verdict.reviewer,
                    severity=verdict.severity,
                    good=verdict.good,
                    bad=verdict.bad,
                    ugly=verdict.ugly,
                    closing_question=verdict.closing_question,
                    raw_response=result.raw_response,
                    template_version=result.template_version,
                )

                verdict_id = self.verdict_store.write_verdict(verdict_record)
                verdict_ids.append(verdict_id)

                # Write findings for this verdict
                if verdict.findings:
                    finding_records = [
                        FindingRecord(
                            verdict_id=verdict_id,
                            bucket=finding.bucket,
                            text=finding.text,
                            severity=finding.severity,
                            invariant_id=finding.invariant_id,
                        )
                        for finding in verdict.findings
                    ]
                    self.verdict_store.write_findings(verdict_id, finding_records)

            logger.info(
                "Verdicts written to store",
                verdict_ids=verdict_ids,
                delivery_id=delivery_id,
            )

            # Stage 6: Create GitHub issues for findings above threshold (recoverable failure)
            try:
                issue_numbers = await self.issue_creator.create_finding_issues(
                    repo=repo,
                    findings=all_findings,
                    pr_number=pr_number,
                    pr_sha=pr_diff.pr_sha,
                    severity_threshold="WARN",
                )

                if issue_numbers:
                    logger.info(
                        "Issues created",
                        issue_numbers=issue_numbers,
                        issue_count=len(issue_numbers),
                    )

            except Exception as e:
                logger.warning(
                    "Issue creation failed but continuing pipeline",
                    error=str(e),
                    error_type=type(e).__name__,
                )

            # Stage 7: Publish ntfy notification (recoverable failure)
            try:
                topic = f"harness-{project_record.stonehaven_id[:8]}"
                await self.notification_publisher.publish_review_complete(
                    topic=topic,
                    project_name=project_record.project_name,
                    pr_number=pr_number,
                    highest_severity=highest_severity,
                    finding_count=len(all_findings),
                )

                logger.info(
                    "Notification published",
                    topic=topic,
                    highest_severity=highest_severity,
                )

            except Exception as e:
                logger.warning(
                    "Notification publishing failed but review completed",
                    error=str(e),
                    error_type=type(e).__name__,
                )

            logger.info(
                "Review processing completed successfully",
                delivery_id=delivery_id,
                repo=repo,
                pr_number=pr_number,
                highest_severity=highest_severity,
                total_findings=len(all_findings),
            )

        except Exception as e:
            logger.error(
                "Review processing failed",
                delivery_id=delivery_id,
                repo=repo,
                pr_number=pr_number,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise WorkerError(f"Review processing failed for {repo} PR #{pr_number}: {e}") from e

    async def _load_project_artifacts(
        self, repo: str, pr_sha: str
    ) -> tuple[dict[str, Path], dict[str, Any]]:
        """Load agent files and project context for the repository.

        Args:
            repo: Repository in format "owner/name"
            pr_sha: Git SHA to retrieve files from

        Returns:
            Tuple of (agent_files_map, project_context_dict)

        Raises:
            WorkerError: If required artifacts cannot be loaded
        """
        try:
            # Load project context from .factory/project_context.md
            context_content = await self.pr_client.get_file_content(
                repo, ".factory/project_context.md", pr_sha
            )

            # Parse YAML frontmatter from project context
            import re

            import yaml

            yaml_match = re.match(r"^---\s*\n(.*?)\n---", context_content, re.DOTALL)
            if not yaml_match:
                raise WorkerError("No YAML frontmatter found in project_context.md")

            project_context = yaml.safe_load(yaml_match.group(1))

            # Load agent files from .factory/agents/
            agent_files = {}
            reviewers_config = project_context.get("reviewers", {})

            for reviewer_name, reviewer_config in reviewers_config.items():
                if reviewer_config.get("enabled", False):
                    agent_file_path = f".factory/agents/{reviewer_name}.md"
                    try:
                        agent_content = await self.pr_client.get_file_content(
                            repo, agent_file_path, pr_sha
                        )
                        # Store as Path-like object for dispatcher compatibility
                        # We'll create a temporary file path for the dispatcher
                        temp_path = Path(f"/tmp/agent_{reviewer_name}.md")
                        temp_path.write_text(agent_content)
                        agent_files[reviewer_name] = temp_path

                    except Exception as agent_error:
                        logger.warning(
                            "Failed to load agent file, skipping reviewer",
                            reviewer=reviewer_name,
                            agent_file=agent_file_path,
                            error=str(agent_error),
                        )

            if not agent_files:
                raise WorkerError("No agent files could be loaded")

            logger.info(
                "Project artifacts loaded",
                repo=repo,
                loaded_agents=list(agent_files.keys()),
                project_name=project_context.get("project", {}).get("name", "unknown"),
            )

            return agent_files, project_context

        except Exception as e:
            logger.error(
                "Failed to load project artifacts",
                repo=repo,
                pr_sha=pr_sha[:8],
                error=str(e),
                error_type=type(e).__name__,
            )
            raise WorkerError(f"Could not load project artifacts for {repo}: {e}") from e

    def _determine_highest_severity(self, parsed_verdicts: list[tuple[Any, Any]]) -> str:
        """Determine the highest severity level across all verdicts.

        Args:
            parsed_verdicts: List of (ParsedVerdict, ReviewResult) tuples

        Returns:
            Highest severity: "BLOCK", "WARN", or "PASS"
        """
        severities = [verdict.severity for verdict, _ in parsed_verdicts]

        if "BLOCK" in severities:
            return "BLOCK"
        elif "WARN" in severities:
            return "WARN"
        else:
            return "PASS"

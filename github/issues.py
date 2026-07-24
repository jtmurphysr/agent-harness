"""GitHub issue creation for triumvirate review findings.

This module creates GitHub issues from normalized review findings extracted from
verdict buckets. It filters findings by severity threshold and includes PR context
and invariant links in issue bodies.

Domain warnings:
⚠️ WARNING: Issue creation after Verdict Store write — Verdict Store must succeed first
⚠️ WARNING: Severity threshold filtering — Only create issues for findings above threshold
⚠️ WARNING: Link back to source PR/commit SHA in issue body
"""

import asyncio
from typing import Any

import httpx
import structlog
from pydantic import BaseModel

from reviewers.verdicts import Finding

__all__ = ["IssueCreationError", "IssueCreator"]

logger = structlog.get_logger(__name__)


class IssueCreationError(Exception):
    """Raised when GitHub issue creation fails."""

    pass


class CreatedIssue(BaseModel):
    """Information about a successfully created issue."""

    issue_number: int
    issue_url: str
    finding_text: str


class IssueCreator:
    """GitHub API client for creating issues from review findings."""

    def __init__(self, github_token: str) -> None:
        """Initialize GitHub client with authentication token.

        Args:
            github_token: GitHub personal access token with issues:write permission
        """
        self._token = github_token
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "agent-harness/1.0",
            },
            timeout=30.0,
        )
        logger.info("IssueCreator initialized")

    async def __aenter__(self) -> "IssueCreator":
        """Async context manager entry."""
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def create_finding_issues(
        self,
        repo: str,
        findings: list[Finding],
        pr_number: int,
        pr_sha: str,
        severity_threshold: str = "WARN",
    ) -> list[int]:
        """Create GitHub issues for findings above severity threshold.

        Args:
            repo: Repository in format "owner/name"
            findings: List of findings to potentially create issues for
            pr_number: Source pull request number
            pr_sha: Source commit SHA
            severity_threshold: Minimum severity to create issues for (WARN or BLOCK)

        Returns:
            List of created issue numbers

        Raises:
            IssueCreationError: If issue creation fails
        """
        logger.info(
            "Creating issues for findings",
            repo=repo,
            pr_number=pr_number,
            pr_sha=pr_sha[:8],
            total_findings=len(findings),
            severity_threshold=severity_threshold,
        )

        # Filter findings by severity threshold
        filtered_findings = self._filter_findings_by_severity(findings, severity_threshold)

        if not filtered_findings:
            logger.info("No findings above severity threshold", threshold=severity_threshold)
            return []

        logger.info(
            "Filtered findings for issue creation",
            filtered_count=len(filtered_findings),
            threshold=severity_threshold,
        )

        # Create issues concurrently for better performance
        create_tasks = [
            self._create_single_issue(repo, finding, pr_number, pr_sha)
            for finding in filtered_findings
        ]

        try:
            created_issues = await asyncio.gather(*create_tasks)
            issue_numbers = [issue.issue_number for issue in created_issues if issue]

            logger.info(
                "Issues created successfully",
                repo=repo,
                pr_number=pr_number,
                created_count=len(issue_numbers),
                issue_numbers=issue_numbers,
            )

            return issue_numbers

        except Exception as e:
            logger.error(
                "Issue creation failed",
                repo=repo,
                pr_number=pr_number,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise IssueCreationError(
                f"Failed to create issues for {repo} PR #{pr_number}: {e}"
            ) from e

    def _filter_findings_by_severity(
        self, findings: list[Finding], threshold: str
    ) -> list[Finding]:
        """Filter findings by severity threshold.

        Args:
            findings: List of findings to filter
            threshold: Minimum severity threshold (WARN or BLOCK)

        Returns:
            Filtered list of findings at or above threshold
        """
        if threshold == "BLOCK":
            # Only BLOCK severity findings
            return [f for f in findings if f.severity == "BLOCK"]
        elif threshold == "WARN":
            # WARN and BLOCK severity findings
            return [f for f in findings if f.severity in ("WARN", "BLOCK")]
        else:
            logger.warning(
                "Unknown severity threshold, including all findings", threshold=threshold
            )
            return findings

    async def _create_single_issue(
        self,
        repo: str,
        finding: Finding,
        pr_number: int,
        pr_sha: str,
    ) -> CreatedIssue | None:
        """Create a single GitHub issue for a finding.

        Args:
            repo: Repository in format "owner/name"
            finding: Finding to create issue for
            pr_number: Source pull request number
            pr_sha: Source commit SHA

        Returns:
            CreatedIssue object if successful, None if failed

        Raises:
            IssueCreationError: If issue creation fails
        """
        # Generate issue title and body
        title = self._generate_issue_title(finding)
        body = self._generate_issue_body(finding, pr_number, pr_sha, repo)

        # Create the issue via GitHub API
        url = f"https://api.github.com/repos/{repo}/issues"
        payload = {
            "title": title,
            "body": body,
            "labels": [
                "triumvirate",
                f"severity-{finding.severity.lower()}",
                f"bucket-{finding.bucket}",
            ],
        }

        try:
            response = await self._client.post(url, json=payload)

            if response.status_code == 201:
                issue_data = response.json()
                created_issue = CreatedIssue(
                    issue_number=issue_data["number"],
                    issue_url=issue_data["html_url"],
                    finding_text=finding.text,
                )

                logger.info(
                    "Issue created successfully",
                    repo=repo,
                    issue_number=created_issue.issue_number,
                    severity=finding.severity,
                    bucket=finding.bucket,
                )

                return created_issue

            elif response.status_code == 403:
                raise IssueCreationError(f"Access forbidden: {response.text}")
            elif response.status_code == 404:
                raise IssueCreationError(f"Repository not found: {repo}")
            elif response.status_code == 422:
                raise IssueCreationError(f"Invalid issue data: {response.text}")
            else:
                raise IssueCreationError(
                    f"GitHub API error: {response.status_code} - {response.text}"
                )

        except httpx.RequestError as e:
            raise IssueCreationError(f"GitHub API request failed: {e!s}") from e

    def _generate_issue_title(self, finding: Finding) -> str:
        """Generate a concise issue title from finding text.

        Args:
            finding: Finding to generate title for

        Returns:
            Issue title string
        """
        # Truncate finding text to reasonable title length
        max_title_length = 80
        text = finding.text.strip()

        # Remove common prefixes and suffixes
        text = text.removeprefix("- ").removeprefix("* ").removeprefix("• ")

        # Take first sentence or first line if longer than max length
        if ". " in text:
            first_sentence = text.split(". ")[0] + "."
            if len(first_sentence) <= max_title_length:
                text = first_sentence

        if len(text) > max_title_length:
            text = text[: max_title_length - 3] + "..."

        # Add severity and bucket prefix
        prefix = f"[{finding.severity}/{finding.bucket.upper()}]"
        return f"{prefix} {text}"

    def _generate_issue_body(self, finding: Finding, pr_number: int, pr_sha: str, repo: str) -> str:
        """Generate comprehensive issue body with context and links.

        Args:
            finding: Finding to generate body for
            pr_number: Source pull request number
            pr_sha: Source commit SHA
            repo: Repository name

        Returns:
            Issue body markdown
        """
        # Build the issue body with sections
        body_parts = []

        # Finding details section
        body_parts.append("## Finding Details")
        body_parts.append(f"**Severity:** {finding.severity}")
        body_parts.append(f"**Source Bucket:** {finding.bucket}")
        body_parts.append("")
        body_parts.append(finding.text)
        body_parts.append("")

        # Invariant reference section
        if finding.invariant_id:
            body_parts.append("## Invariant Reference")
            body_parts.append(
                f"This finding relates to project invariant: `{finding.invariant_id}`"
            )
            body_parts.append("")

        # Source context section
        body_parts.append("## Source Context")
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"
        commit_url = f"https://github.com/{repo}/commit/{pr_sha}"

        body_parts.append(f"**Source PR:** #{pr_number} - {pr_url}")
        body_parts.append(f"**Commit SHA:** `{pr_sha}` - {commit_url}")
        body_parts.append("")

        # Triumvirate metadata section
        body_parts.append("---")
        body_parts.append(
            "*This issue was automatically created by the Triumvirate Review Subsystem.*"
        )

        return "\n".join(body_parts)

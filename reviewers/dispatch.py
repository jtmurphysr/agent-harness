"""Parallel reviewer invocation for triumvirate code review."""

import asyncio
import time
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel

from github.pr import PRDiff
from reviewers.models import ModelResolver

__all__ = ["DispatchError", "ReviewResult", "ReviewerDispatcher"]

logger = structlog.get_logger(__name__)


class DispatchError(Exception):
    """Raised when reviewer dispatch fails."""

    pass


class ReviewResult(BaseModel):
    """Result from a single reviewer execution."""

    reviewer: str
    raw_response: str
    template_version: str
    duration_ms: int


class ReviewerDispatcher:
    """Dispatches multiple reviewers in parallel for code review."""

    def __init__(self, model_resolver: ModelResolver) -> None:
        """Initialize dispatcher with model resolver.

        Args:
            model_resolver: Resolver for model classes to concrete configurations
        """
        self.model_resolver = model_resolver
        self._cost_tracker: dict[str, float] = {}
        logger.info("ReviewerDispatcher initialized")

    async def dispatch_reviewers(
        self,
        agent_files: dict[str, Path],
        pr_diff: PRDiff,
        project_context: dict[str, Any],
    ) -> list[ReviewResult]:
        """Dispatch reviewers in parallel for code review.

        Args:
            agent_files: Mapping of reviewer names to agent file paths
            pr_diff: Pull request diff data
            project_context: Project context from project_context.md

        Returns:
            List of ReviewResult objects from all successful reviewers

        Raises:
            DispatchError: If all reviewers fail or critical errors occur
        """
        logger.info(
            "Starting reviewer dispatch",
            reviewers=list(agent_files.keys()),
            pr_number=pr_diff.pr_number,
            pr_size_lines=pr_diff.pr_size_lines,
        )

        # Prepare reviewer tasks
        tasks = []
        for reviewer_name, agent_file_path in agent_files.items():
            task = self._dispatch_single_reviewer(
                reviewer_name, agent_file_path, pr_diff, project_context
            )
            tasks.append(task)

        # Execute all reviewers in parallel with blind execution
        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_duration = (time.time() - start_time) * 1000

        logger.info(
            "Reviewer dispatch completed",
            total_duration_ms=total_duration,
            total_reviewers=len(tasks),
        )

        # Filter successful results and handle failures
        successful_results: list[ReviewResult] = []
        failed_reviewers: list[str] = []

        for i, result in enumerate(results):
            reviewer_name = list(agent_files.keys())[i]
            if isinstance(result, Exception):
                logger.warning(
                    "Reviewer failed",
                    reviewer=reviewer_name,
                    error=str(result),
                    error_type=type(result).__name__,
                )
                failed_reviewers.append(reviewer_name)
            elif isinstance(result, ReviewResult):
                successful_results.append(result)
                logger.info("Reviewer completed successfully", reviewer=reviewer_name)

        # Check if we have any successful results
        if not successful_results:
            raise DispatchError(f"All reviewers failed: {', '.join(failed_reviewers)}")

        if failed_reviewers:
            logger.warning(
                "Some reviewers failed but continuing with successful results",
                failed_reviewers=failed_reviewers,
                successful_reviewers=[r.reviewer for r in successful_results],
            )

        return successful_results

    async def _dispatch_single_reviewer(
        self,
        reviewer_name: str,
        agent_file_path: Path,
        pr_diff: PRDiff,
        project_context: dict[str, Any],
    ) -> ReviewResult:
        """Dispatch a single reviewer with fallback support.

        Args:
            reviewer_name: Name of the reviewer (engineer, architect, sre)
            agent_file_path: Path to the reviewer's agent file
            pr_diff: Pull request diff data
            project_context: Project context from project_context.md

        Returns:
            ReviewResult from the reviewer execution

        Raises:
            DispatchError: If reviewer execution fails completely
        """
        start_time = time.time()

        try:
            # Load agent prompt
            if not agent_file_path.exists():
                raise DispatchError(f"Agent file not found: {agent_file_path}")

            with open(agent_file_path) as f:
                agent_prompt = f.read()

            # Extract template version from agent file header
            template_version = self._extract_template_version(agent_prompt)

            # Get reviewer configuration from project context
            reviewers_config = project_context.get("reviewers", {})
            reviewer_config = reviewers_config.get(reviewer_name, {})

            if not reviewer_config.get("enabled", False):
                raise DispatchError(f"Reviewer {reviewer_name} is disabled")

            # Resolve model configuration
            model_class = reviewer_config.get("model_class")
            if not model_class:
                raise DispatchError(f"No model class configured for reviewer {reviewer_name}")

            model_config = self.model_resolver.resolve_model(model_class, project_context)

            logger.info(
                "Invoking reviewer",
                reviewer=reviewer_name,
                model_class=model_class,
                model_name=model_config.model_name,
                template_version=template_version,
            )

            # Try local inference first, fallback to Claudegate
            try:
                response = await self._invoke_local_inference(agent_prompt, pr_diff, model_config)
            except Exception as local_error:
                logger.warning(
                    "Local inference failed, trying Claudegate fallback",
                    reviewer=reviewer_name,
                    error=str(local_error),
                )
                response = await self._invoke_claudegate_fallback(
                    agent_prompt, pr_diff, model_config, project_context
                )

            duration_ms = int((time.time() - start_time) * 1000)

            return ReviewResult(
                reviewer=reviewer_name,
                raw_response=response,
                template_version=template_version,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "Reviewer dispatch failed",
                reviewer=reviewer_name,
                duration_ms=duration_ms,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise DispatchError(f"Reviewer {reviewer_name} failed: {e}") from e

    def _extract_template_version(self, agent_prompt: str) -> str:
        """Extract template version from agent file header.

        Args:
            agent_prompt: Content of the agent file

        Returns:
            Template version string, defaults to "unknown" if not found
        """
        lines = agent_prompt.split("\n")
        for line in lines[:10]:  # Check first 10 lines for header
            if "Source:" in line and "template.md" in line:
                # Look for pattern like "engineer.template.md v1.4.2"
                import re

                match = re.search(r"v(\d+\.\d+\.\d+)", line)
                if match:
                    return match.group(1)
        return "unknown"

    async def _invoke_local_inference(
        self, agent_prompt: str, pr_diff: PRDiff, model_config: Any
    ) -> str:
        """Invoke local Pi5 cluster inference.

        This is a stub implementation - actual local inference would connect
        to the Pi5 cluster LLM API.

        Args:
            agent_prompt: The reviewer's agent prompt
            pr_diff: Pull request diff data
            model_config: Model configuration

        Returns:
            Raw response from local inference

        Raises:
            Exception: If local inference is unavailable or fails
        """
        # This is a stub - actual implementation would connect to Pi5 cluster
        # For now, we'll simulate a failure to test fallback
        raise Exception("Local inference not available (stub implementation)")

    async def _invoke_claudegate_fallback(
        self,
        agent_prompt: str,
        pr_diff: PRDiff,
        model_config: Any,
        project_context: dict[str, Any],
    ) -> str:
        """Invoke Claudegate (Anthropic API proxy) as fallback.

        Args:
            agent_prompt: The reviewer's agent prompt
            pr_diff: Pull request diff data
            model_config: Model configuration
            project_context: Project context for cost cap checking

        Returns:
            Raw response from Claudegate

        Raises:
            DispatchError: If fallback fails or cost cap exceeded
        """
        # Check cost cap
        monthly_cost_cap = project_context.get("monthly_cost_cap_usd", 50.0)
        project_name = project_context.get("project", {}).get("name", "unknown")
        current_cost = self._cost_tracker.get(project_name, 0.0)

        if current_cost >= monthly_cost_cap:
            raise DispatchError(
                f"Monthly cost cap of ${monthly_cost_cap} exceeded for project {project_name}"
            )

        # Construct review prompt combining agent prompt and PR diff
        # This is a stub implementation - actual Claudegate would make API call
        # For testing, we'll return a mock response
        logger.info(
            "Invoking Claudegate fallback",
            model_name=model_config.model_name,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            estimated_cost=0.10,  # Mock cost estimate
            pr_size_lines=pr_diff.pr_size_lines,
            changed_files=pr_diff.changed_files,
        )

        # Mock response for testing
        mock_response = """
## Good
- Code follows established patterns
- Tests are included

## Bad
- Minor style inconsistencies

## Ugly
- No blocking issues found

## Closing Question
Have you considered the performance implications of this change?
"""

        # Update cost tracker (mock cost)
        estimated_cost = 0.10  # Mock cost
        self._cost_tracker[project_name] = current_cost + estimated_cost

        return mock_response.strip()

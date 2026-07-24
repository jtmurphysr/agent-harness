"""ntfy notification publishing for review findings."""

from typing import Any

import httpx
import structlog

__all__ = ["NotificationError", "NotificationPublisher"]

logger = structlog.get_logger(__name__)


class NotificationError(Exception):
    """Raised when notification publishing fails."""

    pass


class NotificationPublisher:
    """ntfy notification publisher for review findings."""

    def __init__(self, ntfy_base_url: str) -> None:
        """Initialize ntfy publisher with base URL."""
        self._base_url = ntfy_base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": "agent-harness/1.0",
            },
            timeout=10.0,
        )

    async def __aenter__(self) -> "NotificationPublisher":
        """Async context manager entry."""
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def publish_review_complete(
        self,
        topic: str,
        project_name: str,
        pr_number: int,
        highest_severity: str,
        finding_count: int,
    ) -> None:
        """Publish review completion notification to ntfy topic.

        Args:
            topic: ntfy topic name (typically harness-{stonehaven_id[:8]})
            project_name: Name of the project being reviewed
            pr_number: Pull request number
            highest_severity: Highest severity across all findings (BLOCK, WARN, PASS)
            finding_count: Total number of findings

        Raises:
            NotificationError: When publishing fails
        """
        logger.info(
            "Publishing review completion notification",
            module="notifications/publisher",
            topic=topic,
            project_name=project_name,
            pr_number=pr_number,
            highest_severity=highest_severity,
            finding_count=finding_count,
        )

        # Determine priority based on highest severity
        priority_map = {
            "BLOCK": 5,  # Maximum priority
            "WARN": 3,  # Normal priority
            "PASS": 1,  # Low priority
        }
        priority = priority_map.get(highest_severity, 1)

        # Construct message based on severity and finding count
        if highest_severity == "BLOCK":
            title = f"BLOCKED: {project_name} PR#{pr_number}"
            if finding_count == 1:
                message = "🚫 Review found 1 blocking issue"
            else:
                message = f"🚫 Review found {finding_count} issues including blockers"
        elif highest_severity == "WARN":
            title = f"WARNINGS: {project_name} PR#{pr_number}"
            if finding_count == 1:
                message = "⚠️ Review found 1 warning"
            else:
                message = f"⚠️ Review found {finding_count} warnings"
        else:  # PASS
            title = f"CLEAN: {project_name} PR#{pr_number}"
            if finding_count == 0:
                message = "✅ Review completed with no issues"
            else:
                message = f"✅ Review completed with {finding_count} minor notes"

        url = f"{self._base_url}/{topic}"

        try:
            response = await self._client.post(
                url,
                content=message,
                headers={
                    "Title": title,
                    "Priority": str(priority),
                    "Tags": "agent-harness,review",
                },
            )
            response.raise_for_status()

            logger.info(
                "Review notification published successfully",
                module="notifications/publisher",
                topic=topic,
                priority=priority,
                response_status=response.status_code,
            )

        except httpx.HTTPError as e:
            error_msg = f"Failed to publish notification to topic '{topic}': {e}"
            logger.error(
                "Notification publishing failed",
                module="notifications/publisher",
                topic=topic,
                error=str(e),
                exception=type(e).__name__,
            )
            raise NotificationError(error_msg) from e

"""Manual triumvirate invocation for on-demand code reviews.

This module provides the ManualReviewService class for triggering triumvirate
reviews on demand for specific PRs, bypassing the webhook flow but using the
same review worker pipeline.

⚠️ WARNING: Manual review bypasses webhook flow but uses same worker
⚠️ WARNING: Used for PRs predating harness installation or re-review after fixes
⚠️ WARNING: Generates synthetic delivery ID if not provided
"""

import uuid

import structlog

from stonehaven.worker import ReviewWorker

__all__ = ["ManualReviewError", "ManualReviewService"]

logger = structlog.get_logger(__name__)


class ManualReviewError(Exception):
    """Raised when manual review fails."""

    pass


class ManualReviewService:
    """Service for triggering manual triumvirate reviews on demand.

    Provides the ability to review specific PRs outside the webhook flow,
    useful for PRs that predate harness installation or for re-reviewing
    after addressing earlier findings.
    """

    def __init__(self, worker: ReviewWorker) -> None:
        """Initialize manual review service.

        Args:
            worker: Review worker for processing reviews
        """
        self.worker = worker
        logger.info("ManualReviewService initialized")

    async def review_pr(
        self,
        repo: str,
        pr_number: int,
        delivery_id: str | None = None,
    ) -> None:
        """Trigger manual review for a specific pull request.

        Invokes the review worker to process a PR on demand, generating
        a synthetic delivery ID if not provided.

        Args:
            repo: Repository in format "owner/name"
            pr_number: Pull request number to review
            delivery_id: Optional delivery ID for deduplication.
                        If None, generates synthetic ID.

        Raises:
            ManualReviewError: If manual review fails
        """
        # Generate synthetic delivery ID if not provided
        if delivery_id is None:
            delivery_id = f"manual-{repo.replace('/', '-')}-{pr_number}-{uuid.uuid4().hex[:8]}"

        logger.info(
            "Starting manual review",
            repo=repo,
            pr_number=pr_number,
            delivery_id=delivery_id,
        )

        try:
            await self.worker.process_review(
                delivery_id=delivery_id,
                repo=repo,
                pr_number=pr_number,
            )

            logger.info(
                "Manual review completed successfully",
                repo=repo,
                pr_number=pr_number,
                delivery_id=delivery_id,
            )

        except Exception as e:
            logger.error(
                "Manual review failed",
                repo=repo,
                pr_number=pr_number,
                delivery_id=delivery_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise ManualReviewError(f"Manual review failed for {repo} PR #{pr_number}: {e}") from e

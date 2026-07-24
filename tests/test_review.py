"""Tests for cli/review.py - manual triumvirate invocation.

Test coverage for ManualReviewService class including:
- Manual PR review invocation
- Synthetic delivery ID generation
- Error handling scenarios
- Integration with review worker
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cli.review import ManualReviewError, ManualReviewService
from stonehaven.worker import ReviewWorker, WorkerError


@pytest.fixture
def mock_worker():
    """Mock ReviewWorker for testing."""
    return MagicMock(spec=ReviewWorker)


@pytest.fixture
def manual_review_service(mock_worker):
    """ManualReviewService instance with mocked dependencies."""
    return ManualReviewService(worker=mock_worker)


class TestManualReviewService:
    """Test cases for ManualReviewService."""

    def test_init(self, mock_worker):
        """Test ManualReviewService initialization."""
        service = ManualReviewService(worker=mock_worker)

        assert service.worker is mock_worker

    @pytest.mark.asyncio
    async def test_review_pr_manual_invocation(self, manual_review_service):
        """Test manual review invocation with explicit delivery ID."""
        repo = "owner/test-repo"
        pr_number = 123
        delivery_id = "test-delivery-id"

        # Mock worker.process_review as async
        manual_review_service.worker.process_review = AsyncMock()

        await manual_review_service.review_pr(
            repo=repo,
            pr_number=pr_number,
            delivery_id=delivery_id,
        )

        # Verify worker was called with correct parameters
        manual_review_service.worker.process_review.assert_called_once_with(
            delivery_id=delivery_id,
            repo=repo,
            pr_number=pr_number,
        )

    @pytest.mark.asyncio
    async def test_review_pr_synthetic_delivery_id(self, manual_review_service):
        """Test manual review with synthetic delivery ID generation."""
        repo = "owner/test-repo"
        pr_number = 123

        # Mock worker.process_review as async
        manual_review_service.worker.process_review = AsyncMock()

        with patch("uuid.uuid4") as mock_uuid:
            mock_uuid.return_value.hex = "abcdef123456789012345678"

            await manual_review_service.review_pr(
                repo=repo,
                pr_number=pr_number,
            )

            # Verify synthetic delivery ID was generated
            expected_delivery_id = "manual-owner-test-repo-123-abcdef12"
            manual_review_service.worker.process_review.assert_called_once_with(
                delivery_id=expected_delivery_id,
                repo=repo,
                pr_number=pr_number,
            )

    @pytest.mark.asyncio
    async def test_review_pr_existing_delivery_id(self, manual_review_service):
        """Test manual review with provided delivery ID."""
        repo = "owner/test-repo"
        pr_number = 456
        delivery_id = "existing-delivery-id-789"

        # Mock worker.process_review as async
        manual_review_service.worker.process_review = AsyncMock()

        await manual_review_service.review_pr(
            repo=repo,
            pr_number=pr_number,
            delivery_id=delivery_id,
        )

        # Verify provided delivery ID was used
        manual_review_service.worker.process_review.assert_called_once_with(
            delivery_id=delivery_id,
            repo=repo,
            pr_number=pr_number,
        )

    @pytest.mark.asyncio
    async def test_review_pr_invalid_repo(self, manual_review_service):
        """Test manual review with invalid repository."""
        repo = "invalid/repo"
        pr_number = 123

        # Mock worker.process_review to raise WorkerError
        manual_review_service.worker.process_review = AsyncMock(
            side_effect=WorkerError("Repository not found")
        )

        with pytest.raises(ManualReviewError, match="Manual review failed for invalid/repo PR #123"):
            await manual_review_service.review_pr(
                repo=repo,
                pr_number=pr_number,
            )

        # Verify worker was called despite error
        assert manual_review_service.worker.process_review.call_count == 1

    @pytest.mark.asyncio
    async def test_review_pr_invalid_pr_number(self, manual_review_service):
        """Test manual review with invalid PR number."""
        repo = "owner/test-repo"
        pr_number = 99999

        # Mock worker.process_review to raise WorkerError
        manual_review_service.worker.process_review = AsyncMock(
            side_effect=WorkerError("PR not found")
        )

        with pytest.raises(ManualReviewError, match="Manual review failed for owner/test-repo PR #99999"):
            await manual_review_service.review_pr(
                repo=repo,
                pr_number=pr_number,
            )

        # Verify worker was called despite error
        assert manual_review_service.worker.process_review.call_count == 1

    @pytest.mark.asyncio
    async def test_review_pr_worker_error_propagation(self, manual_review_service):
        """Test that worker errors are properly wrapped in ManualReviewError."""
        repo = "owner/test-repo"
        pr_number = 123

        # Mock worker.process_review to raise generic Exception
        error_message = "Unexpected worker failure"
        manual_review_service.worker.process_review = AsyncMock(
            side_effect=Exception(error_message)
        )

        with pytest.raises(ManualReviewError) as exc_info:
            await manual_review_service.review_pr(
                repo=repo,
                pr_number=pr_number,
            )

        # Verify error message includes original error
        assert error_message in str(exc_info.value)
        assert "Manual review failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_review_pr_successful_completion(self, manual_review_service):
        """Test successful manual review completion."""
        repo = "owner/test-repo"
        pr_number = 789

        # Mock worker.process_review as successful async operation
        manual_review_service.worker.process_review = AsyncMock()

        # Should complete without raising exceptions
        await manual_review_service.review_pr(
            repo=repo,
            pr_number=pr_number,
        )

        manual_review_service.worker.process_review.assert_called_once()

    @pytest.mark.asyncio
    async def test_review_pr_special_characters_in_repo(self, manual_review_service):
        """Test manual review with special characters in repo name."""
        repo = "org-name/repo.name"
        pr_number = 42

        # Mock worker.process_review as async
        manual_review_service.worker.process_review = AsyncMock()

        with patch("uuid.uuid4") as mock_uuid:
            mock_uuid.return_value.hex = "fedcba098765432109876543"

            await manual_review_service.review_pr(
                repo=repo,
                pr_number=pr_number,
            )

            # Verify synthetic delivery ID handles special characters
            expected_delivery_id = "manual-org-name-repo.name-42-fedcba09"
            manual_review_service.worker.process_review.assert_called_once_with(
                delivery_id=expected_delivery_id,
                repo=repo,
                pr_number=pr_number,
            )
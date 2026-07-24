"""Tests for cli/reconcile.py - missed webhook recovery.

Test coverage for ReconciliationService class including:
- Timestamp-based reconciliation
- Per-repo and fleet-wide reconciliation modes
- Integration with review worker
- Error handling scenarios
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cli.reconcile import ReconcileError, ReconciliationService
from github.pr import PRClient, PRError
from stonehaven.registry import ProjectRegistry
from stonehaven.worker import ReviewWorker, WorkerError
from verdict_store.client import ProjectRecord, VerdictStoreClient


@pytest.fixture
def mock_verdict_store():
    """Mock VerdictStoreClient for testing."""
    mock = MagicMock(spec=VerdictStoreClient)
    mock.db_path = "/tmp/test.db"
    return mock


@pytest.fixture
def mock_registry(mock_verdict_store):
    """Mock ProjectRegistry with VerdictStoreClient."""
    registry = MagicMock(spec=ProjectRegistry)
    registry.client = mock_verdict_store
    return registry


@pytest.fixture
def mock_pr_client():
    """Mock PRClient for testing."""
    return MagicMock(spec=PRClient)


@pytest.fixture
def mock_worker():
    """Mock ReviewWorker for testing."""
    return MagicMock(spec=ReviewWorker)


@pytest.fixture
def reconciliation_service(mock_registry, mock_pr_client, mock_worker):
    """ReconciliationService instance with mocked dependencies."""
    return ReconciliationService(
        registry=mock_registry,
        pr_client=mock_pr_client,
        worker=mock_worker,
    )


@pytest.fixture
def sample_project():
    """Sample project record for testing."""
    return ProjectRecord(
        id=1,
        stonehaven_id="test-uuid-1234",
        repo="owner/test-repo",
        project_name="Test Project",
        registered_at=datetime.now(timezone.utc),
        harness_version="1.0.0",
        active=True,
    )


@pytest.fixture
def sample_merged_prs():
    """Sample merged PR data for testing."""
    base_time = datetime.now(timezone.utc)
    return [
        {
            "number": 123,
            "merged_at": (base_time - timedelta(hours=1)).isoformat(),
            "title": "Add new feature",
            "sha": "abc123def456",
        },
        {
            "number": 124,
            "merged_at": (base_time - timedelta(hours=2)).isoformat(),
            "title": "Fix bug",
            "sha": "def456abc123",
        },
        {
            "number": 125,
            "merged_at": (base_time - timedelta(hours=3)).isoformat(),
            "title": "Update docs",
            "sha": "123abc456def",
        },
    ]


class TestReconciliationService:
    """Test cases for ReconciliationService."""

    def test_init(self, mock_registry, mock_pr_client, mock_worker):
        """Test ReconciliationService initialization."""
        service = ReconciliationService(
            registry=mock_registry,
            pr_client=mock_pr_client,
            worker=mock_worker,
        )

        assert service.registry is mock_registry
        assert service.pr_client is mock_pr_client
        assert service.worker is mock_worker

    @pytest.mark.asyncio
    async def test_reconcile_since_missing_verdicts(
        self, reconciliation_service, sample_project, sample_merged_prs
    ):
        """Test reconciliation when PRs have missing verdicts."""
        timestamp = datetime.now(timezone.utc) - timedelta(hours=4)
        repo = "owner/test-repo"

        # Mock registry behavior
        reconciliation_service.registry.get_project.return_value = sample_project

        # Mock PR client behavior
        with patch.object(reconciliation_service, '_get_merged_prs_since') as mock_get_prs, \
             patch.object(reconciliation_service, '_has_verdict') as mock_has_verdict:

            mock_get_prs.return_value = sample_merged_prs
            # First PR has verdict, others don't
            mock_has_verdict.side_effect = [True, False, False]

            # Mock worker.process_review as async
            reconciliation_service.worker.process_review = AsyncMock()

            result = await reconciliation_service.reconcile_since(timestamp, repo)

            # Assertions
            assert result["total_prs_checked"] == 3
            assert result["missing_verdicts"] == 2
            assert result["successful_reviews"] == 2
            assert result["failed_reviews"] == 0

            # Verify worker was called for missing verdicts
            assert reconciliation_service.worker.process_review.call_count == 2

    @pytest.mark.asyncio
    async def test_reconcile_since_no_missing_verdicts(
        self, reconciliation_service, sample_project, sample_merged_prs
    ):
        """Test reconciliation when all PRs already have verdicts."""
        timestamp = datetime.now(timezone.utc) - timedelta(hours=4)
        repo = "owner/test-repo"

        # Mock registry behavior
        reconciliation_service.registry.get_project.return_value = sample_project

        # Mock PR client behavior
        with patch.object(reconciliation_service, '_get_merged_prs_since') as mock_get_prs, \
             patch.object(reconciliation_service, '_has_verdict') as mock_has_verdict:

            mock_get_prs.return_value = sample_merged_prs
            # All PRs have verdicts
            mock_has_verdict.return_value = True

            # Mock worker.process_review as async
            reconciliation_service.worker.process_review = AsyncMock()

            result = await reconciliation_service.reconcile_since(timestamp, repo)

            # Assertions
            assert result["total_prs_checked"] == 3
            assert result["missing_verdicts"] == 0
            assert result["successful_reviews"] == 0
            assert result["failed_reviews"] == 0

            # Verify worker was never called
            reconciliation_service.worker.process_review.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconcile_since_specific_repo(
        self, reconciliation_service, sample_project, sample_merged_prs
    ):
        """Test reconciliation targeting a specific repository."""
        timestamp = datetime.now(timezone.utc) - timedelta(hours=4)
        repo = "owner/test-repo"

        # Mock registry behavior
        reconciliation_service.registry.get_project.return_value = sample_project

        with patch.object(reconciliation_service, '_reconcile_repo') as mock_reconcile_repo:
            mock_reconcile_repo.return_value = {
                "total_prs_checked": 2,
                "missing_verdicts": 1,
                "successful_reviews": 1,
                "failed_reviews": 0,
            }

            result = await reconciliation_service.reconcile_since(timestamp, repo)

            # Verify single repo was targeted
            mock_reconcile_repo.assert_called_once_with(repo, timestamp)
            assert result["total_prs_checked"] == 2
            assert result["missing_verdicts"] == 1

    @pytest.mark.asyncio
    async def test_reconcile_since_all_projects(self, reconciliation_service):
        """Test fleet-wide reconciliation across all registered projects."""
        timestamp = datetime.now(timezone.utc) - timedelta(hours=4)
        repos = ["owner/repo1", "owner/repo2"]

        with patch.object(reconciliation_service, '_get_all_registered_repos') as mock_get_repos, \
             patch.object(reconciliation_service, '_reconcile_repo') as mock_reconcile_repo:

            mock_get_repos.return_value = repos
            mock_reconcile_repo.side_effect = [
                {
                    "total_prs_checked": 2,
                    "missing_verdicts": 1,
                    "successful_reviews": 1,
                    "failed_reviews": 0,
                },
                {
                    "total_prs_checked": 3,
                    "missing_verdicts": 2,
                    "successful_reviews": 1,
                    "failed_reviews": 1,
                },
            ]

            result = await reconciliation_service.reconcile_since(timestamp)

            # Verify all repos were processed
            assert mock_reconcile_repo.call_count == 2
            assert result["total_prs_checked"] == 5
            assert result["missing_verdicts"] == 3
            assert result["successful_reviews"] == 2
            assert result["failed_reviews"] == 1

    @pytest.mark.asyncio
    async def test_reconcile_since_error_handling(self, reconciliation_service):
        """Test error handling during reconciliation."""
        timestamp = datetime.now(timezone.utc) - timedelta(hours=4)
        repo = "owner/test-repo"

        # Mock registry to raise error
        reconciliation_service.registry.get_project.side_effect = Exception("Registry error")

        with pytest.raises(ReconcileError, match="Reconciliation process failed"):
            await reconciliation_service.reconcile_since(timestamp, repo)

    @pytest.mark.asyncio
    async def test_reconcile_repo_with_review_failures(
        self, reconciliation_service, sample_project, sample_merged_prs
    ):
        """Test repository reconciliation handling review worker failures."""
        timestamp = datetime.now(timezone.utc) - timedelta(hours=4)
        repo = "owner/test-repo"

        with patch.object(reconciliation_service, '_get_merged_prs_since') as mock_get_prs, \
             patch.object(reconciliation_service, '_has_verdict') as mock_has_verdict:

            mock_get_prs.return_value = sample_merged_prs
            # All PRs missing verdicts
            mock_has_verdict.return_value = False

            # Mock worker to fail on some reviews
            reconciliation_service.worker.process_review = AsyncMock()
            reconciliation_service.worker.process_review.side_effect = [
                None,  # Success
                WorkerError("Review failed"),  # Failure
                None,  # Success
            ]

            result = await reconciliation_service._reconcile_repo(repo, timestamp)

            assert result["total_prs_checked"] == 3
            assert result["missing_verdicts"] == 3
            assert result["successful_reviews"] == 2
            assert result["failed_reviews"] == 1

    @pytest.mark.asyncio
    async def test_get_merged_prs_since(self, reconciliation_service):
        """Test fetching merged PRs since timestamp."""
        repo = "owner/test-repo"
        timestamp = datetime.now(timezone.utc) - timedelta(hours=4)

        # Mock PR response data
        pr_data = [
            {
                "number": 123,
                "merged_at": (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "title": "Test PR",
                "head": {"sha": "abc123"},
            }
        ]

        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.json.return_value = pr_data
        reconciliation_service.pr_client._request_with_retry = AsyncMock(return_value=mock_response)

        result = await reconciliation_service._get_merged_prs_since(repo, timestamp)

        assert len(result) == 1
        assert result[0]["number"] == 123
        assert result[0]["sha"] == "abc123"

    @pytest.mark.asyncio
    async def test_get_merged_prs_since_api_error(self, reconciliation_service):
        """Test handling GitHub API errors when fetching PRs."""
        repo = "owner/test-repo"
        timestamp = datetime.now(timezone.utc) - timedelta(hours=4)

        # Mock API error
        reconciliation_service.pr_client._request_with_retry = AsyncMock(
            side_effect=PRError("API rate limit exceeded")
        )

        with pytest.raises(ReconcileError, match="Failed to fetch merged PRs"):
            await reconciliation_service._get_merged_prs_since(repo, timestamp)

    @pytest.mark.asyncio
    async def test_has_verdict_existing(self, reconciliation_service, sample_project):
        """Test checking for existing verdicts."""
        repo = "owner/test-repo"
        pr_number = 123

        # Mock registry behavior
        reconciliation_service.registry.get_project.return_value = sample_project

        # Mock database query
        with patch('sqlite3.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = [1]  # Count > 0
            mock_conn.execute.return_value = mock_cursor
            mock_connect.return_value.__enter__.return_value = mock_conn

            result = await reconciliation_service._has_verdict(repo, pr_number)

            assert result is True

    @pytest.mark.asyncio
    async def test_has_verdict_missing(self, reconciliation_service, sample_project):
        """Test checking for missing verdicts."""
        repo = "owner/test-repo"
        pr_number = 123

        # Mock registry behavior
        reconciliation_service.registry.get_project.return_value = sample_project

        # Mock database query
        with patch('sqlite3.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = [0]  # Count = 0
            mock_conn.execute.return_value = mock_cursor
            mock_connect.return_value.__enter__.return_value = mock_conn

            result = await reconciliation_service._has_verdict(repo, pr_number)

            assert result is False

    @pytest.mark.asyncio
    async def test_has_verdict_database_error(self, reconciliation_service, sample_project):
        """Test handling database errors when checking verdicts."""
        repo = "owner/test-repo"
        pr_number = 123

        # Mock registry behavior
        reconciliation_service.registry.get_project.return_value = sample_project

        # Mock database error
        with patch('sqlite3.connect') as mock_connect:
            mock_connect.side_effect = sqlite3.Error("Database locked")

            with pytest.raises(ReconcileError, match="Database error checking verdicts"):
                await reconciliation_service._has_verdict(repo, pr_number)

    @pytest.mark.asyncio
    async def test_get_all_registered_repos(self, reconciliation_service):
        """Test fetching all registered repository names."""
        expected_repos = ["owner/repo1", "owner/repo2", "owner/repo3"]

        # Mock database query
        with patch('sqlite3.connect') as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = [(repo,) for repo in expected_repos]
            mock_conn.execute.return_value = mock_cursor
            mock_connect.return_value.__enter__.return_value = mock_conn

            result = await reconciliation_service._get_all_registered_repos()

            assert result == expected_repos

    @pytest.mark.asyncio
    async def test_get_all_registered_repos_database_error(self, reconciliation_service):
        """Test handling database errors when fetching registered repos."""
        # Mock database error
        with patch('sqlite3.connect') as mock_connect:
            mock_connect.side_effect = sqlite3.Error("Connection failed")

            with pytest.raises(ReconcileError, match="Database error fetching registered repos"):
                await reconciliation_service._get_all_registered_repos()

    @pytest.mark.asyncio
    async def test_reconcile_since_unregistered_repo(self, reconciliation_service):
        """Test reconciliation error for unregistered repository."""
        timestamp = datetime.now(timezone.utc) - timedelta(hours=4)
        repo = "owner/unregistered-repo"

        # Mock registry to return None for unregistered repo
        reconciliation_service.registry.get_project.return_value = None

        with pytest.raises(ReconcileError, match="Repository .* is not registered"):
            await reconciliation_service.reconcile_since(timestamp, repo)

    @pytest.mark.asyncio
    async def test_synthetic_delivery_id_generation(
        self, reconciliation_service, sample_project, sample_merged_prs
    ):
        """Test that synthetic delivery IDs are generated correctly for reconciliation."""
        timestamp = datetime.now(timezone.utc) - timedelta(hours=4)
        repo = "owner/test-repo"

        # Mock registry behavior
        reconciliation_service.registry.get_project.return_value = sample_project

        with patch.object(reconciliation_service, '_get_merged_prs_since') as mock_get_prs, \
             patch.object(reconciliation_service, '_has_verdict') as mock_has_verdict:

            mock_get_prs.return_value = [sample_merged_prs[0]]  # Single PR
            mock_has_verdict.return_value = False  # Missing verdict

            # Mock worker.process_review as async
            reconciliation_service.worker.process_review = AsyncMock()

            await reconciliation_service.reconcile_since(timestamp, repo)

            # Verify delivery ID format
            call_args = reconciliation_service.worker.process_review.call_args[1]
            delivery_id = call_args["delivery_id"]
            expected_prefix = f"reconcile-{repo.replace('/', '-')}-{sample_merged_prs[0]['number']}-"
            assert delivery_id.startswith(expected_prefix)
            assert call_args["repo"] == repo
            assert call_args["pr_number"] == sample_merged_prs[0]["number"]
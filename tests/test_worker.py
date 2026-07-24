"""Tests for stonehaven/worker.py review pipeline orchestration."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from github.issues import IssueCreator
from github.pr import PRClient, PRDiff
from notifications.publisher import NotificationPublisher
from reviewers.dispatch import ReviewerDispatcher, ReviewResult
from reviewers.verdicts import Finding, ParsedVerdict, VerdictParser
from stonehaven.worker import ReviewWorker, WorkerError
from verdict_store.client import ProjectRecord, VerdictStoreClient


class TestReviewWorker:
    """Test cases for ReviewWorker class."""

    @pytest.fixture
    def mock_pr_client(self) -> PRClient:
        """Mock PR client."""
        client = AsyncMock(spec=PRClient)
        return client

    @pytest.fixture
    def mock_dispatcher(self) -> ReviewerDispatcher:
        """Mock reviewer dispatcher."""
        dispatcher = AsyncMock(spec=ReviewerDispatcher)
        return dispatcher

    @pytest.fixture
    def mock_verdict_parser(self) -> VerdictParser:
        """Mock verdict parser."""
        parser = MagicMock(spec=VerdictParser)
        parser.project_invariants = set()
        return parser

    @pytest.fixture
    def mock_verdict_store(self) -> VerdictStoreClient:
        """Mock verdict store client."""
        store = MagicMock(spec=VerdictStoreClient)
        return store

    @pytest.fixture
    def mock_issue_creator(self) -> IssueCreator:
        """Mock issue creator."""
        creator = AsyncMock(spec=IssueCreator)
        return creator

    @pytest.fixture
    def mock_notification_publisher(self) -> NotificationPublisher:
        """Mock notification publisher."""
        publisher = AsyncMock(spec=NotificationPublisher)
        return publisher

    @pytest.fixture
    def review_worker(
        self,
        mock_pr_client: PRClient,
        mock_dispatcher: ReviewerDispatcher,
        mock_verdict_parser: VerdictParser,
        mock_verdict_store: VerdictStoreClient,
        mock_issue_creator: IssueCreator,
        mock_notification_publisher: NotificationPublisher,
    ) -> ReviewWorker:
        """Create ReviewWorker instance with mocked dependencies."""
        return ReviewWorker(
            pr_client=mock_pr_client,
            dispatcher=mock_dispatcher,
            verdict_parser=mock_verdict_parser,
            verdict_store=mock_verdict_store,
            issue_creator=mock_issue_creator,
            notification_publisher=mock_notification_publisher,
        )

    @pytest.fixture
    def sample_project_record(self) -> ProjectRecord:
        """Sample project record for testing."""
        return ProjectRecord(
            id=1,
            stonehaven_id="test-uuid-12345678",
            repo="test/repo",
            project_name="Test Project",
            registered_at=datetime.now(),
            harness_version="1.0.0",
            active=True,
        )

    @pytest.fixture
    def sample_pr_diff(self) -> PRDiff:
        """Sample PR diff for testing."""
        return PRDiff(
            pr_number=42,
            pr_sha="abcd1234567890",
            pr_size_lines=150,
            diff_content="diff --git a/test.py b/test.py\n+added line",
            changed_files=["test.py"],
        )

    @pytest.fixture
    def sample_project_context(self) -> dict:
        """Sample project context for testing."""
        return {
            "project": {"name": "Test Project"},
            "reviewers": {
                "engineer": {"enabled": True, "model_class": "code_review"},
                "architect": {"enabled": True, "model_class": "structural_review"},
                "sre": {"enabled": False, "model_class": "adversarial_review"},
            },
            "invariants": [
                {"id": "test_invariant", "rule": "Test rule", "severity": "correctness"}
            ],
        }

    @pytest.fixture
    def sample_review_results(self) -> list[ReviewResult]:
        """Sample review results from dispatcher."""
        return [
            ReviewResult(
                reviewer="engineer",
                raw_response="## Good\nCode looks good\n## Bad\nMinor issues\n## Ugly\nNone\n## Closing Question\nAll good?",
                template_version="1.0.0",
                duration_ms=2000,
            ),
            ReviewResult(
                reviewer="architect",
                raw_response="## Good\nStructure is fine\n## Bad\nNone\n## Ugly\nSecurity issue (invariant: test_invariant)\n## Closing Question\nConsidered alternatives?",
                template_version="1.0.0",
                duration_ms=2500,
            ),
        ]

    async def test_process_review_complete_flow(
        self,
        review_worker: ReviewWorker,
        mock_pr_client: PRClient,
        mock_dispatcher: ReviewerDispatcher,
        mock_verdict_parser: VerdictParser,
        mock_verdict_store: VerdictStoreClient,
        mock_issue_creator: IssueCreator,
        mock_notification_publisher: NotificationPublisher,
        sample_project_record: ProjectRecord,
        sample_pr_diff: PRDiff,
        sample_project_context: dict,
        sample_review_results: list[ReviewResult],
    ) -> None:
        """Test complete review processing flow."""
        # Setup mocks
        mock_verdict_store.get_project_by_repo.return_value = sample_project_record
        mock_pr_client.get_pr_diff.return_value = sample_pr_diff

        # Mock file content loading
        context_yaml = """---
project:
  name: Test Project
reviewers:
  engineer:
    enabled: true
    model_class: code_review
  architect:
    enabled: true
    model_class: structural_review
invariants:
  - id: test_invariant
    rule: Test rule
    severity: correctness
---
# Additional content
"""
        agent_content = "# Engineer agent prompt"

        mock_pr_client.get_file_content.side_effect = [
            context_yaml,  # project_context.md
            agent_content,  # engineer.md
            agent_content,  # architect.md
        ]

        mock_dispatcher.dispatch_reviewers.return_value = sample_review_results

        # Setup verdict parsing
        engineer_verdict = ParsedVerdict(
            reviewer="engineer",
            severity="WARN",
            good="Code looks good",
            bad="Minor issues",
            ugly=None,
            closing_question="All good?",
            findings=[
                Finding(bucket="bad", text="Minor issues", severity="WARN", invariant_id=None)
            ],
        )
        architect_verdict = ParsedVerdict(
            reviewer="architect",
            severity="BLOCK",
            good="Structure is fine",
            bad=None,
            ugly="Security issue (invariant: test_invariant)",
            closing_question="Considered alternatives?",
            findings=[
                Finding(
                    bucket="ugly",
                    text="Security issue (invariant: test_invariant)",
                    severity="BLOCK",
                    invariant_id="test_invariant",
                )
            ],
        )

        mock_verdict_parser.parse_verdict.side_effect = [engineer_verdict, architect_verdict]
        mock_verdict_store.write_verdict.side_effect = [1, 2]  # verdict IDs
        mock_issue_creator.create_finding_issues.return_value = [123, 124]

        with patch("pathlib.Path.write_text"), patch("tempfile.mkdtemp") as mock_mkdtemp:
            mock_mkdtemp.return_value = "/tmp"

            # Execute
            await review_worker.process_review(
                delivery_id="test-delivery-123",
                repo="test/repo",
                pr_number=42,
            )

        # Verify project lookup
        mock_verdict_store.get_project_by_repo.assert_called_once_with("test/repo")

        # Verify PR diff retrieval
        mock_pr_client.get_pr_diff.assert_called_once_with("test/repo", 42)

        # Verify project artifacts loading
        assert mock_pr_client.get_file_content.call_count >= 3

        # Verify reviewer dispatch
        mock_dispatcher.dispatch_reviewers.assert_called_once()

        # Verify verdict parsing
        assert mock_verdict_parser.parse_verdict.call_count == 2

        # Verify verdict store writes
        assert mock_verdict_store.write_verdict.call_count == 2
        assert mock_verdict_store.write_findings.call_count == 2

        # Verify issue creation
        mock_issue_creator.create_finding_issues.assert_called_once()

        # Verify notification
        mock_notification_publisher.publish_review_complete.assert_called_once()

    async def test_process_review_missing_project_context(
        self,
        review_worker: ReviewWorker,
        mock_verdict_store: VerdictStoreClient,
    ) -> None:
        """Test handling when project context is missing from repo."""
        # Setup: project not found in registry
        mock_verdict_store.get_project_by_repo.return_value = None

        # Execute and verify exception
        with pytest.raises(WorkerError, match="Project not found in registry"):
            await review_worker.process_review(
                delivery_id="test-delivery-123",
                repo="nonexistent/repo",
                pr_number=42,
            )

    async def test_process_review_verdict_store_write_first(
        self,
        review_worker: ReviewWorker,
        mock_pr_client: PRClient,
        mock_dispatcher: ReviewerDispatcher,
        mock_verdict_parser: VerdictParser,
        mock_verdict_store: VerdictStoreClient,
        mock_issue_creator: IssueCreator,
        mock_notification_publisher: NotificationPublisher,
        sample_project_record: ProjectRecord,
        sample_pr_diff: PRDiff,
        sample_review_results: list[ReviewResult],
    ) -> None:
        """Test that verdict store write occurs before issue creation."""
        # Setup mocks
        mock_verdict_store.get_project_by_repo.return_value = sample_project_record
        mock_pr_client.get_pr_diff.return_value = sample_pr_diff

        context_yaml = """---
project:
  name: Test Project
reviewers:
  engineer:
    enabled: true
    model_class: code_review
invariants: []
---
"""
        mock_pr_client.get_file_content.side_effect = [
            context_yaml,
            "# Agent content",
        ]

        mock_dispatcher.dispatch_reviewers.return_value = sample_review_results

        engineer_verdict = ParsedVerdict(
            reviewer="engineer",
            severity="WARN",
            good="Good",
            bad="Bad",
            ugly=None,
            closing_question="Question?",
            findings=[Finding(bucket="bad", text="Issue", severity="WARN", invariant_id=None)],
        )
        architect_verdict = ParsedVerdict(
            reviewer="architect",
            severity="WARN",
            good="Good",
            bad="Bad",
            ugly=None,
            closing_question="Question?",
            findings=[Finding(bucket="bad", text="Issue", severity="WARN", invariant_id=None)],
        )
        mock_verdict_parser.parse_verdict.side_effect = [engineer_verdict, architect_verdict]

        # Track call order
        call_order = []

        def track_verdict_write(*args):
            call_order.append("verdict_write")
            return 1

        def track_issue_create(*args, **kwargs):
            call_order.append("issue_create")
            return [123]

        mock_verdict_store.write_verdict.side_effect = track_verdict_write
        mock_issue_creator.create_finding_issues.side_effect = track_issue_create

        with patch("pathlib.Path.write_text"), patch("tempfile.mkdtemp", return_value="/tmp"):
            await review_worker.process_review(
                delivery_id="test-delivery-123",
                repo="test/repo",
                pr_number=42,
            )

        # Verify verdict store writes occurred before issue creation
        # Should have: verdict_write, verdict_write, issue_create
        assert call_order == ["verdict_write", "verdict_write", "issue_create"]

    async def test_process_review_partial_issue_creation_failure(
        self,
        review_worker: ReviewWorker,
        mock_pr_client: PRClient,
        mock_dispatcher: ReviewerDispatcher,
        mock_verdict_parser: VerdictParser,
        mock_verdict_store: VerdictStoreClient,
        mock_issue_creator: IssueCreator,
        mock_notification_publisher: NotificationPublisher,
        sample_project_record: ProjectRecord,
        sample_pr_diff: PRDiff,
        sample_review_results: list[ReviewResult],
    ) -> None:
        """Test that issue creation failure doesn't break the pipeline."""
        # Setup basic mocks
        mock_verdict_store.get_project_by_repo.return_value = sample_project_record
        mock_pr_client.get_pr_diff.return_value = sample_pr_diff

        context_yaml = """---
project:
  name: Test Project
reviewers:
  engineer:
    enabled: true
    model_class: code_review
invariants: []
---
"""
        mock_pr_client.get_file_content.side_effect = [context_yaml, "# Agent content"]
        
        # Use only one reviewer for this test
        single_review_result = [
            ReviewResult(
                reviewer="engineer",
                raw_response="## Good\nCode looks good\n## Bad\nMinor issues\n## Ugly\nNone\n## Closing Question\nAll good?",
                template_version="1.0.0",
                duration_ms=2000,
            )
        ]
        mock_dispatcher.dispatch_reviewers.return_value = single_review_result

        verdict = ParsedVerdict(
            reviewer="engineer",
            severity="WARN",
            good="Good",
            bad="Bad",
            ugly=None,
            closing_question="Question?",
            findings=[Finding(bucket="bad", text="Issue", severity="WARN", invariant_id=None)],
        )
        mock_verdict_parser.parse_verdict.return_value = verdict
        mock_verdict_store.write_verdict.return_value = 1

        # Make issue creation fail
        mock_issue_creator.create_finding_issues.side_effect = Exception("Issue creation failed")

        with patch("pathlib.Path.write_text"), patch("tempfile.mkdtemp", return_value="/tmp"):
            # Should not raise exception despite issue creation failure
            await review_worker.process_review(
                delivery_id="test-delivery-123",
                repo="test/repo",
                pr_number=42,
            )

        # Verify verdict was still written
        mock_verdict_store.write_verdict.assert_called_once()

        # Verify notification still attempted
        mock_notification_publisher.publish_review_complete.assert_called_once()

    async def test_process_review_notification_failure_non_blocking(
        self,
        review_worker: ReviewWorker,
        mock_pr_client: PRClient,
        mock_dispatcher: ReviewerDispatcher,
        mock_verdict_parser: VerdictParser,
        mock_verdict_store: VerdictStoreClient,
        mock_issue_creator: IssueCreator,
        mock_notification_publisher: NotificationPublisher,
        sample_project_record: ProjectRecord,
        sample_pr_diff: PRDiff,
        sample_review_results: list[ReviewResult],
    ) -> None:
        """Test that notification failure doesn't break the pipeline."""
        # Setup basic mocks
        mock_verdict_store.get_project_by_repo.return_value = sample_project_record
        mock_pr_client.get_pr_diff.return_value = sample_pr_diff

        context_yaml = """---
project:
  name: Test Project
reviewers:
  engineer:
    enabled: true
    model_class: code_review
invariants: []
---
"""
        mock_pr_client.get_file_content.side_effect = [context_yaml, "# Agent content"]
        
        # Use only one reviewer for this test
        single_review_result = [
            ReviewResult(
                reviewer="engineer",
                raw_response="## Good\nCode looks good\n## Bad\nMinor issues\n## Ugly\nNone\n## Closing Question\nAll good?",
                template_version="1.0.0",
                duration_ms=2000,
            )
        ]
        mock_dispatcher.dispatch_reviewers.return_value = single_review_result

        verdict = ParsedVerdict(
            reviewer="engineer",
            severity="WARN",
            good="Good",
            bad="Bad",
            ugly=None,
            closing_question="Question?",
            findings=[Finding(bucket="bad", text="Issue", severity="WARN", invariant_id=None)],
        )
        mock_verdict_parser.parse_verdict.return_value = verdict
        mock_verdict_store.write_verdict.return_value = 1
        mock_issue_creator.create_finding_issues.return_value = [123]

        # Make notification fail
        mock_notification_publisher.publish_review_complete.side_effect = Exception(
            "Notification failed"
        )

        with patch("pathlib.Path.write_text"), patch("tempfile.mkdtemp", return_value="/tmp"):
            # Should not raise exception despite notification failure
            await review_worker.process_review(
                delivery_id="test-delivery-123",
                repo="test/repo",
                pr_number=42,
            )

        # Verify verdict was still written
        mock_verdict_store.write_verdict.assert_called_once()

        # Verify issue creation still happened
        mock_issue_creator.create_finding_issues.assert_called_once()

    def test_determine_highest_severity(self, review_worker: ReviewWorker) -> None:
        """Test severity determination logic."""
        # Test BLOCK severity
        block_verdict = ParsedVerdict(
            reviewer="sre",
            severity="BLOCK",
            good=None,
            bad=None,
            ugly="Critical issue",
            closing_question=None,
            findings=[],
        )
        warn_verdict = ParsedVerdict(
            reviewer="engineer",
            severity="WARN",
            good=None,
            bad="Minor issue",
            ugly=None,
            closing_question=None,
            findings=[],
        )

        highest = review_worker._determine_highest_severity(
            [(block_verdict, None), (warn_verdict, None)]
        )
        assert highest == "BLOCK"

        # Test WARN severity
        highest = review_worker._determine_highest_severity([(warn_verdict, None)])
        assert highest == "WARN"

        # Test PASS severity
        pass_verdict = ParsedVerdict(
            reviewer="architect",
            severity="PASS",
            good="All good",
            bad=None,
            ugly=None,
            closing_question=None,
            findings=[],
        )
        highest = review_worker._determine_highest_severity([(pass_verdict, None)])
        assert highest == "PASS"

    async def test_load_project_artifacts_success(self, review_worker: ReviewWorker) -> None:
        """Test successful loading of project artifacts."""
        context_yaml = """---
project:
  name: Test Project
reviewers:
  engineer:
    enabled: true
    model_class: code_review
  architect:
    enabled: true
    model_class: structural_review
  sre:
    enabled: false
    model_class: adversarial_review
invariants: []
---
"""
        agent_content = "# Agent prompt"

        review_worker.pr_client.get_file_content.side_effect = [
            context_yaml,  # project_context.md
            agent_content,  # engineer.md
            agent_content,  # architect.md
        ]

        with patch("pathlib.Path.write_text"), patch("tempfile.mkdtemp", return_value="/tmp"):
            agent_files, project_context = await review_worker._load_project_artifacts(
                "test/repo", "abc123"
            )

        # Verify enabled agents were loaded
        assert "engineer" in agent_files
        assert "architect" in agent_files
        assert "sre" not in agent_files  # disabled

        # Verify project context parsed correctly
        assert project_context["project"]["name"] == "Test Project"
        assert len(project_context["reviewers"]) == 3

    async def test_load_project_artifacts_malformed_yaml(
        self, review_worker: ReviewWorker
    ) -> None:
        """Test handling of malformed project context YAML."""
        # Missing YAML frontmatter
        malformed_content = "# Just markdown, no YAML frontmatter"

        review_worker.pr_client.get_file_content.return_value = malformed_content

        with pytest.raises(WorkerError, match="No YAML frontmatter found"):
            await review_worker._load_project_artifacts("test/repo", "abc123")

    async def test_load_project_artifacts_no_enabled_agents(
        self, review_worker: ReviewWorker
    ) -> None:
        """Test handling when no agents are enabled."""
        context_yaml = """---
project:
  name: Test Project
reviewers:
  engineer:
    enabled: false
    model_class: code_review
  architect:
    enabled: false
    model_class: structural_review
invariants: []
---
"""

        review_worker.pr_client.get_file_content.return_value = context_yaml

        with pytest.raises(WorkerError, match="No agent files could be loaded"):
            await review_worker._load_project_artifacts("test/repo", "abc123")
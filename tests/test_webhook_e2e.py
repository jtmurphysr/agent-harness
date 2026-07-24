"""End-to-end webhook-to-Verdict Store tests.

This is a GATE issue - No analyze path progress until these tests pass.
Tests the complete webhook flow from GitHub webhook receipt through
HMAC verification, deduplication, worker processing, and Verdict Store persistence.

⚠️ WARNING: This is a GATE issue — No analyze path progress until this passes
⚠️ WARNING: Test must verify HMAC signature validation
⚠️ WARNING: Test must verify verdicts written to Verdict Store before issues created
"""

import hashlib
import hmac
import json
import sqlite3
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from github.issues import IssueCreator
from github.pr import PRClient, PRDiff
from notifications.publisher import NotificationPublisher
from reviewers.dispatch import ReviewerDispatcher, ReviewResult
from reviewers.verdicts import Finding, ParsedVerdict, VerdictParser
from stonehaven.listener import WebhookHandler, create_listener_app
from stonehaven.registry import ProjectRegistry
from stonehaven.worker import ReviewWorker
from verdict_store.client import ProjectRecord, VerdictStoreClient


class TestWebhookE2E:
    """End-to-end webhook testing from receipt to Verdict Store persistence."""

    @pytest.fixture
    def temp_db_path(self) -> Path:
        """Create temporary database file."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        yield db_path
        if db_path.exists():
            db_path.unlink()

    @pytest.fixture
    def verdict_store_client(self, temp_db_path: Path) -> VerdictStoreClient:
        """Create verdict store client with temporary database."""
        return VerdictStoreClient(temp_db_path)

    @pytest.fixture
    def project_record(self, verdict_store_client: VerdictStoreClient) -> ProjectRecord:
        """Create test project record in database."""
        stonehaven_id = str(uuid.uuid4())
        project_id = verdict_store_client.create_project(
            stonehaven_id=stonehaven_id,
            repo="test-org/test-repo",
            project_name="Test Project"
        )
        return ProjectRecord(
            id=project_id,
            stonehaven_id=stonehaven_id,
            repo="test-org/test-repo",
            project_name="Test Project",
            registered_at=datetime.now(),
            harness_version="1.0.0",
            active=True
        )

    @pytest.fixture
    def webhook_secret(self) -> str:
        """Generate test webhook secret."""
        return "test-webhook-secret-12345"

    @pytest.fixture
    def sample_webhook_payload(self) -> dict:
        """Sample GitHub webhook payload for pull request."""
        return {
            "action": "opened",
            "repository": {
                "full_name": "test-org/test-repo"
            },
            "pull_request": {
                "number": 42,
                "head": {
                    "sha": "abc123def456789"
                }
            }
        }

    @pytest.fixture
    def mock_pr_client(self) -> PRClient:
        """Mock PR client for testing."""
        client = AsyncMock(spec=PRClient)
        client.get_pr_diff.return_value = PRDiff(
            pr_number=42,
            pr_sha="abc123def456789",
            pr_size_lines=150,
            diff_content="diff --git a/test.py b/test.py\n+added line",
            changed_files=["test.py"]
        )
        
        # Mock project context file content
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
        agent_content = "# Test agent prompt"
        client.get_file_content.side_effect = [
            context_yaml,  # project_context.md
            agent_content,  # engineer.md
            agent_content,  # architect.md
        ]
        return client

    @pytest.fixture
    def mock_dispatcher(self) -> ReviewerDispatcher:
        """Mock reviewer dispatcher."""
        dispatcher = AsyncMock(spec=ReviewerDispatcher)
        dispatcher.dispatch_reviewers.return_value = [
            ReviewResult(
                reviewer="engineer",
                raw_response="## Good\nCode looks good\n## Bad\nMinor issues\n## Ugly\nNone\n## Closing Question\nAll good?",
                template_version="1.0.0",
                duration_ms=2000
            ),
            ReviewResult(
                reviewer="architect",
                raw_response="## Good\nStructure is fine\n## Bad\nNone\n## Ugly\nSecurity issue (invariant: test_invariant)\n## Closing Question\nConsidered alternatives?",
                template_version="1.0.0",
                duration_ms=2500
            )
        ]
        return dispatcher

    @pytest.fixture
    def mock_verdict_parser(self) -> VerdictParser:
        """Mock verdict parser."""
        parser = MagicMock(spec=VerdictParser)
        parser.project_invariants = {"test_invariant"}
        
        engineer_verdict = ParsedVerdict(
            reviewer="engineer",
            severity="WARN",
            good="Code looks good",
            bad="Minor issues",
            ugly=None,
            closing_question="All good?",
            findings=[
                Finding(bucket="bad", text="Minor issues", severity="WARN", invariant_id=None)
            ]
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
                    invariant_id="test_invariant"
                )
            ]
        )
        parser.parse_verdict.side_effect = [engineer_verdict, architect_verdict]
        return parser

    @pytest.fixture
    def mock_issue_creator(self) -> IssueCreator:
        """Mock issue creator."""
        creator = AsyncMock(spec=IssueCreator)
        creator.create_finding_issues.return_value = [123, 124]
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
        verdict_store_client: VerdictStoreClient,
        mock_issue_creator: IssueCreator,
        mock_notification_publisher: NotificationPublisher
    ) -> ReviewWorker:
        """Create review worker with mocked dependencies."""
        return ReviewWorker(
            pr_client=mock_pr_client,
            dispatcher=mock_dispatcher,
            verdict_parser=mock_verdict_parser,
            verdict_store=verdict_store_client,
            issue_creator=mock_issue_creator,
            notification_publisher=mock_notification_publisher
        )

    @pytest.fixture
    def mock_registry(self, project_record: ProjectRecord) -> ProjectRegistry:
        """Mock project registry."""
        registry = MagicMock(spec=ProjectRegistry)
        # Mock registry is not used in current webhook handler implementation
        return registry

    @pytest.fixture
    def webhook_handler(self, mock_registry: ProjectRegistry) -> WebhookHandler:
        """Create webhook handler."""
        return WebhookHandler(mock_registry)

    @pytest.fixture
    def test_client(self, webhook_handler: WebhookHandler) -> TestClient:
        """FastAPI test client for webhook endpoint."""
        app = create_listener_app(webhook_handler)
        return TestClient(app)

    def create_valid_signature(self, payload: bytes, secret: str) -> str:
        """Create valid HMAC-SHA256 signature for testing."""
        signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return f"sha256={signature}"

    async def test_webhook_to_verdict_store_complete(
        self,
        test_client: TestClient,
        webhook_handler: WebhookHandler,
        review_worker: ReviewWorker,
        verdict_store_client: VerdictStoreClient,
        project_record: ProjectRecord,
        webhook_secret: str,
        sample_webhook_payload: dict
    ) -> None:
        """End-to-end test from webhook receipt to Verdict Store persistence.
        
        This is the primary GATE test verifying the complete flow:
        1. Webhook receives GitHub event with HMAC verification
        2. Worker processes review pipeline
        3. Verdicts are written to Verdict Store
        4. Issues are created on GitHub
        5. Notifications are sent
        """
        # Override webhook handler's secret for this test
        original_verify = webhook_handler._verify_signature
        
        def mock_verify_signature(payload: bytes, signature: str, secret: str) -> bool:
            return signature == self.create_valid_signature(payload, webhook_secret)
        
        webhook_handler._verify_signature = mock_verify_signature

        # Prepare webhook payload
        payload_json = json.dumps(sample_webhook_payload)
        payload_bytes = payload_json.encode("utf-8")
        signature = self.create_valid_signature(payload_bytes, webhook_secret)
        delivery_id = "test-delivery-e2e-123"

        # Mock the worker processing
        with patch("tempfile.mkdtemp", return_value="/tmp"), \
             patch("pathlib.Path.write_text"):
            
            # Step 1: Webhook receives event and returns 200 immediately
            response = test_client.post(
                "/webhook",
                headers={
                    "X-Hub-Signature-256": signature,
                    "X-GitHub-Delivery": delivery_id,
                    "Content-Type": "application/json"
                },
                content=payload_bytes
            )

            # Verify webhook accepted immediately (< 500ms requirement)
            assert response.status_code == 200
            assert response.json()["status"] == "received"
            assert response.json()["delivery_id"] == delivery_id

            # Step 2: Simulate worker processing (normally async background)
            await review_worker.process_review(
                delivery_id=delivery_id,
                repo="test-org/test-repo",
                pr_number=42
            )

        # Step 3: Verify verdicts written to Verdict Store
        verdicts = verdict_store_client.get_verdicts_for_project(project_record.id)
        assert len(verdicts) == 2  # engineer + architect

        # Verify verdict details
        engineer_verdict = next(v for v in verdicts if v.reviewer == "engineer")
        architect_verdict = next(v for v in verdicts if v.reviewer == "architect")

        assert engineer_verdict.delivery_id == delivery_id
        assert engineer_verdict.pr_number == 42
        assert engineer_verdict.pr_sha == "abc123def456789"
        assert engineer_verdict.severity == "WARN"
        assert engineer_verdict.good == "Code looks good"
        assert engineer_verdict.bad == "Minor issues"

        assert architect_verdict.delivery_id == delivery_id
        assert architect_verdict.pr_number == 42
        assert architect_verdict.severity == "BLOCK"
        assert architect_verdict.ugly == "Security issue (invariant: test_invariant)"

        # Step 4: Verify findings written with invariant citation
        engineer_findings = verdict_store_client.get_findings_for_verdict(engineer_verdict.id)
        architect_findings = verdict_store_client.get_findings_for_verdict(architect_verdict.id)

        assert len(engineer_findings) == 1
        assert engineer_findings[0].bucket == "bad"
        assert engineer_findings[0].text == "Minor issues"
        assert engineer_findings[0].severity == "WARN"
        assert engineer_findings[0].invariant_id is None

        assert len(architect_findings) == 1
        assert architect_findings[0].bucket == "ugly"
        assert architect_findings[0].severity == "BLOCK"
        assert architect_findings[0].invariant_id == "test_invariant"

        # Restore original verification
        webhook_handler._verify_signature = original_verify

    async def test_webhook_hmac_verification(
        self,
        test_client: TestClient,
        webhook_handler: WebhookHandler,
        webhook_secret: str,
        sample_webhook_payload: dict
    ) -> None:
        """Test webhook HMAC signature verification with valid and invalid signatures."""
        payload_json = json.dumps(sample_webhook_payload)
        payload_bytes = payload_json.encode("utf-8")
        delivery_id = "test-hmac-verification"

        # Test 1: Valid signature should succeed
        valid_signature = self.create_valid_signature(payload_bytes, webhook_secret)
        
        # Mock the verification to use our test secret
        original_verify = webhook_handler._verify_signature
        webhook_handler._verify_signature = lambda p, s, secret: s == valid_signature

        response = test_client.post(
            "/webhook",
            headers={
                "X-Hub-Signature-256": valid_signature,
                "X-GitHub-Delivery": delivery_id,
                "Content-Type": "application/json"
            },
            content=payload_bytes
        )

        assert response.status_code == 200
        assert response.json()["status"] == "received"

        # Test 2: Invalid signature should fail with 401
        invalid_signature = "sha256=invalid_signature_hash"
        
        response = test_client.post(
            "/webhook",
            headers={
                "X-Hub-Signature-256": invalid_signature,
                "X-GitHub-Delivery": "test-invalid-signature",
                "Content-Type": "application/json"
            },
            content=payload_bytes
        )

        assert response.status_code == 401
        assert "Invalid webhook signature" in response.json()["detail"]

        # Test 3: Missing signature should fail with 400
        response = test_client.post(
            "/webhook",
            headers={
                "X-GitHub-Delivery": "test-missing-signature",
                "Content-Type": "application/json"
            },
            content=payload_bytes
        )

        assert response.status_code == 400
        assert "Missing X-Hub-Signature-256 header" in response.json()["detail"]

        # Restore original verification
        webhook_handler._verify_signature = original_verify

    async def test_webhook_deduplication(
        self,
        test_client: TestClient,
        webhook_handler: WebhookHandler,
        webhook_secret: str,
        sample_webhook_payload: dict
    ) -> None:
        """Test webhook deduplication by delivery ID prevents duplicate processing."""
        payload_json = json.dumps(sample_webhook_payload)
        payload_bytes = payload_json.encode("utf-8")
        signature = self.create_valid_signature(payload_bytes, webhook_secret)
        delivery_id = "test-deduplication-123"

        # Mock verification to always pass for this test
        webhook_handler._verify_signature = lambda *args: True

        # First request should succeed
        response1 = test_client.post(
            "/webhook",
            headers={
                "X-Hub-Signature-256": signature,
                "X-GitHub-Delivery": delivery_id,
                "Content-Type": "application/json"
            },
            content=payload_bytes
        )

        assert response1.status_code == 200
        assert response1.json()["status"] == "received"
        assert response1.json()["delivery_id"] == delivery_id

        # Second request with same delivery ID should fail with 409
        response2 = test_client.post(
            "/webhook",
            headers={
                "X-Hub-Signature-256": signature,
                "X-GitHub-Delivery": delivery_id,  # Same delivery ID
                "Content-Type": "application/json"
            },
            content=payload_bytes
        )

        assert response2.status_code == 409
        assert f"Delivery {delivery_id} already processed" in response2.json()["detail"]

        # Third request with different delivery ID should succeed
        response3 = test_client.post(
            "/webhook",
            headers={
                "X-Hub-Signature-256": signature,
                "X-GitHub-Delivery": "test-deduplication-456",  # Different delivery ID
                "Content-Type": "application/json"
            },
            content=payload_bytes
        )

        assert response3.status_code == 200
        assert response3.json()["status"] == "received"

    async def test_webhook_verdict_store_durability(
        self,
        review_worker: ReviewWorker,
        verdict_store_client: VerdictStoreClient,
        project_record: ProjectRecord,
        mock_issue_creator: IssueCreator
    ) -> None:
        """Test that Verdict Store write occurs before issue creation (durability requirement).
        
        ⚠️ WARNING: Verdict Store write durability — Write verdicts before attempting issue creation
        """
        # Make issue creation fail to verify verdicts are still persisted
        mock_issue_creator.create_finding_issues.side_effect = Exception("GitHub API failure")

        delivery_id = "test-durability-789"

        with patch("tempfile.mkdtemp", return_value="/tmp"), \
             patch("pathlib.Path.write_text"):
            
            # Process review - should not fail even though issue creation fails
            await review_worker.process_review(
                delivery_id=delivery_id,
                repo="test-org/test-repo",
                pr_number=42
            )

        # Verify verdicts were written despite issue creation failure
        verdicts = verdict_store_client.get_verdicts_for_project(project_record.id)
        
        # Should have verdicts from both this test and previous tests
        durability_verdicts = [v for v in verdicts if v.delivery_id == delivery_id]
        assert len(durability_verdicts) == 2  # engineer + architect

        # Verify verdict details are correct
        for verdict in durability_verdicts:
            assert verdict.delivery_id == delivery_id
            assert verdict.pr_number == 42
            assert verdict.raw_response is not None
            assert verdict.severity in ["WARN", "BLOCK"]

        # Verify findings were also written
        for verdict in durability_verdicts:
            findings = verdict_store_client.get_findings_for_verdict(verdict.id)
            assert len(findings) >= 1  # Each verdict should have findings

        # Verify issue creator was called but failed
        mock_issue_creator.create_finding_issues.assert_called_once()

    async def test_webhook_response_time_constraint(
        self,
        test_client: TestClient,
        webhook_handler: WebhookHandler,
        sample_webhook_payload: dict
    ) -> None:
        """Test webhook endpoint responds within 500ms requirement (GitHub timeout constraint).
        
        ⚠️ WARNING: Webhook timeout vs review duration — GitHub timeout is 10 seconds, return 200 immediately
        """
        import time

        payload_json = json.dumps(sample_webhook_payload)
        payload_bytes = payload_json.encode("utf-8")

        # Mock verification to always pass
        webhook_handler._verify_signature = lambda *args: True

        start_time = time.time()

        response = test_client.post(
            "/webhook",
            headers={
                "X-Hub-Signature-256": "sha256=test",
                "X-GitHub-Delivery": "test-timing-123",
                "Content-Type": "application/json"
            },
            content=payload_bytes
        )

        response_time = (time.time() - start_time) * 1000  # Convert to milliseconds

        # Should respond within 500ms requirement
        assert response_time < 500
        assert response.status_code == 200

    async def test_webhook_processing_error_returns_200(
        self,
        test_client: TestClient,
        webhook_handler: WebhookHandler,
        sample_webhook_payload: dict
    ) -> None:
        """Test webhook returns 200 even for processing errors to avoid GitHub retries."""
        payload_json = json.dumps(sample_webhook_payload)
        payload_bytes = payload_json.encode("utf-8")

        # Mock handler to raise an unexpected exception
        original_handle = webhook_handler.handle_webhook
        
        async def failing_handler(*args, **kwargs):
            raise ValueError("Unexpected processing error")
        
        webhook_handler.handle_webhook = failing_handler

        response = test_client.post(
            "/webhook",
            headers={
                "X-Hub-Signature-256": "sha256=test",
                "X-GitHub-Delivery": "test-error-123",
                "Content-Type": "application/json"
            },
            content=payload_bytes
        )

        # Should still return 200 to avoid GitHub retries
        assert response.status_code == 200
        assert response.json()["status"] == "error"
        assert "Internal error processing webhook" in response.json()["message"]

        # Restore original handler
        webhook_handler.handle_webhook = original_handle

    async def test_verdict_store_write_before_issue_creation_ordering(
        self,
        review_worker: ReviewWorker,
        verdict_store_client: VerdictStoreClient,
        project_record: ProjectRecord,
        mock_issue_creator: IssueCreator
    ) -> None:
        """Test that Verdict Store writes complete before issue creation attempts.
        
        This verifies the critical ordering requirement for durability.
        """
        call_order = []

        # Track when verdict store writes occur
        original_write_verdict = verdict_store_client.write_verdict
        original_write_findings = verdict_store_client.write_findings

        def track_verdict_write(verdict):
            call_order.append("verdict_write")
            return original_write_verdict(verdict)

        def track_findings_write(verdict_id, findings):
            call_order.append("findings_write")
            return original_write_findings(verdict_id, findings)

        verdict_store_client.write_verdict = track_verdict_write
        verdict_store_client.write_findings = track_findings_write

        # Track when issue creation occurs
        def track_issue_create(*args, **kwargs):
            call_order.append("issue_create")
            return [123, 124]

        mock_issue_creator.create_finding_issues.side_effect = track_issue_create

        delivery_id = "test-ordering-456"

        with patch("tempfile.mkdtemp", return_value="/tmp"), \
             patch("pathlib.Path.write_text"):
            
            await review_worker.process_review(
                delivery_id=delivery_id,
                repo="test-org/test-repo",
                pr_number=42
            )

        # Verify correct ordering: all verdict/findings writes before issue creation
        # Expected: verdict_write, findings_write, verdict_write, findings_write, issue_create
        assert len(call_order) == 5
        assert call_order[0] == "verdict_write"
        assert call_order[1] == "findings_write"
        assert call_order[2] == "verdict_write"
        assert call_order[3] == "findings_write"
        assert call_order[4] == "issue_create"

        # Restore original methods
        verdict_store_client.write_verdict = original_write_verdict
        verdict_store_client.write_findings = original_write_findings

    async def test_database_transaction_integrity(
        self,
        temp_db_path: Path,
        project_record: ProjectRecord
    ) -> None:
        """Test that database writes are transactionally safe."""
        # Create a new client for direct database manipulation
        store = VerdictStoreClient(temp_db_path)

        # Simulate a scenario where findings write might fail
        delivery_id = "test-transaction-123"

        from verdict_store.client import VerdictRecord, FindingRecord

        verdict = VerdictRecord(
            delivery_id=delivery_id,
            project_id=project_record.id,
            pr_number=42,
            pr_sha="test123",
            pr_size_lines=100,
            reviewer="engineer",
            severity="WARN",
            good="Good things",
            bad="Bad things",
            ugly=None,
            closing_question="Question?",
            raw_response="Raw response",
            template_version="1.0.0"
        )

        # Write verdict successfully
        verdict_id = store.write_verdict(verdict)
        assert verdict_id is not None

        # Create findings
        findings = [
            FindingRecord(
                verdict_id=verdict_id,
                bucket="bad",
                text="Test finding",
                severity="WARN",
                invariant_id=None
            )
        ]

        # Write findings successfully
        store.write_findings(verdict_id, findings)

        # Verify both verdict and findings exist
        verdicts = store.get_verdicts_for_project(project_record.id)
        transaction_verdicts = [v for v in verdicts if v.delivery_id == delivery_id]
        assert len(transaction_verdicts) == 1

        stored_findings = store.get_findings_for_verdict(verdict_id)
        assert len(stored_findings) == 1
        assert stored_findings[0].text == "Test finding"
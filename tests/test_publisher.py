"""Tests for notifications.publisher module."""

from unittest.mock import patch

import httpx
import pytest
import respx

from notifications.publisher import NotificationError, NotificationPublisher


@pytest.fixture
def ntfy_base_url() -> str:
    """Test ntfy base URL."""
    return "https://ntfy.example.com"


@pytest.fixture
def publisher(ntfy_base_url: str) -> NotificationPublisher:
    """NotificationPublisher instance for testing."""
    return NotificationPublisher(ntfy_base_url)


class TestNotificationPublisher:
    """Test NotificationPublisher class."""

    def test_init(self, ntfy_base_url: str) -> None:
        """Test NotificationPublisher initialization."""
        publisher = NotificationPublisher(ntfy_base_url)
        assert publisher._base_url == ntfy_base_url
        assert publisher._client.headers["User-Agent"] == "agent-harness/1.0"
        # Timeout object should have been set to 10.0 seconds
        assert str(publisher._client.timeout) == "Timeout(timeout=10.0)"

    def test_init_strips_trailing_slash(self) -> None:
        """Test that trailing slash is stripped from base URL."""
        publisher = NotificationPublisher("https://ntfy.example.com/")
        assert publisher._base_url == "https://ntfy.example.com"

    async def test_context_manager(self, publisher: NotificationPublisher) -> None:
        """Test async context manager protocol."""
        async with publisher as p:
            assert p is publisher
        # Should not raise when exiting context

    @respx.mock
    async def test_publish_review_complete_success(self, publisher: NotificationPublisher) -> None:
        """Test successful review completion notification."""
        topic = "harness-abc123"
        project_name = "test-project"
        pr_number = 42
        highest_severity = "WARN"
        finding_count = 3

        mock_request = respx.post(f"{publisher._base_url}/{topic}").mock(
            return_value=httpx.Response(200)
        )

        async with publisher:
            await publisher.publish_review_complete(
                topic=topic,
                project_name=project_name,
                pr_number=pr_number,
                highest_severity=highest_severity,
                finding_count=finding_count,
            )

        assert mock_request.called
        request = mock_request.calls[0].request
        
        # Verify request body
        assert b"Review found 3 warnings" in request.content

        # Verify headers
        assert request.headers["Title"] == "WARNINGS: test-project PR#42"
        assert request.headers["Priority"] == "3"
        assert request.headers["Tags"] == "agent-harness,review"

    @respx.mock
    async def test_publish_review_complete_block_priority(
        self, publisher: NotificationPublisher
    ) -> None:
        """Test BLOCK severity gets maximum priority."""
        topic = "harness-def456"
        
        mock_request = respx.post(f"{publisher._base_url}/{topic}").mock(
            return_value=httpx.Response(200)
        )

        async with publisher:
            await publisher.publish_review_complete(
                topic=topic,
                project_name="critical-app",
                pr_number=1,
                highest_severity="BLOCK",
                finding_count=2,
            )

        request = mock_request.calls[0].request
        assert request.headers["Title"] == "BLOCKED: critical-app PR#1"
        assert request.headers["Priority"] == "5"
        assert b"Review found 2 issues including blockers" in request.content

    @respx.mock
    async def test_publish_review_complete_block_single_finding(
        self, publisher: NotificationPublisher
    ) -> None:
        """Test BLOCK severity with single finding uses singular message."""
        topic = "harness-def456"
        
        mock_request = respx.post(f"{publisher._base_url}/{topic}").mock(
            return_value=httpx.Response(200)
        )

        async with publisher:
            await publisher.publish_review_complete(
                topic=topic,
                project_name="critical-app", 
                pr_number=1,
                highest_severity="BLOCK",
                finding_count=1,
            )

        request = mock_request.calls[0].request
        assert b"Review found 1 blocking issue" in request.content

    @respx.mock
    async def test_publish_review_complete_warn_priority(
        self, publisher: NotificationPublisher
    ) -> None:
        """Test WARN severity gets normal priority."""
        topic = "harness-ghi789"
        
        mock_request = respx.post(f"{publisher._base_url}/{topic}").mock(
            return_value=httpx.Response(200)
        )

        async with publisher:
            await publisher.publish_review_complete(
                topic=topic,
                project_name="webapp",
                pr_number=99,
                highest_severity="WARN",
                finding_count=1,
            )

        request = mock_request.calls[0].request
        assert request.headers["Title"] == "WARNINGS: webapp PR#99"
        assert request.headers["Priority"] == "3"
        assert b"Review found 1 warning" in request.content

    @respx.mock
    async def test_publish_review_complete_pass_priority(
        self, publisher: NotificationPublisher
    ) -> None:
        """Test PASS severity gets low priority."""
        topic = "harness-jkl012"
        
        mock_request = respx.post(f"{publisher._base_url}/{topic}").mock(
            return_value=httpx.Response(200)
        )

        async with publisher:
            await publisher.publish_review_complete(
                topic=topic,
                project_name="library",
                pr_number=5,
                highest_severity="PASS",
                finding_count=0,
            )

        request = mock_request.calls[0].request
        assert request.headers["Title"] == "CLEAN: library PR#5"
        assert request.headers["Priority"] == "1"
        assert b"Review completed with no issues" in request.content

    @respx.mock
    async def test_publish_review_complete_pass_with_minor_notes(
        self, publisher: NotificationPublisher
    ) -> None:
        """Test PASS severity with minor notes."""
        topic = "harness-mno345"
        
        mock_request = respx.post(f"{publisher._base_url}/{topic}").mock(
            return_value=httpx.Response(200)
        )

        async with publisher:
            await publisher.publish_review_complete(
                topic=topic,
                project_name="library",
                pr_number=5,
                highest_severity="PASS",
                finding_count=2,
            )

        request = mock_request.calls[0].request
        assert b"Review completed with 2 minor notes" in request.content

    @respx.mock
    async def test_publish_review_complete_unknown_severity(
        self, publisher: NotificationPublisher
    ) -> None:
        """Test unknown severity defaults to low priority."""
        topic = "harness-pqr678"
        
        mock_request = respx.post(f"{publisher._base_url}/{topic}").mock(
            return_value=httpx.Response(200)
        )

        async with publisher:
            await publisher.publish_review_complete(
                topic=topic,
                project_name="test-app",
                pr_number=10,
                highest_severity="UNKNOWN",
                finding_count=1,
            )

        request = mock_request.calls[0].request
        assert request.headers["Priority"] == "1"

    @respx.mock
    async def test_publish_review_complete_network_error(
        self, publisher: NotificationPublisher
    ) -> None:
        """Test network error raises NotificationError."""
        topic = "harness-error"
        
        respx.post(f"{publisher._base_url}/{topic}").mock(
            side_effect=httpx.ConnectError("Connection failed")
        )

        async with publisher:
            with pytest.raises(NotificationError) as exc_info:
                await publisher.publish_review_complete(
                    topic=topic,
                    project_name="test-app",
                    pr_number=1,
                    highest_severity="WARN",
                    finding_count=1,
                )

        assert "Failed to publish notification to topic 'harness-error'" in str(exc_info.value)
        assert exc_info.value.__cause__.__class__ == httpx.ConnectError

    @respx.mock
    async def test_publish_review_complete_http_error(
        self, publisher: NotificationPublisher
    ) -> None:
        """Test HTTP error raises NotificationError."""
        topic = "harness-http-error"
        
        respx.post(f"{publisher._base_url}/{topic}").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        async with publisher:
            with pytest.raises(NotificationError) as exc_info:
                await publisher.publish_review_complete(
                    topic=topic,
                    project_name="test-app", 
                    pr_number=1,
                    highest_severity="WARN",
                    finding_count=1,
                )

        assert "Failed to publish notification to topic 'harness-http-error'" in str(exc_info.value)
        assert exc_info.value.__cause__.__class__ == httpx.HTTPStatusError
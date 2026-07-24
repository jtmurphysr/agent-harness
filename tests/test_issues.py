"""Tests for github/issues.py - GitHub issue creation functionality."""

import pytest
import respx
import httpx
from unittest.mock import AsyncMock

from github.issues import IssueCreator, IssueCreationError
from reviewers.verdicts import Finding


@pytest.fixture
def sample_findings() -> list[Finding]:
    """Create sample findings with different severities and invariant citations."""
    return [
        Finding(
            bucket="bad",
            text="Function `calculate_total` has no input validation (invariant: input_validation)",
            severity="WARN",
            invariant_id="input_validation",
        ),
        Finding(
            bucket="ugly",
            text="Database query bypasses soft-delete filter, potential data leak",
            severity="BLOCK",
            invariant_id=None,
        ),
        Finding(
            bucket="bad",
            text="Missing error handling in payment processing flow",
            severity="WARN", 
            invariant_id=None,
        ),
        Finding(
            bucket="bad",
            text="Minor formatting inconsistency in CSS",
            severity="WARN",
            invariant_id=None,
        ),
    ]


@pytest.fixture
def issue_creator() -> IssueCreator:
    """Create IssueCreator instance with test token."""
    return IssueCreator(github_token="test-token")


class TestIssueCreator:
    """Test cases for IssueCreator class."""

    def test_init(self) -> None:
        """Test IssueCreator initialization."""
        creator = IssueCreator("test-token")
        assert creator._token == "test-token"
        assert creator._client is not None

    async def test_async_context_manager(self) -> None:
        """Test async context manager protocol."""
        async with IssueCreator("test-token") as creator:
            assert creator is not None
            assert creator._client is not None

    async def test_close(self) -> None:
        """Test explicit close method."""
        creator = IssueCreator("test-token")
        await creator.close()
        # Verify client is closed - no exception should be raised


class TestCreateFindingIssues:
    """Test cases for create_finding_issues method."""

    @respx.mock
    async def test_create_finding_issues_above_threshold(
        self, issue_creator: IssueCreator, sample_findings: list[Finding]
    ) -> None:
        """Test creating issues for findings above WARN threshold."""
        # Mock successful GitHub API responses
        respx.post("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "number": 123,
                    "html_url": "https://github.com/test/repo/issues/123",
                },
            )
        )

        async with issue_creator:
            issue_numbers = await issue_creator.create_finding_issues(
                repo="test/repo",
                findings=sample_findings,
                pr_number=42,
                pr_sha="abc123def456",
                severity_threshold="WARN",
            )

        # Should create issues for all findings (all are WARN or BLOCK)
        assert len(issue_numbers) == 4
        assert all(num == 123 for num in issue_numbers)

    @respx.mock
    async def test_create_finding_issues_block_threshold(
        self, issue_creator: IssueCreator, sample_findings: list[Finding]
    ) -> None:
        """Test creating issues only for BLOCK severity findings."""
        respx.post("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "number": 124,
                    "html_url": "https://github.com/test/repo/issues/124",
                },
            )
        )

        async with issue_creator:
            issue_numbers = await issue_creator.create_finding_issues(
                repo="test/repo",
                findings=sample_findings,
                pr_number=42,
                pr_sha="abc123def456",
                severity_threshold="BLOCK",
            )

        # Should create issue only for the one BLOCK severity finding
        assert len(issue_numbers) == 1
        assert issue_numbers[0] == 124

    async def test_create_finding_issues_below_threshold_skipped(
        self, issue_creator: IssueCreator
    ) -> None:
        """Test that findings below threshold are skipped."""
        # Create findings that are below BLOCK threshold
        warn_findings = [
            Finding(
                bucket="bad",
                text="Minor issue",
                severity="WARN",
                invariant_id=None,
            )
        ]

        async with issue_creator:
            issue_numbers = await issue_creator.create_finding_issues(
                repo="test/repo",
                findings=warn_findings,
                pr_number=42,
                pr_sha="abc123def456",
                severity_threshold="BLOCK",
            )

        # No issues should be created for WARN findings with BLOCK threshold
        assert len(issue_numbers) == 0

    async def test_create_finding_issues_empty_findings(self, issue_creator: IssueCreator) -> None:
        """Test handling of empty findings list."""
        async with issue_creator:
            issue_numbers = await issue_creator.create_finding_issues(
                repo="test/repo",
                findings=[],
                pr_number=42,
                pr_sha="abc123def456",
                severity_threshold="WARN",
            )

        assert len(issue_numbers) == 0

    @respx.mock
    async def test_create_finding_issues_with_invariant_links(
        self, issue_creator: IssueCreator
    ) -> None:
        """Test that issues include invariant references when present."""
        finding_with_invariant = Finding(
            bucket="bad",
            text="Validation bypassed (invariant: input_validation)",
            severity="WARN",
            invariant_id="input_validation",
        )

        # Track the request to verify issue body content
        respx.post("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "number": 125,
                    "html_url": "https://github.com/test/repo/issues/125",
                },
            )
        )

        async with issue_creator:
            issue_numbers = await issue_creator.create_finding_issues(
                repo="test/repo",
                findings=[finding_with_invariant],
                pr_number=42,
                pr_sha="abc123def456",
                severity_threshold="WARN",
            )

        assert len(issue_numbers) == 1

        # Verify the request was made with proper content
        request = respx.calls.last.request
        request_data = request.content
        assert b"input_validation" in request_data

    @respx.mock
    async def test_create_finding_issues_includes_pr_context(
        self, issue_creator: IssueCreator
    ) -> None:
        """Test that issues include PR and commit context."""
        finding = Finding(
            bucket="bad",
            text="Test finding",
            severity="WARN",
            invariant_id=None,
        )

        respx.post("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                201,
                json={
                    "number": 126,
                    "html_url": "https://github.com/test/repo/issues/126",
                },
            )
        )

        async with issue_creator:
            await issue_creator.create_finding_issues(
                repo="test/repo",
                findings=[finding],
                pr_number=42,
                pr_sha="abc123def456789",
                severity_threshold="WARN",
            )

        # Verify PR context is included in request
        request = respx.calls.last.request
        request_data = request.content
        assert b"#42" in request_data
        assert b"abc123def456789" in request_data
        assert b"https://github.com/test/repo/pull/42" in request_data
        assert b"https://github.com/test/repo/commit/abc123def456789" in request_data

    @respx.mock
    async def test_create_finding_issues_github_api_error(
        self, issue_creator: IssueCreator, sample_findings: list[Finding]
    ) -> None:
        """Test handling of GitHub API errors."""
        # Mock API error response
        respx.post("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                403,
                text="Forbidden - insufficient permissions",
            )
        )

        with pytest.raises(IssueCreationError, match="Access forbidden"):
            async with issue_creator:
                await issue_creator.create_finding_issues(
                    repo="test/repo",
                    findings=sample_findings[:1],  # Just test with one finding
                    pr_number=42,
                    pr_sha="abc123def456",
                    severity_threshold="WARN",
                )

    @respx.mock
    async def test_create_finding_issues_not_found_error(
        self, issue_creator: IssueCreator, sample_findings: list[Finding]
    ) -> None:
        """Test handling of repository not found error."""
        respx.post("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                404,
                text="Not Found",
            )
        )

        with pytest.raises(IssueCreationError, match="Repository not found"):
            async with issue_creator:
                await issue_creator.create_finding_issues(
                    repo="test/repo",
                    findings=sample_findings[:1],
                    pr_number=42,
                    pr_sha="abc123def456",
                    severity_threshold="WARN",
                )

    @respx.mock
    async def test_create_finding_issues_validation_error(
        self, issue_creator: IssueCreator, sample_findings: list[Finding]
    ) -> None:
        """Test handling of GitHub validation errors."""
        respx.post("https://api.github.com/repos/test/repo/issues").mock(
            return_value=httpx.Response(
                422,
                text="Unprocessable Entity - validation failed",
            )
        )

        with pytest.raises(IssueCreationError, match="Invalid issue data"):
            async with issue_creator:
                await issue_creator.create_finding_issues(
                    repo="test/repo",
                    findings=sample_findings[:1],
                    pr_number=42,
                    pr_sha="abc123def456",
                    severity_threshold="WARN",
                )

    @respx.mock
    async def test_create_finding_issues_network_error(
        self, issue_creator: IssueCreator, sample_findings: list[Finding]
    ) -> None:
        """Test handling of network errors."""
        respx.post("https://api.github.com/repos/test/repo/issues").mock(
            side_effect=httpx.RequestError("Network error")
        )

        with pytest.raises(IssueCreationError, match="GitHub API request failed"):
            async with issue_creator:
                await issue_creator.create_finding_issues(
                    repo="test/repo",
                    findings=sample_findings[:1],
                    pr_number=42,
                    pr_sha="abc123def456",
                    severity_threshold="WARN",
                )


class TestFilterFindingsBySeverity:
    """Test cases for _filter_findings_by_severity method."""

    def test_filter_warn_threshold(self, issue_creator: IssueCreator) -> None:
        """Test filtering with WARN threshold includes WARN and BLOCK."""
        findings = [
            Finding(bucket="bad", text="warn1", severity="WARN", invariant_id=None),
            Finding(bucket="ugly", text="block1", severity="BLOCK", invariant_id=None),
        ]

        filtered = issue_creator._filter_findings_by_severity(findings, "WARN")
        assert len(filtered) == 2

    def test_filter_block_threshold(self, issue_creator: IssueCreator) -> None:
        """Test filtering with BLOCK threshold includes only BLOCK."""
        findings = [
            Finding(bucket="bad", text="warn1", severity="WARN", invariant_id=None),
            Finding(bucket="ugly", text="block1", severity="BLOCK", invariant_id=None),
        ]

        filtered = issue_creator._filter_findings_by_severity(findings, "BLOCK")
        assert len(filtered) == 1
        assert filtered[0].severity == "BLOCK"

    def test_filter_unknown_threshold(self, issue_creator: IssueCreator) -> None:
        """Test filtering with unknown threshold includes all findings."""
        findings = [
            Finding(bucket="bad", text="warn1", severity="WARN", invariant_id=None),
            Finding(bucket="ugly", text="block1", severity="BLOCK", invariant_id=None),
        ]

        filtered = issue_creator._filter_findings_by_severity(findings, "UNKNOWN")
        assert len(filtered) == 2


class TestIssueTitleGeneration:
    """Test cases for _generate_issue_title method."""

    def test_generate_issue_title_basic(self, issue_creator: IssueCreator) -> None:
        """Test basic issue title generation."""
        finding = Finding(
            bucket="bad",
            text="Function has no input validation",
            severity="WARN",
            invariant_id=None,
        )

        title = issue_creator._generate_issue_title(finding)
        assert title == "[WARN/BAD] Function has no input validation"

    def test_generate_issue_title_long_text(self, issue_creator: IssueCreator) -> None:
        """Test title generation with long text gets truncated."""
        long_text = "This is a very long finding text that exceeds the maximum title length and should be truncated to fit within reasonable bounds for GitHub issue titles"
        
        finding = Finding(
            bucket="ugly",
            text=long_text,
            severity="BLOCK",
            invariant_id=None,
        )

        title = issue_creator._generate_issue_title(finding)
        assert len(title) <= 100  # Prefix + max length + buffer
        assert title.endswith("...")
        assert title.startswith("[BLOCK/UGLY]")

    def test_generate_issue_title_with_sentence(self, issue_creator: IssueCreator) -> None:
        """Test title generation uses first sentence if reasonable length."""
        finding = Finding(
            bucket="bad",
            text="Input validation missing. This causes security issues.",
            severity="WARN",
            invariant_id=None,
        )

        title = issue_creator._generate_issue_title(finding)
        assert title == "[WARN/BAD] Input validation missing."

    def test_generate_issue_title_removes_prefixes(self, issue_creator: IssueCreator) -> None:
        """Test title generation removes bullet point prefixes."""
        finding = Finding(
            bucket="bad",
            text="- Function has no input validation",
            severity="WARN",
            invariant_id=None,
        )

        title = issue_creator._generate_issue_title(finding)
        assert title == "[WARN/BAD] Function has no input validation"


class TestIssueBodyGeneration:
    """Test cases for _generate_issue_body method."""

    def test_generate_issue_body_basic(self, issue_creator: IssueCreator) -> None:
        """Test basic issue body generation."""
        finding = Finding(
            bucket="bad",
            text="Function has no input validation",
            severity="WARN",
            invariant_id=None,
        )

        body = issue_creator._generate_issue_body(finding, 42, "abc123", "test/repo")
        
        assert "## Finding Details" in body
        assert "**Severity:** WARN" in body
        assert "**Source Bucket:** bad" in body
        assert "Function has no input validation" in body
        assert "## Source Context" in body
        assert "**Source PR:** #42" in body
        assert "**Commit SHA:** `abc123`" in body
        assert "https://github.com/test/repo/pull/42" in body
        assert "https://github.com/test/repo/commit/abc123" in body
        assert "Triumvirate Review Subsystem" in body

    def test_generate_issue_body_with_invariant(self, issue_creator: IssueCreator) -> None:
        """Test issue body generation includes invariant reference."""
        finding = Finding(
            bucket="bad",
            text="Validation bypassed (invariant: input_validation)",
            severity="WARN",
            invariant_id="input_validation",
        )

        body = issue_creator._generate_issue_body(finding, 42, "abc123", "test/repo")
        
        assert "## Invariant Reference" in body
        assert "input_validation" in body

    def test_generate_issue_body_no_invariant(self, issue_creator: IssueCreator) -> None:
        """Test issue body generation without invariant reference."""
        finding = Finding(
            bucket="bad",
            text="Simple finding",
            severity="WARN",
            invariant_id=None,
        )

        body = issue_creator._generate_issue_body(finding, 42, "abc123", "test/repo")
        
        assert "## Invariant Reference" not in body
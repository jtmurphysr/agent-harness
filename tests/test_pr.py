"""Tests for github.pr module."""

import base64
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from github.pr import PRClient, PRDiff, PRError


@pytest.fixture
def github_token() -> str:
    """Test GitHub token."""
    return "test_token_12345"


@pytest.fixture
def pr_client(github_token: str) -> PRClient:
    """PRClient instance for testing."""
    return PRClient(github_token)


@pytest.fixture
def mock_pr_data() -> dict:
    """Mock PR metadata response."""
    return {
        "number": 42,
        "head": {"sha": "abc123def456"},
        "title": "Test PR",
        "body": "Test PR body",
    }


@pytest.fixture
def mock_diff_content() -> str:
    """Mock diff content."""
    return """diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,5 +1,6 @@
 def main():
     print("Hello World")
+    print("Added line")
 
 if __name__ == "__main__":
     main()
diff --git a/src/utils.py b/src/utils.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/src/utils.py
@@ -0,0 +1,3 @@
+def helper():
+    return "helper"
+"""


@pytest.fixture
def mock_file_content() -> str:
    """Mock file content."""
    return """def main():
    print("Hello World")
    
if __name__ == "__main__":
    main()
"""


class TestPRClient:
    """Test PRClient class."""

    def test_init(self, github_token: str) -> None:
        """Test PRClient initialization."""
        client = PRClient(github_token)
        assert client._token == github_token
        assert client._client.headers["Authorization"] == f"Bearer {github_token}"
        assert client._client.headers["Accept"] == "application/vnd.github.v3+json"
        assert client._client.headers["User-Agent"] == "agent-harness/1.0"

    async def test_context_manager(self, pr_client: PRClient) -> None:
        """Test async context manager protocol."""
        async with pr_client as client:
            assert client is pr_client
        # Should not raise when exiting context

    async def test_get_pr_diff_success(
        self, pr_client: PRClient, mock_pr_data: dict, mock_diff_content: str
    ) -> None:
        """Test successful PR diff retrieval."""
        # Mock the client request method directly
        with patch.object(
            pr_client._client,
            "request",
            side_effect=[
                httpx.Response(200, json=mock_pr_data),
                httpx.Response(200, text=mock_diff_content),
            ]
        ):
            result = await pr_client.get_pr_diff("owner/repo", 42)

            assert isinstance(result, PRDiff)
            assert result.pr_number == 42
            assert result.pr_sha == "abc123def456"
            assert result.pr_size_lines == 4  # 1 addition in main.py + 3 additions in utils.py
            assert result.diff_content == mock_diff_content
            assert result.changed_files == ["src/main.py", "src/utils.py"]

    @respx.mock
    async def test_get_pr_diff_not_found(self, pr_client: PRClient) -> None:
        """Test PR diff retrieval when PR not found."""
        repo = "owner/repo"
        pr_number = 999

        # Mock 404 response
        respx.get(f"https://api.github.com/repos/{repo}/pulls/{pr_number}").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        with pytest.raises(PRError, match="Resource not found"):
            await pr_client.get_pr_diff(repo, pr_number)

    async def test_get_pr_diff_rate_limited(self, pr_client: PRClient) -> None:
        """Test PR diff retrieval with rate limiting."""
        # Use patch to mock the internal client behavior
        with patch.object(
            pr_client._client,
            "request",
            side_effect=[
                httpx.Response(403, text="rate limit exceeded"),
                httpx.Response(200, json={"number": 42, "head": {"sha": "abc123"}}),
                httpx.Response(200, text="mock diff"),
            ],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await pr_client.get_pr_diff("owner/repo", 42)
                assert result.pr_number == 42
                mock_sleep.assert_called_once()

    @respx.mock
    async def test_get_file_content_success(
        self, pr_client: PRClient, mock_file_content: str
    ) -> None:
        """Test successful file content retrieval."""
        repo = "owner/repo"
        path = "src/main.py"
        ref = "main"

        encoded_content = base64.b64encode(mock_file_content.encode()).decode()
        mock_response = {
            "type": "file",
            "encoding": "base64",
            "content": encoded_content,
        }

        respx.get(f"https://api.github.com/repos/{repo}/contents/{path}").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        result = await pr_client.get_file_content(repo, path, ref)
        assert result == mock_file_content

    @respx.mock
    async def test_get_file_content_not_found(self, pr_client: PRClient) -> None:
        """Test file content retrieval when file not found."""
        repo = "owner/repo"
        path = "nonexistent.py"
        ref = "main"

        respx.get(f"https://api.github.com/repos/{repo}/contents/{path}").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        with pytest.raises(PRError, match="Resource not found"):
            await pr_client.get_file_content(repo, path, ref)

    @respx.mock
    async def test_get_file_content_not_file(self, pr_client: PRClient) -> None:
        """Test file content retrieval when path is not a file."""
        repo = "owner/repo"
        path = "src"
        ref = "main"

        mock_response = {
            "type": "dir",
            "encoding": None,
            "content": None,
        }

        respx.get(f"https://api.github.com/repos/{repo}/contents/{path}").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        with pytest.raises(PRError, match="Path src is not a file"):
            await pr_client.get_file_content(repo, path, ref)


class TestPRDiff:
    """Test PRDiff data model."""

    def test_pr_diff_creation(self) -> None:
        """Test PRDiff model creation."""
        diff = PRDiff(
            pr_number=42,
            pr_sha="abc123",
            pr_size_lines=10,
            diff_content="mock diff",
            changed_files=["file1.py", "file2.py"],
        )

        assert diff.pr_number == 42
        assert diff.pr_sha == "abc123"
        assert diff.pr_size_lines == 10
        assert diff.diff_content == "mock diff"
        assert diff.changed_files == ["file1.py", "file2.py"]


class TestPRError:
    """Test PRError exception."""

    def test_pr_error_creation(self) -> None:
        """Test PRError exception creation."""
        error = PRError("Test error message")
        assert str(error) == "Test error message"
        assert isinstance(error, Exception)


class TestDiffParsing:
    """Test diff parsing helper methods."""

    def test_extract_changed_files(self, pr_client: PRClient) -> None:
        """Test extraction of changed files from diff."""
        diff_content = """diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
 line 1
+added line
 line 3
diff --git a/src/utils.py b/src/utils.py
new file mode 100644"""

        files = pr_client._extract_changed_files(diff_content)
        assert files == ["src/main.py", "src/utils.py"]

    def test_extract_changed_files_empty(self, pr_client: PRClient) -> None:
        """Test extraction with empty diff."""
        files = pr_client._extract_changed_files("")
        assert files == []

    def test_count_diff_lines(self, pr_client: PRClient) -> None:
        """Test counting of diff lines."""
        diff_content = """diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
 line 1
-removed line
+added line
 line 3"""

        count = pr_client._count_diff_lines(diff_content)
        assert count == 2  # 1 addition + 1 deletion

    def test_count_diff_lines_empty(self, pr_client: PRClient) -> None:
        """Test counting with empty diff."""
        count = pr_client._count_diff_lines("")
        assert count == 0

    def test_count_diff_lines_ignores_headers(self, pr_client: PRClient) -> None:
        """Test that line counting ignores diff headers."""
        diff_content = """diff --git a/file.py b/file.py
index 1234567..abcdefg 100644
--- a/file.py
+++ b/file.py
@@ -1,2 +1,2 @@
-old line
+new line"""

        count = pr_client._count_diff_lines(diff_content)
        assert count == 2  # Should not count --- and +++ header lines


class TestRetryLogic:
    """Test retry and error handling logic."""

    async def test_server_error_retry(self, pr_client: PRClient) -> None:
        """Test retry logic for server errors."""
        # Use patch to mock the internal client behavior
        with patch.object(
            pr_client._client,
            "request",
            side_effect=[
                httpx.Response(500, text="Internal Server Error"),
                httpx.Response(200, json={"number": 42, "head": {"sha": "abc123"}}),
                httpx.Response(200, text="mock diff"),
            ],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await pr_client.get_pr_diff("owner/repo", 42)
                assert result.pr_number == 42
                mock_sleep.assert_called_once()

    @respx.mock
    async def test_max_retries_exceeded(self, pr_client: PRClient) -> None:
        """Test max retries exceeded."""
        repo = "owner/repo"
        pr_number = 42

        # Mock persistent server error
        respx.get(f"https://api.github.com/repos/{repo}/pulls/{pr_number}").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(PRError, match="GitHub API server error: 500"):
                await pr_client.get_pr_diff(repo, pr_number)

    @respx.mock
    async def test_forbidden_not_rate_limit(self, pr_client: PRClient) -> None:
        """Test 403 forbidden that's not a rate limit."""
        repo = "owner/repo"
        pr_number = 42

        respx.get(f"https://api.github.com/repos/{repo}/pulls/{pr_number}").mock(
            return_value=httpx.Response(403, text="Access denied")
        )

        with pytest.raises(PRError, match="Access forbidden"):
            await pr_client.get_pr_diff(repo, pr_number)

    async def test_request_error_retry(self, pr_client: PRClient) -> None:
        """Test retry logic for request errors."""
        repo = "owner/repo"
        pr_number = 42

        with patch.object(
            pr_client._client,
            "request",
            side_effect=[
                httpx.RequestError("Connection failed"),
                httpx.Response(200, json={"number": 42, "head": {"sha": "abc123"}}),
                httpx.Response(200, text="mock diff"),
            ],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await pr_client.get_pr_diff(repo, pr_number)
                assert result.pr_number == 42
                mock_sleep.assert_called_once()
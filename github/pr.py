"""GitHub pull request diff retrieval."""

import asyncio
import re
from typing import Any

import httpx
from pydantic import BaseModel

__all__ = ["PRClient", "PRDiff", "PRError"]


class PRError(Exception):
    """Raised when PR retrieval fails."""

    pass


class PRDiff(BaseModel):
    """GitHub pull request diff data."""

    pr_number: int
    pr_sha: str
    pr_size_lines: int
    diff_content: str
    changed_files: list[str]


class PRClient:
    """GitHub API client for pull request operations."""

    def __init__(self, github_token: str) -> None:
        """Initialize GitHub client with authentication token."""
        self._token = github_token
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "agent-harness/1.0",
            },
            timeout=30.0,
        )

    async def __aenter__(self) -> "PRClient":
        """Async context manager entry."""
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def _request_with_retry(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Make HTTP request with exponential backoff retry for rate limits."""
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries + 1):
            try:
                response = await self._client.request(method, url, **kwargs)

                if response.status_code == 200:
                    return response
                elif response.status_code == 404:
                    raise PRError(f"Resource not found: {url}")
                elif response.status_code == 403:
                    # Check if it's a rate limit
                    if "rate limit" in response.text.lower():
                        if attempt < max_retries:
                            delay = base_delay * (2**attempt)
                            await asyncio.sleep(delay)
                            continue
                        else:
                            raise PRError("GitHub API rate limit exceeded")
                    else:
                        raise PRError(f"Access forbidden: {response.text}")
                elif response.status_code >= 500:
                    if attempt < max_retries:
                        delay = base_delay * (2**attempt)
                        await asyncio.sleep(delay)
                        continue
                    else:
                        raise PRError(f"GitHub API server error: {response.status_code}")
                else:
                    raise PRError(f"GitHub API error: {response.status_code} - {response.text}")

            except httpx.RequestError as e:
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                else:
                    raise PRError(f"GitHub API request failed: {e!s}") from e

        raise PRError("Max retries exceeded")

    async def get_pr_diff(self, repo: str, pr_number: int) -> PRDiff:
        """Retrieve PR diff content and metadata.

        Args:
            repo: Repository in format "owner/name"
            pr_number: Pull request number

        Returns:
            PRDiff object with diff content and metadata

        Raises:
            PRError: If PR retrieval fails
        """
        # First get PR metadata
        pr_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        pr_response = await self._request_with_retry("GET", pr_url)
        pr_data = pr_response.json()

        pr_sha = pr_data["head"]["sha"]

        # Get the diff content
        diff_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        diff_response = await self._request_with_retry(
            "GET", diff_url, headers={"Accept": "application/vnd.github.v3.diff"}
        )
        diff_content = diff_response.text

        # Parse diff to extract metadata
        changed_files = self._extract_changed_files(diff_content)
        pr_size_lines = self._count_diff_lines(diff_content)

        return PRDiff(
            pr_number=pr_number,
            pr_sha=pr_sha,
            pr_size_lines=pr_size_lines,
            diff_content=diff_content,
            changed_files=changed_files,
        )

    async def get_file_content(self, repo: str, path: str, ref: str) -> str:
        """Retrieve file content from repository.

        Args:
            repo: Repository in format "owner/name"
            path: File path within repository
            ref: Git reference (branch, tag, or SHA)

        Returns:
            File content as string

        Raises:
            PRError: If file retrieval fails
        """
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        response = await self._request_with_retry("GET", url, params={"ref": ref})

        data = response.json()

        if data.get("type") != "file":
            raise PRError(f"Path {path} is not a file")

        if data.get("encoding") == "base64":
            import base64

            content_str = str(data["content"])
            content = base64.b64decode(content_str).decode("utf-8")
            return content
        else:
            # Fallback to raw content if not base64 encoded
            return str(data.get("content", ""))

    def _extract_changed_files(self, diff_content: str) -> list[str]:
        """Extract list of changed files from diff content."""
        files = []
        lines = diff_content.split("\n")

        for line in lines:
            if line.startswith("diff --git a/"):
                # Extract filename from diff header: "diff --git a/path b/path"
                match = re.match(r"diff --git a/(.+?) b/", line)
                if match:
                    files.append(match.group(1))

        return files

    def _count_diff_lines(self, diff_content: str) -> int:
        """Count number of changed lines in diff (additions + deletions)."""
        lines = diff_content.split("\n")
        count = 0

        for line in lines:
            if (line.startswith("+") and not line.startswith("+++")) or (
                line.startswith("-") and not line.startswith("---")
            ):
                count += 1

        return count

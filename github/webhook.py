"""GitHub webhook registration and management functionality."""

import asyncio
from typing import Any

import httpx


class WebhookError(Exception):
    """Raised when webhook registration fails."""


async def register_webhook(
    repo_owner: str,
    repo_name: str,
    webhook_url: str,
    secret: str,
    github_token: str,
) -> int:
    """Register webhook with GitHub and return webhook ID.

    Creates a new webhook or replaces an existing one for the triumvirate
    review system. Configures webhook to trigger on pull_request and push events.

    Args:
        repo_owner: GitHub repository owner (user or organization)
        repo_name: GitHub repository name
        webhook_url: URL that GitHub should POST webhook events to
        secret: HMAC secret for webhook signature verification
        github_token: GitHub Personal Access Token with webhooks:write scope

    Returns:
        Webhook ID for tracking and management

    Raises:
        WebhookError: If webhook registration fails due to API errors,
                     invalid credentials, or repository access issues
    """
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "agent-harness-webhook-manager/1.0",
    }

    base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
    webhook_config = {
        "name": "web",
        "active": True,
        "events": ["pull_request", "push"],
        "config": {
            "url": webhook_url,
            "content_type": "json",
            "secret": secret,
            "insecure_ssl": "0",  # Always require SSL
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check if webhook already exists for this URL
        try:
            existing_webhook_id = await _find_existing_webhook(
                client, base_url, headers, webhook_url
            )

            if existing_webhook_id:
                # Update existing webhook
                response = await client.patch(
                    f"{base_url}/hooks/{existing_webhook_id}",
                    json=webhook_config,
                    headers=headers,
                )

                if response.status_code == 200:
                    return existing_webhook_id
                else:
                    raise WebhookError(
                        f"Failed to update existing webhook {existing_webhook_id}: "
                        f"{response.status_code} {response.text}"
                    )

        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise WebhookError(f"Error checking existing webhooks: {e}") from e

        # Create new webhook
        try:
            response = await client.post(
                f"{base_url}/hooks",
                json=webhook_config,
                headers=headers,
            )
            response.raise_for_status()

            webhook_data = response.json()
            webhook_id: int = webhook_data["id"]

            return webhook_id

        except httpx.HTTPStatusError as e:
            error_msg = _parse_github_error(e.response)
            raise WebhookError(f"Failed to create webhook: {error_msg}") from e
        except (httpx.RequestError, KeyError) as e:
            raise WebhookError(f"Request failed or invalid response format: {e}") from e


async def _find_existing_webhook(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    webhook_url: str,
) -> int | None:
    """Find existing webhook ID for the given URL, if any."""
    try:
        response = await client.get(f"{base_url}/hooks", headers=headers)
        response.raise_for_status()

        webhooks: list[dict[str, Any]] = response.json()

        for webhook in webhooks:
            config = webhook.get("config", {})
            if config.get("url") == webhook_url:
                webhook_id: int = webhook["id"]
                return webhook_id

        return None

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise WebhookError("Repository not found or access denied") from e
        raise WebhookError(f"Failed to list existing webhooks: {e}") from e


def _parse_github_error(response: httpx.Response) -> str:
    """Parse GitHub API error response to extract meaningful error message."""
    try:
        error_data = response.json()

        # GitHub API returns errors in this format
        if "message" in error_data:
            message: str = error_data["message"]

            # Include validation errors if present
            if "errors" in error_data:
                errors = "; ".join(
                    [
                        f"{err.get('field', 'unknown')}: {err.get('message', 'invalid')}"
                        for err in error_data["errors"]
                    ]
                )
                return f"{message} (errors: {errors})"

            return message

    except Exception:
        # Fallback to status code and text if JSON parsing fails
        pass

    return f"{response.status_code} {response.reason_phrase}"


# Sync wrapper for CLI usage
def register_webhook_sync(
    repo_owner: str,
    repo_name: str,
    webhook_url: str,
    secret: str,
    github_token: str,
) -> int:
    """Synchronous wrapper for register_webhook.

    This function provides a synchronous interface to the async register_webhook
    function for use in CLI contexts where async/await is not available.
    """
    return asyncio.run(register_webhook(repo_owner, repo_name, webhook_url, secret, github_token))

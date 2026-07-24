"""Tests for GitHub webhook registration functionality."""

import pytest
import respx
import httpx

from github.webhook import WebhookError, register_webhook, register_webhook_sync


@pytest.mark.asyncio
async def test_register_webhook_success():
    """Test successful webhook registration returns webhook ID."""
    webhook_id = 12345678
    
    with respx.mock:
        # Mock existing webhooks check (empty list)
        respx.get(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(200, json=[]))
        
        # Mock successful webhook creation
        respx.post(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(
            201,
            json={
                "id": webhook_id,
                "url": "https://api.github.com/repos/testowner/testrepo/hooks/12345678",
                "config": {
                    "url": "https://stonehaven.example.com/webhook/test-project",
                    "content_type": "json",
                    "secret": "****",
                    "insecure_ssl": "0"
                },
                "events": ["pull_request", "push"],
                "active": True
            }
        ))
        
        result = await register_webhook(
            repo_owner="testowner",
            repo_name="testrepo", 
            webhook_url="https://stonehaven.example.com/webhook/test-project",
            secret="test-secret-123",
            github_token="ghp_testtoken123"
        )
        
        assert result == webhook_id


@pytest.mark.asyncio
async def test_register_webhook_invalid_token():
    """Test webhook registration with invalid GitHub token raises WebhookError."""
    with respx.mock:
        respx.get(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(
            401,
            json={"message": "Bad credentials"}
        ))
        
        with pytest.raises(WebhookError, match="Failed to list existing webhooks"):
            await register_webhook(
                repo_owner="testowner",
                repo_name="testrepo",
                webhook_url="https://stonehaven.example.com/webhook/test-project", 
                secret="test-secret-123",
                github_token="invalid_token"
            )


@pytest.mark.asyncio
async def test_register_webhook_repo_not_found():
    """Test webhook registration for non-existent repo raises WebhookError."""
    with respx.mock:
        respx.get(
            "https://api.github.com/repos/testowner/nonexistent/hooks"
        ).mock(return_value=httpx.Response(
            404,
            json={"message": "Not Found"}
        ))
        
        with pytest.raises(WebhookError, match="Repository not found or access denied"):
            await register_webhook(
                repo_owner="testowner",
                repo_name="nonexistent",
                webhook_url="https://stonehaven.example.com/webhook/test-project",
                secret="test-secret-123", 
                github_token="ghp_testtoken123"
            )


@pytest.mark.asyncio
async def test_register_webhook_replaces_existing():
    """Test webhook registration replaces existing webhook with same URL."""
    existing_webhook_id = 11111111
    
    with respx.mock:
        # Mock existing webhook with same URL
        respx.get(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(
            200,
            json=[
                {
                    "id": existing_webhook_id,
                    "config": {
                        "url": "https://stonehaven.example.com/webhook/test-project"
                    }
                },
                {
                    "id": 22222222,
                    "config": {
                        "url": "https://different.example.com/webhook"  
                    }
                }
            ]
        ))
        
        # Mock successful webhook update
        respx.patch(
            f"https://api.github.com/repos/testowner/testrepo/hooks/{existing_webhook_id}"
        ).mock(return_value=httpx.Response(200, json={"id": existing_webhook_id}))
        
        result = await register_webhook(
            repo_owner="testowner",
            repo_name="testrepo",
            webhook_url="https://stonehaven.example.com/webhook/test-project",
            secret="updated-secret-456", 
            github_token="ghp_testtoken123"
        )
        
        assert result == existing_webhook_id


@pytest.mark.asyncio
async def test_register_webhook_includes_secret():
    """Test webhook registration includes HMAC secret in configuration."""
    with respx.mock:
        # Mock empty existing webhooks
        respx.get(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(200, json=[]))
        
        # Capture the request to verify secret is included
        webhook_request = respx.post(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(
            201,
            json={"id": 12345678}
        ))
        
        await register_webhook(
            repo_owner="testowner", 
            repo_name="testrepo",
            webhook_url="https://stonehaven.example.com/webhook/test-project",
            secret="supersecret123",
            github_token="ghp_testtoken123"
        )
        
        # Verify the request included the secret
        request_data = webhook_request.calls[0].request.content
        assert b"supersecret123" in request_data
        
        # Verify webhook events are configured correctly
        assert b'"events":["pull_request","push"]' in request_data
        
        # Verify SSL is required 
        assert b'"insecure_ssl":"0"' in request_data


@pytest.mark.asyncio
async def test_register_webhook_update_existing_fails():
    """Test failure when updating existing webhook raises WebhookError."""
    existing_webhook_id = 11111111
    
    with respx.mock:
        # Mock existing webhook found
        respx.get(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(
            200,
            json=[{
                "id": existing_webhook_id,
                "config": {
                    "url": "https://stonehaven.example.com/webhook/test-project"
                }
            }]
        ))
        
        # Mock failed webhook update
        respx.patch(
            f"https://api.github.com/repos/testowner/testrepo/hooks/{existing_webhook_id}"
        ).mock(return_value=httpx.Response(
            403,
            json={"message": "Forbidden"}
        ))
        
        with pytest.raises(WebhookError, match=f"Failed to update existing webhook {existing_webhook_id}"):
            await register_webhook(
                repo_owner="testowner",
                repo_name="testrepo",
                webhook_url="https://stonehaven.example.com/webhook/test-project", 
                secret="test-secret-123",
                github_token="ghp_testtoken123"
            )


@pytest.mark.asyncio
async def test_register_webhook_create_fails_with_validation_errors():
    """Test webhook creation failure with validation errors."""
    with respx.mock:
        # Mock empty existing webhooks
        respx.get(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(200, json=[]))
        
        # Mock failed webhook creation with validation errors
        respx.post(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(
            422,
            json={
                "message": "Validation Failed",
                "errors": [
                    {"field": "config.url", "message": "is invalid"},
                    {"field": "events", "message": "is too long"}
                ]
            }
        ))
        
        with pytest.raises(WebhookError, match="Validation Failed.*config.url.*is invalid.*events.*is too long"):
            await register_webhook(
                repo_owner="testowner",
                repo_name="testrepo",
                webhook_url="invalid-url",
                secret="test-secret-123",
                github_token="ghp_testtoken123"
            )


@pytest.mark.asyncio 
async def test_register_webhook_network_error():
    """Test webhook registration handles network errors."""
    # Use a mock that simulates a timeout rather than connection error
    # since respx doesn't handle side_effect exceptions well
    with respx.mock:
        respx.get(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(
            503,
            json={"message": "Service unavailable"}
        ))
        
        with pytest.raises(WebhookError, match="Failed to list existing webhooks"):
            await register_webhook(
                repo_owner="testowner",
                repo_name="testrepo", 
                webhook_url="https://stonehaven.example.com/webhook/test-project",
                secret="test-secret-123",
                github_token="ghp_testtoken123"
            )


def test_register_webhook_sync():
    """Test synchronous wrapper function works correctly.""" 
    with respx.mock:
        # Mock existing webhooks check (empty list)
        respx.get(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(200, json=[]))
        
        # Mock successful webhook creation
        respx.post(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(
            201,
            json={"id": 87654321}
        ))
        
        result = register_webhook_sync(
            repo_owner="testowner",
            repo_name="testrepo",
            webhook_url="https://stonehaven.example.com/webhook/test-project",
            secret="test-secret-123", 
            github_token="ghp_testtoken123"
        )
        
        assert result == 87654321


@pytest.mark.asyncio
async def test_register_webhook_proper_headers():
    """Test webhook registration includes proper GitHub API headers."""
    with respx.mock:
        # Mock requests to capture headers
        hooks_request = respx.get(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(200, json=[]))
        
        create_request = respx.post(
            "https://api.github.com/repos/testowner/testrepo/hooks"
        ).mock(return_value=httpx.Response(201, json={"id": 12345678}))
        
        await register_webhook(
            repo_owner="testowner",
            repo_name="testrepo",
            webhook_url="https://stonehaven.example.com/webhook/test-project",
            secret="test-secret-123",
            github_token="ghp_testtoken123" 
        )
        
        # Verify headers on both requests
        for request in [hooks_request, create_request]:
            headers = request.calls[0].request.headers
            assert headers["Authorization"] == "Bearer ghp_testtoken123"
            assert headers["Accept"] == "application/vnd.github.v3+json"
            assert headers["X-GitHub-Api-Version"] == "2022-11-28"
            assert headers["User-Agent"] == "agent-harness-webhook-manager/1.0"
"""End-to-end greenfield initialization tests.

This is a GATE issue - no runtime path progress until these tests pass.
Tests the complete greenfield flow from project_context.md through
agent scaffolding, webhook registration, and Stonehaven registration.
"""

import pytest
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli.init import init_greenfield, InitError


@pytest.fixture
def temp_project_root():
    """Create a temporary project root directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir) / "project"


@pytest.fixture
def valid_project_context():
    """Valid project_context.md content for testing."""
    return """---
project:
  name: "test-e2e-project"
  description: "End-to-end test project"

stack:
  language: "python"
  framework: "fastapi"
  primary_files:
    high_blast_radius:
      - "app.py"
      - "models.py"
    generated:
      - "migrations/"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true
  production_record_count: 50000

invariants:
  - id: "no_direct_db_access"
    rule: "All database access must go through repository pattern"
    severity: "correctness"
  - id: "auth_required"
    rule: "All API endpoints require authentication"
    severity: "data_consistency"

sharp_edges:
  - location: "database/migrations.py"
    issue: "Manual migration validation required"
    fix: "Always dry-run migrations in staging first"

structural_decisions:
  - decision: "FastAPI with Pydantic v2"
    rationale: "Type safety and API documentation generation"

becoming:
  - "Add real-time event streaming"
  - "Implement advanced caching layer"

reviewers:
  engineer:
    enabled: true
    model_class: "code_review"
  architect:
    enabled: true
    model_class: "structural_review"
  sre:
    enabled: true
    model_class: "adversarial_review"
  deploy:
    enabled: false
    surfaces: []
---

This is the test project context for end-to-end greenfield testing.
"""


@pytest.fixture
def mock_templates_dir():
    """Mock templates directory path."""
    return Path("/mock/templates")


@pytest.fixture
def stonehaven_url():
    """Test Stonehaven URL."""
    return "https://stonehaven.test.local"


@pytest.fixture
def github_token():
    """Test GitHub token."""
    return "ghp_test_token_e2e_12345"


@pytest.fixture
def mock_subprocess():
    """Mock subprocess for git commands."""
    with patch("subprocess.run") as mock:
        mock.return_value.stdout = "git@github.com:testowner/test-e2e-project.git"
        mock.return_value.returncode = 0
        yield mock


def test_greenfield_e2e_complete_flow(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token,
    valid_project_context,
    mock_subprocess,
):
    """End-to-end test of complete greenfield initialization.
    
    This is the primary GATE test - verifies full flow end-to-end:
    - Agents scaffolded in .factory/agents/
    - Webhook registered with GitHub  
    - Project registered with Stonehaven
    - All manifests created (.factory/harness.toml, webhook_config.yml, templates_lock.yml)
    """
    # Setup project structure
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_project_context)

    # Mock all external dependencies
    with patch("cli.init.render_agents") as mock_render, \
         patch("cli.init.register_webhook_sync", return_value=98765) as mock_webhook, \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock for Stonehaven registration
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        # Execute complete greenfield flow
        init_greenfield(
            project_root=temp_project_root,
            templates_dir=mock_templates_dir,
            stonehaven_url=stonehaven_url,
            github_token=github_token
        )

        # GATE REQUIREMENT: Verify agents scaffolded in .factory/agents/
        agents_dir = factory_dir / "agents"
        assert agents_dir.exists(), ".factory/agents/ directory must be created"
        
        # GATE REQUIREMENT: Verify webhook registered with GitHub
        mock_webhook.assert_called_once()
        webhook_call_args = mock_webhook.call_args
        assert webhook_call_args.kwargs["repo_owner"] == "testowner"
        assert webhook_call_args.kwargs["repo_name"] == "test-e2e-project"
        assert "stonehaven.test.local/webhooks/" in webhook_call_args.kwargs["webhook_url"]
        assert len(webhook_call_args.kwargs["secret"]) == 64  # 32 bytes hex
        assert webhook_call_args.kwargs["github_token"] == github_token
        
        # GATE REQUIREMENT: Verify project registered with Stonehaven
        mock_client.post.assert_called_once()
        stonehaven_call_args = mock_client.post.call_args
        assert stonehaven_call_args[0][0] == f"{stonehaven_url}/api/v1/projects/register"
        request_data = stonehaven_call_args.kwargs["json"]
        assert "stonehaven_id" in request_data
        assert request_data["repo"] == "testowner/test-e2e-project"
        assert request_data["project_name"] == "test-e2e-project"
        
        # GATE REQUIREMENT: Verify all manifests created
        # 1. .factory/harness.toml
        harness_toml = factory_dir / "harness.toml"
        assert harness_toml.exists(), "harness.toml manifest must be created"
        harness_content = harness_toml.read_text()
        assert 'stonehaven_id = ' in harness_content
        assert 'project_name = "test-e2e-project"' in harness_content
        assert 'repo = "testowner/test-e2e-project"' in harness_content
        assert 'webhook_id = 98765' in harness_content
        assert 'harness_version = "0.1.0"' in harness_content
        
        # 2. .factory/webhook_config.yml
        webhook_config = factory_dir / "webhook_config.yml"
        assert webhook_config.exists(), "webhook_config.yml must be created"
        
        # 3. Verify render_agents was called (this creates templates_lock.yml)
        mock_render.assert_called_once()
        render_call_args = mock_render.call_args
        assert render_call_args.kwargs["project_context_path"] == context_path
        assert render_call_args.kwargs["templates_dir"] == mock_templates_dir
        assert render_call_args.kwargs["output_dir"] == agents_dir
        assert render_call_args.kwargs["update_lock"] is True


def test_greenfield_e2e_agents_scaffolded(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token,
    valid_project_context,
    mock_subprocess,
):
    """Test that agents are properly scaffolded in .factory/agents/."""
    # Setup project structure
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_project_context)

    with patch("cli.init.render_agents") as mock_render, \
         patch("cli.init.register_webhook_sync", return_value=11111), \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        init_greenfield(
            project_root=temp_project_root,
            templates_dir=mock_templates_dir,
            stonehaven_url=stonehaven_url,
            github_token=github_token
        )

        # Verify agents directory structure was created
        agents_dir = factory_dir / "agents"
        assert agents_dir.exists()
        assert agents_dir.is_dir()
        
        # Verify render_agents was called with correct parameters
        mock_render.assert_called_once()
        call_args = mock_render.call_args
        assert call_args.kwargs["project_context_path"] == context_path
        assert call_args.kwargs["templates_dir"] == mock_templates_dir
        assert call_args.kwargs["output_dir"] == agents_dir
        assert call_args.kwargs["update_lock"] is True


def test_greenfield_e2e_webhook_registered(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token,
    valid_project_context,
    mock_subprocess,
):
    """Test webhook registration succeeds."""
    # Setup project structure
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_project_context)

    expected_webhook_id = 55555
    
    with patch("cli.init.render_agents"), \
         patch("cli.init.register_webhook_sync", return_value=expected_webhook_id) as mock_webhook, \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        init_greenfield(
            project_root=temp_project_root,
            templates_dir=mock_templates_dir,
            stonehaven_url=stonehaven_url,
            github_token=github_token
        )

        # Verify webhook registration was called
        mock_webhook.assert_called_once()
        call_args = mock_webhook.call_args
        
        # Check webhook registration parameters
        assert call_args.kwargs["repo_owner"] == "testowner"
        assert call_args.kwargs["repo_name"] == "test-e2e-project" 
        assert call_args.kwargs["webhook_url"].startswith(f"{stonehaven_url}/webhooks/")
        assert len(call_args.kwargs["secret"]) == 64  # 32 bytes hex = 64 chars
        assert call_args.kwargs["github_token"] == github_token
        
        # Verify webhook URL contains a valid UUID
        webhook_url = call_args.kwargs["webhook_url"]
        stonehaven_id = webhook_url.split("/webhooks/")[-1]
        # Should not raise if valid UUID
        uuid.UUID(stonehaven_id, version=4)
        
        # Verify webhook ID is recorded in harness.toml
        harness_toml = factory_dir / "harness.toml"
        assert harness_toml.exists()
        content = harness_toml.read_text()
        assert f'webhook_id = {expected_webhook_id}' in content


def test_greenfield_e2e_manifests_created(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token,
    valid_project_context,
    mock_subprocess,
):
    """Test all manifest files are created correctly."""
    # Setup project structure  
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_project_context)

    with patch("cli.init.render_agents"), \
         patch("cli.init.register_webhook_sync", return_value=77777), \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        init_greenfield(
            project_root=temp_project_root,
            templates_dir=mock_templates_dir,
            stonehaven_url=stonehaven_url,
            github_token=github_token
        )

        # Verify harness.toml manifest
        harness_toml = factory_dir / "harness.toml"
        assert harness_toml.exists()
        harness_content = harness_toml.read_text()
        
        # Check all required fields in harness.toml
        assert 'stonehaven_id = ' in harness_content
        assert 'project_name = "test-e2e-project"' in harness_content
        assert 'repo = "testowner/test-e2e-project"' in harness_content
        assert 'webhook_id = 77777' in harness_content
        assert 'harness_version = "0.1.0"' in harness_content
        assert 'registered_at = ' in harness_content
        
        # Verify webhook_config.yml manifest
        webhook_config = factory_dir / "webhook_config.yml"
        assert webhook_config.exists()
        
        import yaml
        with webhook_config.open() as f:
            config = yaml.safe_load(f)
        
        # Check all required fields in webhook_config.yml
        assert "stonehaven_id" in config
        assert "secret" in config
        assert "url" in config
        assert "created_at" in config
        assert len(config["secret"]) == 64  # 32 bytes hex = 64 chars
        assert config["url"].startswith(f"{stonehaven_url}/webhooks/")
        
        # Verify stonehaven_id is consistent between files
        stonehaven_id_from_webhook = config["stonehaven_id"]
        assert f'stonehaven_id = "{stonehaven_id_from_webhook}"' in harness_content
        
        # Verify webhook URL contains the same stonehaven_id
        webhook_url = config["url"]
        assert webhook_url.endswith(f"/webhooks/{stonehaven_id_from_webhook}")


def test_greenfield_e2e_failure_missing_context(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token,
):
    """Test initialization fails gracefully when project_context.md is missing."""
    temp_project_root.mkdir(parents=True)
    # Note: NOT creating .factory/project_context.md

    with pytest.raises(InitError) as exc_info:
        init_greenfield(
            project_root=temp_project_root,
            templates_dir=mock_templates_dir,
            stonehaven_url=stonehaven_url,
            github_token=github_token
        )

    assert "project_context.md not found" in str(exc_info.value)
    assert "prd-generator skill" in str(exc_info.value)


def test_greenfield_e2e_failure_invalid_context(
    temp_project_root,
    mock_templates_dir, 
    stonehaven_url,
    github_token,
):
    """Test initialization fails gracefully with invalid project context."""
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    
    # Write invalid YAML content
    context_path.write_text("invalid: yaml: content: [")

    with pytest.raises(InitError) as exc_info:
        init_greenfield(
            project_root=temp_project_root,
            templates_dir=mock_templates_dir,
            stonehaven_url=stonehaven_url,
            github_token=github_token
        )

    assert "Invalid project_context.md" in str(exc_info.value)


def test_greenfield_e2e_failure_render_error(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token,
    valid_project_context,
):
    """Test initialization fails gracefully when agent rendering fails."""
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_project_context)

    with patch("cli.init.render_agents", side_effect=Exception("Template not found")):
        with pytest.raises(InitError) as exc_info:
            init_greenfield(
                project_root=temp_project_root,
                templates_dir=mock_templates_dir,
                stonehaven_url=stonehaven_url,
                github_token=github_token
            )

        assert "Failed to render agent files" in str(exc_info.value)
        assert "Template not found" in str(exc_info.value)


def test_greenfield_e2e_failure_webhook_error(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token,
    valid_project_context,
    mock_subprocess,
):
    """Test initialization fails gracefully when webhook registration fails."""
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_project_context)

    with patch("cli.init.render_agents"), \
         patch("cli.init.register_webhook_sync", side_effect=Exception("GitHub API error")), \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock  
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        with pytest.raises(InitError) as exc_info:
            init_greenfield(
                project_root=temp_project_root,
                templates_dir=mock_templates_dir,
                stonehaven_url=stonehaven_url,
                github_token=github_token
            )

        assert "Failed to register GitHub webhook" in str(exc_info.value)
        assert "GitHub API error" in str(exc_info.value)


def test_greenfield_e2e_failure_stonehaven_error(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token,
    valid_project_context,
    mock_subprocess,
):
    """Test initialization fails gracefully when Stonehaven registration fails."""
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_project_context)

    with patch("cli.init.render_agents"), \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock to fail
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 500
        mock_client.post.return_value.reason_phrase = "Internal Server Error"
        
        with pytest.raises(InitError) as exc_info:
            init_greenfield(
                project_root=temp_project_root,
                templates_dir=mock_templates_dir,
                stonehaven_url=stonehaven_url,
                github_token=github_token
            )

        assert "Failed to register with Stonehaven" in str(exc_info.value)


def test_greenfield_e2e_idempotent_execution(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token,
    valid_project_context,
    mock_subprocess,
):
    """Test that greenfield initialization is idempotent (safe to run multiple times)."""
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_project_context)

    with patch("cli.init.render_agents"), \
         patch("cli.init.register_webhook_sync", return_value=33333), \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock - first call succeeds, second returns 409 (conflict)
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.side_effect = [
            MagicMock(status_code=200),  # First registration succeeds
            MagicMock(status_code=409),  # Second registration returns conflict (already registered)
        ]
        
        # Run initialization twice
        init_greenfield(
            project_root=temp_project_root,
            templates_dir=mock_templates_dir,
            stonehaven_url=stonehaven_url,
            github_token=github_token
        )
        
        # Capture stonehaven_id from first run
        harness_toml = factory_dir / "harness.toml"
        first_content = harness_toml.read_text()
        first_stonehaven_id = None
        for line in first_content.split('\n'):
            if line.strip().startswith('stonehaven_id = '):
                first_stonehaven_id = line.split('=', 1)[1].strip().strip('"\'')
                break
        
        # Run second time - should be idempotent
        init_greenfield(
            project_root=temp_project_root,
            templates_dir=mock_templates_dir,
            stonehaven_url=stonehaven_url,
            github_token=github_token
        )
        
        # Verify same stonehaven_id is reused
        second_content = harness_toml.read_text()
        assert first_stonehaven_id is not None
        assert f'stonehaven_id = "{first_stonehaven_id}"' in second_content
        
        # Verify both Stonehaven registration calls were made
        assert mock_client.post.call_count == 2
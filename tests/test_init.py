"""Tests for cli.init module."""

import pytest
import uuid
import yaml
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, AsyncMock

from cli.init import InitError, init_greenfield, init_analyze, init_finalize


@pytest.fixture
def temp_project_root(tmp_path):
    """Create a temporary project root directory."""
    return tmp_path / "project"


@pytest.fixture
def templates_dir():
    """Mock templates directory."""
    return Path("/mock/templates")


@pytest.fixture
def stonehaven_url():
    """Mock Stonehaven URL."""
    return "https://stonehaven.example.com"


@pytest.fixture
def github_token():
    """Mock GitHub token."""
    return "ghp_test_token_123"


@pytest.fixture
def mock_subprocess():
    """Mock subprocess for git commands."""
    with patch("subprocess.run") as mock:
        mock.return_value.stdout = "git@github.com:owner/repo.git"
        mock.return_value.returncode = 0
        yield mock


@pytest.fixture
def valid_context_content():
    """Valid project_context.md content."""
    return """---
project:
  name: "test-project"
  description: "A test project"

stack:
  language: "python"
  framework: "fastapi"
  primary_files:
    high_blast_radius:
      - "app.py"
    generated: []

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants:
  - id: "test_invariant"
    rule: "Test rule"
    severity: "correctness"

sharp_edges: []

structural_decisions: []

becoming: []

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

Test project context file.
"""


def test_init_greenfield_full_flow(
    temp_project_root, templates_dir, stonehaven_url, github_token, valid_context_content, mock_subprocess
):
    """Test complete greenfield initialization flow."""
    # Setup project structure
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_context_content)

    # Mock all external dependencies
    with patch("cli.init.render_agents") as mock_render, \
         patch("cli.init.register_webhook_sync", return_value=12345) as mock_webhook, \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)

        # Verify agents directory was created
        assert (factory_dir / "agents").exists()
        
        # Verify webhook_config.yml was created
        webhook_config = factory_dir / "webhook_config.yml"
        assert webhook_config.exists()
        
        # Verify harness.toml was created
        harness_toml = factory_dir / "harness.toml"
        assert harness_toml.exists()

        # Verify render_agents was called
        mock_render.assert_called_once()
        
        # Verify webhook registration was called
        mock_webhook.assert_called_once()
        
        # Verify Stonehaven registration was called
        mock_client.post.assert_called_once()


def test_init_greenfield_missing_context(temp_project_root, templates_dir, stonehaven_url, github_token):
    """Test initialization fails when project_context.md is missing."""
    temp_project_root.mkdir(parents=True)

    with pytest.raises(InitError) as exc_info:
        init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)

    assert "project_context.md not found" in str(exc_info.value)
    assert "prd-generator skill" in str(exc_info.value)


def test_init_greenfield_webhook_registration(
    temp_project_root, templates_dir, stonehaven_url, github_token, valid_context_content, mock_subprocess
):
    """Test webhook registration functionality."""
    # Setup project structure
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_context_content)

    with patch("cli.init.render_agents"), \
         patch("cli.init.register_webhook_sync", return_value=12345) as mock_webhook, \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock for Stonehaven
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)
        
        # Verify webhook registration was called with correct parameters
        mock_webhook.assert_called_once()
        call_args = mock_webhook.call_args
        kwargs = call_args.kwargs
        
        assert kwargs["repo_owner"] == "owner"
        assert kwargs["repo_name"] == "repo"
        assert "stonehaven.example.com/webhooks/" in kwargs["webhook_url"]
        assert len(kwargs["secret"]) == 64  # 32 bytes hex = 64 chars
        assert kwargs["github_token"] == github_token


def test_init_greenfield_stonehaven_registration(
    temp_project_root, templates_dir, stonehaven_url, github_token, valid_context_content, mock_subprocess
):
    """Test Stonehaven registration functionality."""
    # Setup project structure
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_context_content)

    with patch("cli.init.render_agents"), \
         patch("cli.init.register_webhook_sync", return_value=12345), \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock for Stonehaven
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)
        
        # Verify Stonehaven registration was called
        mock_client.post.assert_called_once()
        args, kwargs = mock_client.post.call_args
        
        # Check URL
        assert args[0] == "https://stonehaven.example.com/api/v1/projects/register"
        
        # Check request data
        request_data = kwargs["json"]
        assert "stonehaven_id" in request_data
        assert request_data["repo"] == "owner/repo"
        assert request_data["project_name"] == "test-project"
        
        # Check headers
        headers = kwargs["headers"]
        assert headers["Authorization"] == "Bearer admin-token"


def test_init_greenfield_creates_harness_toml(
    temp_project_root, templates_dir, stonehaven_url, github_token, valid_context_content, mock_subprocess
):
    """Test harness.toml creation."""
    # Setup project structure
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_context_content)

    with patch("cli.init.render_agents"), \
         patch("cli.init.register_webhook_sync", return_value=12345), \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)
        
        # Verify harness.toml was created with correct content
        harness_toml = factory_dir / "harness.toml"
        assert harness_toml.exists()
        
        content = harness_toml.read_text()
        assert 'stonehaven_id = ' in content
        assert 'project_name = "test-project"' in content
        assert 'repo = "owner/repo"' in content
        assert 'webhook_id = 12345' in content
        assert 'harness_version = "0.1.0"' in content


def test_init_greenfield_creates_webhook_config(
    temp_project_root, templates_dir, stonehaven_url, github_token, valid_context_content, mock_subprocess
):
    """Test webhook_config.yml creation."""
    # Setup project structure
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_context_content)

    with patch("cli.init.render_agents"), \
         patch("cli.init.register_webhook_sync", return_value=12345), \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)
        
        # Verify webhook_config.yml was created
        webhook_config = factory_dir / "webhook_config.yml"
        assert webhook_config.exists()
        
        # Parse and verify content
        import yaml
        with webhook_config.open() as f:
            config = yaml.safe_load(f)
        
        assert "stonehaven_id" in config
        assert "secret" in config
        assert "url" in config
        assert "created_at" in config
        assert len(config["secret"]) == 64  # 32 bytes hex = 64 chars
        assert "stonehaven.example.com/webhooks/" in config["url"]


def test_init_greenfield_idempotent_full_flow(
    temp_project_root, templates_dir, stonehaven_url, github_token, valid_context_content, mock_subprocess
):
    """Test that full flow is idempotent."""
    # Setup project structure
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_context_content)

    with patch("cli.init.render_agents"), \
         patch("cli.init.register_webhook_sync", return_value=12345), \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock - first call succeeds, second returns 409 (already registered)
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.side_effect = [
            MagicMock(status_code=200),  # First call succeeds
            MagicMock(status_code=409),  # Second call returns conflict (already registered)
        ]
        
        # Run init twice
        init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)
        
        # Store first stonehaven_id
        harness_toml = factory_dir / "harness.toml"
        first_content = harness_toml.read_text()
        first_stonehaven_id = None
        for line in first_content.split('\n'):
            if line.strip().startswith('stonehaven_id = '):
                first_stonehaven_id = line.split('=', 1)[1].strip().strip('"\'')
                break
        
        # Run second time
        init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)
        
        # Verify same stonehaven_id is used
        second_content = harness_toml.read_text()
        assert first_stonehaven_id is not None
        assert f'stonehaven_id = "{first_stonehaven_id}"' in second_content


def test_init_greenfield_invalid_context(temp_project_root, templates_dir, stonehaven_url, github_token):
    """Test initialization fails with invalid project context."""
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    # Write invalid YAML
    context_path.write_text("invalid: yaml: content: [")

    with pytest.raises(InitError) as exc_info:
        init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)

    assert "Invalid project_context.md" in str(exc_info.value)


def test_init_greenfield_render_failure(
    temp_project_root, templates_dir, stonehaven_url, github_token, valid_context_content
):
    """Test initialization fails when render_agents fails."""
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_context_content)

    with patch("cli.init.render_agents", side_effect=Exception("Render failed")):
        with pytest.raises(InitError) as exc_info:
            init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)

        assert "Failed to render agent files" in str(exc_info.value)
        assert "Render failed" in str(exc_info.value)


def test_init_greenfield_webhook_registration_failure(
    temp_project_root, templates_dir, stonehaven_url, github_token, valid_context_content, mock_subprocess
):
    """Test initialization fails when webhook registration fails."""
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_context_content)

    with patch("cli.init.render_agents"), \
         patch("cli.init.register_webhook_sync", side_effect=Exception("Webhook failed")), \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        with pytest.raises(InitError) as exc_info:
            init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)

        assert "Failed to register GitHub webhook" in str(exc_info.value)
        assert "Webhook failed" in str(exc_info.value)


def test_init_greenfield_stonehaven_registration_failure(
    temp_project_root, templates_dir, stonehaven_url, github_token, valid_context_content, mock_subprocess
):
    """Test initialization fails when Stonehaven registration fails."""
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_context_content)

    with patch("cli.init.render_agents"), \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock to fail
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 500
        mock_client.post.return_value.reason_phrase = "Internal Server Error"
        
        with pytest.raises(InitError) as exc_info:
            init_greenfield(temp_project_root, templates_dir, stonehaven_url, github_token)

        assert "Failed to register with Stonehaven" in str(exc_info.value)


def test_get_or_generate_stonehaven_id_existing_file():
    """Test stonehaven ID extraction from existing harness.toml."""
    from cli.init import _get_or_generate_stonehaven_id
    import tempfile
    import uuid
    
    existing_id = str(uuid.uuid4())
    toml_content = f'''stonehaven_id = "{existing_id}"
project_name = "test"
'''
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.toml') as f:
        f.write(toml_content)
        f.flush()
        
        result = _get_or_generate_stonehaven_id(Path(f.name))
        assert result == existing_id


def test_get_or_generate_stonehaven_id_invalid_file():
    """Test stonehaven ID generation when file is invalid."""
    from cli.init import _get_or_generate_stonehaven_id
    import tempfile
    
    invalid_content = "invalid toml content: ["
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.toml') as f:
        f.write(invalid_content)
        f.flush()
        
        result = _get_or_generate_stonehaven_id(Path(f.name))
        # Should generate a new UUID
        uuid.UUID(result, version=4)  # Will raise if not valid UUID4


def test_get_or_generate_webhook_secret_existing_file():
    """Test webhook secret extraction from existing webhook_config.yml."""
    from cli.init import _get_or_generate_webhook_secret
    import tempfile
    
    existing_secret = "existing_secret_123"
    config = {"secret": existing_secret, "other": "data"}
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yml') as f:
        yaml.dump(config, f)
        f.flush()
        
        result = _get_or_generate_webhook_secret(Path(f.name))
        assert result == existing_secret


def test_get_or_generate_webhook_secret_invalid_file():
    """Test webhook secret generation when file is invalid."""
    from cli.init import _get_or_generate_webhook_secret
    import tempfile
    
    invalid_content = "invalid: yaml: content: ["
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yml') as f:
        f.write(invalid_content)
        f.flush()
        
        result = _get_or_generate_webhook_secret(Path(f.name))
        # Should generate a new secret (64 hex chars = 32 bytes)
        assert len(result) == 64
        

def test_extract_repo_info_git_failure_fallback():
    """Test repo info extraction with git failure and fallback to project context."""
    from cli.init import _extract_repo_info
    import tempfile
    
    project_context = {
        "project": {"name": "owner/repo-from-context"}
    }
    
    with tempfile.TemporaryDirectory() as temp_dir, \
         patch("subprocess.run", side_effect=Exception("git failed")):
        
        project_root = Path(temp_dir)
        result = _extract_repo_info(project_root, project_context)
        
        assert result["owner"] == "owner"
        assert result["name"] == "repo-from-context"
        assert result["full_name"] == "owner/repo-from-context"


def test_extract_repo_info_no_git_no_slash():
    """Test repo info extraction failure when no git and no slash in project name."""
    from cli.init import _extract_repo_info
    import tempfile
    
    project_context = {
        "project": {"name": "just-a-name"}
    }
    
    with tempfile.TemporaryDirectory() as temp_dir, \
         patch("subprocess.run", side_effect=Exception("git failed")):
        
        project_root = Path(temp_dir)
        
        with pytest.raises(InitError) as exc_info:
            _extract_repo_info(project_root, project_context)
        
        assert "Cannot determine repository owner/name" in str(exc_info.value)
        assert "just-a-name" in str(exc_info.value)


def test_extract_repo_info_https_url():
    """Test repo info extraction from HTTPS git URL."""
    from cli.init import _extract_repo_info
    import tempfile
    
    project_context = {"project": {"name": "test"}}
    
    with tempfile.TemporaryDirectory() as temp_dir, \
         patch("subprocess.run") as mock_run:
        
        mock_run.return_value.stdout = "https://github.com/owner/repo.git"
        mock_run.return_value.returncode = 0
        
        project_root = Path(temp_dir)
        result = _extract_repo_info(project_root, project_context)
        
        assert result["owner"] == "owner"
        assert result["name"] == "repo"
        assert result["full_name"] == "owner/repo"


def test_extract_repo_info_unrecognized_url():
    """Test repo info extraction with unrecognized URL format."""
    from cli.init import _extract_repo_info
    import tempfile
    
    project_context = {"project": {"name": "owner/fallback"}}
    
    with tempfile.TemporaryDirectory() as temp_dir, \
         patch("subprocess.run") as mock_run:
        
        mock_run.return_value.stdout = "https://gitlab.com/owner/repo.git"  # Not github.com
        mock_run.return_value.returncode = 0
        
        project_root = Path(temp_dir)
        result = _extract_repo_info(project_root, project_context)
        
        # Should fall back to project context
        assert result["owner"] == "owner"
        assert result["name"] == "fallback"
        assert result["full_name"] == "owner/fallback"


def test_register_with_stonehaven_json_parse_error():
    """Test Stonehaven registration with JSON parse error."""
    from cli.init import _register_with_stonehaven
    
    with patch("cli.init.httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        
        # Mock response with non-JSON content but error status
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.reason_phrase = "Bad Request"
        mock_response.json.side_effect = Exception("Not JSON")
        mock_client.post.return_value = mock_response
        
        with pytest.raises(InitError) as exc_info:
            _register_with_stonehaven(
                "https://stonehaven.test",
                "test-id",
                "owner/repo",
                "test-project"
            )
        
        assert "400 Bad Request" in str(exc_info.value)


def test_register_with_stonehaven_connection_error():
    """Test Stonehaven registration with connection error."""
    from cli.init import _register_with_stonehaven
    import httpx
    
    with patch("cli.init.httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.side_effect = httpx.RequestError("Connection failed")
        
        with pytest.raises(InitError) as exc_info:
            _register_with_stonehaven(
                "https://stonehaven.test",
                "test-id",
                "owner/repo",
                "test-project"
            )
        
        assert "Failed to connect to Stonehaven" in str(exc_info.value)
        assert "Connection failed" in str(exc_info.value)


def test_extract_repo_info_weird_github_url():
    """Test repo info extraction with weird GitHub URL that contains github.com but isn't proper format."""
    from cli.init import _extract_repo_info
    import tempfile
    
    project_context = {"project": {"name": "owner/fallback"}}
    
    with tempfile.TemporaryDirectory() as temp_dir, \
         patch("subprocess.run") as mock_run:
        
        # URL contains github.com but not in expected SSH or HTTPS format
        mock_run.return_value.stdout = "ftp://github.com"  # Contains github.com but not proper format
        mock_run.return_value.returncode = 0
        
        project_root = Path(temp_dir)
        result = _extract_repo_info(project_root, project_context)
        
        # Should fall back to project context after ValueError
        assert result["owner"] == "owner"
        assert result["name"] == "fallback"
        assert result["full_name"] == "owner/fallback"


# Tests for init_analyze function

@pytest.fixture
def mock_claude_client():
    """Mock Claude client for testing."""
    return MagicMock()


@pytest.fixture
def mock_analysis_result():
    """Mock analysis result from RepoAnalyzer."""
    result = MagicMock()
    result.proposed_context = {
        "project": {
            "name": "Analyzed Project",
            "description": "A project analyzed by Claude"
        },
        "stack": {
            "language": "Python",
            "framework": "FastAPI"
        },
        "deployment": {
            "surface": "server",
            "rollback_available": True,
            "forced_update": False,
            "user_data_recoverable": True
        },
        "invariants": [{
            "id": "test_invariant",
            "rule": "Test rule",
            "severity": "correctness"
        }],
        "sharp_edges": [],
        "structural_decisions": [],
        "becoming": [],
        "reviewers": {
            "engineer": {"enabled": True, "model_class": "code_review"},
            "architect": {"enabled": True, "model_class": "structural_review"},
            "sre": {"enabled": True, "model_class": "adversarial_review"},
            "deploy": {"enabled": True, "surfaces": ["server"]}
        }
    }
    result.confidence_score = 0.85
    result.analysis_notes = "Analysis completed successfully with high confidence."
    return result


@pytest.mark.asyncio
async def test_init_analyze_creates_context_pr(
    temp_project_root, github_token, mock_claude_client, mock_analysis_result
):
    """Test init_analyze creates context PR successfully."""
    # Setup git repository
    temp_project_root.mkdir(parents=True)
    git_dir = temp_project_root / ".git"
    git_dir.mkdir()
    
    with patch("interview.analyzer.RepoAnalyzer") as mock_analyzer_class, \
         patch("cli.init._create_context_pr") as mock_create_pr:
        
        # Setup analyzer mock
        mock_analyzer = MagicMock()
        mock_analyzer_class.return_value = mock_analyzer
        
        # Mock the async method with AsyncMock
        mock_analyzer.analyze_repository = AsyncMock(return_value=mock_analysis_result)
        
        await init_analyze(temp_project_root, github_token, mock_claude_client)
        
        # Verify .factory directory was created
        factory_dir = temp_project_root / ".factory"
        assert factory_dir.exists()
        
        # Verify project_context.md was created
        context_path = factory_dir / "project_context.md"
        assert context_path.exists()
        
        # Verify content format
        content = context_path.read_text()
        assert content.startswith("---\n")
        
        assert "project:" in content  # Verify YAML structure
        assert "Analysis Notes" in content  
        assert "Next Steps" in content
        assert "Proposed Project Context" in content
        
        # Verify PR creation was attempted (implies analyzer was called successfully)
        mock_create_pr.assert_called_once()


@pytest.mark.asyncio
async def test_init_analyze_existing_factory_dir_error(
    temp_project_root, github_token, mock_claude_client
):
    """Test init_analyze fails when .factory directory already exists."""
    # Setup project with existing .factory directory
    temp_project_root.mkdir(parents=True)
    git_dir = temp_project_root / ".git"
    git_dir.mkdir()
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    
    with pytest.raises(InitError) as exc_info:
        await init_analyze(temp_project_root, github_token, mock_claude_client)
    
    assert ".factory directory already exists" in str(exc_info.value)
    assert "Use init_finalize()" in str(exc_info.value)


@pytest.mark.asyncio
async def test_init_analyze_analysis_failure_cleanup(
    temp_project_root, github_token, mock_claude_client
):
    """Test init_analyze cleans up on analysis failure."""
    # Setup git repository
    temp_project_root.mkdir(parents=True)
    git_dir = temp_project_root / ".git"
    git_dir.mkdir()
    
    with patch("interview.analyzer.RepoAnalyzer") as mock_analyzer_class:
        # Setup analyzer to fail
        mock_analyzer = MagicMock()
        mock_analyzer_class.return_value = mock_analyzer
        
        # Mock the async method to fail with AsyncMock
        mock_analyzer.analyze_repository = AsyncMock(side_effect=Exception("Analysis failed"))
        
        with pytest.raises(InitError) as exc_info:
            await init_analyze(temp_project_root, github_token, mock_claude_client)
        
        assert "Failed to analyze repository" in str(exc_info.value)
        
        # Verify .factory directory was cleaned up
        factory_dir = temp_project_root / ".factory"
        assert not factory_dir.exists()


@pytest.mark.asyncio
async def test_init_analyze_proposed_context_validates(
    temp_project_root, github_token, mock_claude_client, mock_analysis_result
):
    """Test that init_analyze creates valid project context that passes validation."""
    # Setup git repository
    temp_project_root.mkdir(parents=True)
    git_dir = temp_project_root / ".git"
    git_dir.mkdir()
    
    with patch("interview.analyzer.RepoAnalyzer") as mock_analyzer_class, \
         patch("cli.init._create_context_pr"):
        
        # Setup analyzer mock
        mock_analyzer = MagicMock()
        mock_analyzer_class.return_value = mock_analyzer
        
        # Mock the async method with AsyncMock
        mock_analyzer.analyze_repository = AsyncMock(return_value=mock_analysis_result)
        
        await init_analyze(temp_project_root, github_token, mock_claude_client)
        
        # Read the generated context
        context_path = temp_project_root / ".factory" / "project_context.md"
        content = context_path.read_text()
        
        # Extract YAML frontmatter
        frontmatter_end = content.find("\n---\n", 3)
        yaml_content = content[4:frontmatter_end]  # Skip initial "---\n"
        
        # Validate YAML can be parsed
        parsed_yaml = yaml.safe_load(yaml_content)
        
        # Verify structure matches expected schema
        assert "project" in parsed_yaml
        assert "stack" in parsed_yaml
        assert "deployment" in parsed_yaml
        assert "invariants" in parsed_yaml
        assert "reviewers" in parsed_yaml
        
        # Verify project section
        project = parsed_yaml["project"]
        assert "name" in project
        assert "description" in project
        
        # Verify deployment section
        deployment = parsed_yaml["deployment"]
        assert "surface" in deployment
        assert isinstance(deployment["rollback_available"], bool)
        assert isinstance(deployment["forced_update"], bool)
        assert isinstance(deployment["user_data_recoverable"], bool)


# Tests for init_finalize function

def test_init_finalize_after_context_merge(
    temp_project_root, templates_dir, stonehaven_url, github_token, 
    valid_context_content, mock_subprocess
):
    """Test init_finalize completes flow after context PR merge."""
    # Setup project with merged context
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    context_path = factory_dir / "project_context.md"
    context_path.write_text(valid_context_content)
    
    # Mock all external dependencies
    with patch("cli.init.render_agents") as mock_render, \
         patch("cli.init.register_webhook_sync", return_value=12345) as mock_webhook, \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        init_finalize(temp_project_root, templates_dir, stonehaven_url, github_token)
        
        # Verify agents directory was created
        assert (factory_dir / "agents").exists()
        
        # Verify webhook_config.yml was created
        webhook_config = factory_dir / "webhook_config.yml"
        assert webhook_config.exists()
        
        # Verify harness.toml was created
        harness_toml = factory_dir / "harness.toml"
        assert harness_toml.exists()
        
        # Verify render_agents was called
        mock_render.assert_called_once()
        
        # Verify webhook registration was called
        mock_webhook.assert_called_once()
        
        # Verify Stonehaven registration was called
        mock_client.post.assert_called_once()


def test_init_finalize_missing_factory_dir(
    temp_project_root, templates_dir, stonehaven_url, github_token
):
    """Test init_finalize fails when .factory directory doesn't exist."""
    temp_project_root.mkdir(parents=True)
    # No .factory directory
    
    with pytest.raises(InitError) as exc_info:
        init_finalize(temp_project_root, templates_dir, stonehaven_url, github_token)
    
    assert ".factory directory not found" in str(exc_info.value)
    assert "Run init_analyze()" in str(exc_info.value)


def test_init_finalize_missing_context_file(
    temp_project_root, templates_dir, stonehaven_url, github_token
):
    """Test init_finalize fails when project_context.md doesn't exist."""
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    # No project_context.md file
    
    with pytest.raises(InitError) as exc_info:
        init_finalize(temp_project_root, templates_dir, stonehaven_url, github_token)
    
    assert "project_context.md not found" in str(exc_info.value)
    assert "context PR may not have been merged" in str(exc_info.value)


# Tests for helper functions

def test_parse_github_repo_from_url_ssh():
    """Test parsing GitHub repo from SSH URL."""
    from cli.init import _parse_github_repo_from_url
    
    url = "git@github.com:owner/repo.git"
    result = _parse_github_repo_from_url(url)
    assert result == "owner/repo"


def test_parse_github_repo_from_url_https():
    """Test parsing GitHub repo from HTTPS URL."""
    from cli.init import _parse_github_repo_from_url
    
    url = "https://github.com/owner/repo.git"
    result = _parse_github_repo_from_url(url)
    assert result == "owner/repo"


def test_parse_github_repo_from_url_not_github():
    """Test parsing fails for non-GitHub URLs."""
    from cli.init import _parse_github_repo_from_url
    
    url = "git@gitlab.com:owner/repo.git"
    with pytest.raises(ValueError) as exc_info:
        _parse_github_repo_from_url(url)
    
    assert "Not a GitHub repository URL" in str(exc_info.value)


def test_create_github_pr_success():
    """Test successful GitHub PR creation."""
    from cli.init import _create_github_pr
    
    mock_result = MagicMock()
    mock_result.confidence_score = 0.85
    mock_result.analysis_notes = "Test analysis notes"
    
    with patch("cli.init.httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"html_url": "https://github.com/owner/repo/pull/1"}
        mock_client.post.return_value = mock_response
        
        _create_github_pr(
            repo_full_name="owner/repo",
            head_branch="feature-branch",
            base_branch="main",
            github_token="test-token",
            analysis_result=mock_result
        )
        
        # Verify API call was made correctly
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        
        assert call_args[0][0] == "https://api.github.com/repos/owner/repo/pulls"
        assert "test-token" in call_args[1]["headers"]["Authorization"]
        
        payload = call_args[1]["json"]
        assert payload["head"] == "feature-branch"
        assert payload["base"] == "main"
        assert "factory: proposed project context" in payload["title"]
        assert "0.85" in payload["body"]
"""End-to-end analyze initialization tests.

This is a GATE issue - no lifecycle path progress until these tests pass.
Tests the complete analyze flow from repository analysis through context PR creation
to finalization with agent scaffolding and webhook registration.
"""

import pytest
import tempfile
import uuid
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cli.init import init_analyze, init_finalize, InitError
from interview.analyzer import AnalysisResult


@pytest.fixture
def temp_project_root():
    """Create a temporary project root directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir) / "project"


@pytest.fixture
def mock_claude_client():
    """Mock Claude client for testing."""
    return MagicMock()


@pytest.fixture
def mock_analysis_result():
    """Mock analysis result from RepoAnalyzer with credible context."""
    result = MagicMock()
    result.proposed_context = {
        "project": {
            "name": "analyzed-test-project",
            "description": "A test project analyzed by automated repository analysis"
        },
        "stack": {
            "language": "Python",
            "framework": "FastAPI",
            "primary_files": {
                "high_blast_radius": ["app.py", "models.py"],
                "generated": ["migrations/"]
            }
        },
        "deployment": {
            "surface": "server",
            "rollback_available": True,
            "forced_update": False,
            "user_data_recoverable": True,
            "production_record_count": 10000
        },
        "invariants": [
            {
                "id": "auth_required",
                "rule": "All API endpoints must require authentication",
                "severity": "data_consistency"
            },
            {
                "id": "input_validation",
                "rule": "All user inputs must be validated before processing",
                "severity": "correctness"
            }
        ],
        "sharp_edges": [
            {
                "location": "database/connections.py",
                "issue": "Direct database connection management",
                "fix": "Use connection pooling for production deployments"
            }
        ],
        "structural_decisions": [
            {
                "decision": "FastAPI with async/await pattern",
                "rationale": "High-performance async I/O for API endpoints"
            }
        ],
        "becoming": [
            "Add monitoring and observability",
            "Implement caching layer"
        ],
        "reviewers": {
            "engineer": {
                "enabled": True,
                "model_class": "code_review"
            },
            "architect": {
                "enabled": True,
                "model_class": "structural_review"
            },
            "sre": {
                "enabled": True,
                "model_class": "adversarial_review"
            },
            "deploy": {
                "enabled": False,
                "surfaces": []
            }
        }
    }
    result.confidence_score = 0.87
    result.analysis_notes = "Repository analysis completed with high confidence. Detected FastAPI-based server application with clear architectural patterns and comprehensive test coverage."
    return result


@pytest.fixture
def mock_templates_dir():
    """Mock templates directory path."""
    return Path("/mock/templates")


@pytest.fixture
def stonehaven_url():
    """Test Stonehaven URL."""
    return "https://stonehaven.analyze.test"


@pytest.fixture
def github_token():
    """Test GitHub token."""
    return "ghp_analyze_test_token_456"


@pytest.fixture
def mock_subprocess():
    """Mock subprocess for git commands."""
    with patch("subprocess.run") as mock:
        # Mock for getting current branch
        mock.return_value.stdout = "main"
        mock.return_value.returncode = 0
        yield mock


@pytest.mark.asyncio
async def test_analyze_e2e_complete_flow(
    temp_project_root,
    github_token,
    mock_claude_client,
    mock_analysis_result
):
    """End-to-end test of existing repo analysis and context PR creation.
    
    This is the primary GATE test for the analyze flow - verifies:
    - Repository analysis produces credible project_context.md proposal
    - PR is created with proposed context
    - Context file follows proper YAML frontmatter + markdown structure
    - Analysis notes and next steps included in generated content
    """
    # Setup git repository structure
    temp_project_root.mkdir(parents=True)
    git_dir = temp_project_root / ".git"
    git_dir.mkdir()
    
    # Create some example source files to analyze
    (temp_project_root / "app.py").write_text("""
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}
""")
    (temp_project_root / "requirements.txt").write_text("fastapi>=0.68.0\nuvicorn>=0.15.0")
    (temp_project_root / "README.md").write_text("# Test Project\nA FastAPI application for testing.")

    with patch("cli.init.RepoAnalyzer") as mock_analyzer_class, \
         patch("cli.init._create_context_pr") as mock_create_pr:
        
        # Setup analyzer mock
        mock_analyzer = AsyncMock()
        mock_analyzer_class.return_value = mock_analyzer
        
        # Mock the async method with AsyncMock
        mock_analyzer.analyze_repository = AsyncMock(return_value=mock_analysis_result)
        
        # Execute analyze flow
        await init_analyze(temp_project_root, github_token, mock_claude_client)
        
        # GATE REQUIREMENT: Verify .factory directory was created
        factory_dir = temp_project_root / ".factory"
        assert factory_dir.exists(), ".factory directory must be created during analyze"
        
        # GATE REQUIREMENT: Verify credible project_context.md proposal generated
        context_path = factory_dir / "project_context.md"
        assert context_path.exists(), "project_context.md must be created"
        
        content = context_path.read_text()
        
        # Verify proper YAML frontmatter structure
        assert content.startswith("---\n"), "Content must start with YAML frontmatter"
        assert "\n---\n" in content, "YAML frontmatter must be properly closed"
        
        # Extract and validate YAML content
        frontmatter_end = content.find("\n---\n", 3)
        yaml_content = content[4:frontmatter_end]  # Skip initial "---\n"
        parsed_yaml = yaml.safe_load(yaml_content)
        
        # Verify all required sections present
        required_sections = ["project", "stack", "deployment", "invariants", "reviewers"]
        for section in required_sections:
            assert section in parsed_yaml, f"Required section '{section}' missing from context"
        
        # Verify project section credibility
        project = parsed_yaml["project"]
        assert "name" in project and isinstance(project["name"], str)
        assert "description" in project and isinstance(project["description"], str)
        assert len(project["description"]) > 10, "Description should be meaningful"
        
        # Verify deployment section credibility
        deployment = parsed_yaml["deployment"]
        assert deployment["surface"] in ["mobile", "server", "cli", "embedded", "library"]
        assert isinstance(deployment["rollback_available"], bool)
        assert isinstance(deployment["forced_update"], bool)
        assert isinstance(deployment["user_data_recoverable"], bool)
        
        # Verify invariants section structure
        invariants = parsed_yaml["invariants"]
        assert isinstance(invariants, list)
        for invariant in invariants:
            assert "id" in invariant and isinstance(invariant["id"], str)
            assert "rule" in invariant and isinstance(invariant["rule"], str)
            assert "severity" in invariant
            assert invariant["severity"] in ["data_loss", "data_consistency", "irreversibility", "correctness", "performance"]
        
        # Verify markdown content includes analysis notes and next steps
        markdown_content = content[frontmatter_end + 5:]  # Skip "\n---\n"
        assert "Proposed Project Context" in markdown_content
        assert "Analysis Notes" in markdown_content
        assert "Next Steps" in markdown_content
        assert "harness init --finalize" in markdown_content
        
        # GATE REQUIREMENT: Verify PR creation was attempted
        mock_create_pr.assert_called_once()
        create_pr_args = mock_create_pr.call_args
        assert create_pr_args[0][0] == temp_project_root  # repo_path
        assert create_pr_args[0][1] == github_token  # github_token
        assert create_pr_args[0][2] == mock_analysis_result  # analysis_result


@pytest.mark.asyncio
async def test_analyze_e2e_context_proposal_credible(
    temp_project_root,
    github_token,
    mock_claude_client,
    mock_analysis_result
):
    """Test that analyze generates credible project_context.md proposal."""
    # Setup git repository with Python/FastAPI structure
    temp_project_root.mkdir(parents=True)
    git_dir = temp_project_root / ".git"
    git_dir.mkdir()
    
    # Create realistic project structure
    (temp_project_root / "pyproject.toml").write_text("""
[project]
name = "test-fastapi-app"
dependencies = ["fastapi", "uvicorn", "sqlalchemy"]
""")
    (temp_project_root / "app" / "main.py").parent.mkdir(exist_ok=True)
    (temp_project_root / "app" / "main.py").write_text("from fastapi import FastAPI")
    
    with patch("cli.init.RepoAnalyzer") as mock_analyzer_class, \
         patch("cli.init._create_context_pr"):
        
        # Setup analyzer mock
        mock_analyzer = AsyncMock()
        mock_analyzer_class.return_value = mock_analyzer
        mock_analyzer.analyze_repository = AsyncMock(return_value=mock_analysis_result)
        
        await init_analyze(temp_project_root, github_token, mock_claude_client)
        
        # Validate the proposed context is credible
        context_path = temp_project_root / ".factory" / "project_context.md"
        content = context_path.read_text()
        
        # Extract YAML content for validation
        frontmatter_end = content.find("\n---\n", 3)
        yaml_content = content[4:frontmatter_end]
        parsed_context = yaml.safe_load(yaml_content)
        
        # Verify stack detection is credible for FastAPI project
        stack = parsed_context["stack"]
        assert stack["language"] == "Python"
        assert "FastAPI" in stack["framework"]
        
        # Verify deployment surface is appropriate for server app
        assert parsed_context["deployment"]["surface"] == "server"
        
        # Verify invariants are meaningful for a web application
        invariants = parsed_context["invariants"]
        assert len(invariants) >= 1, "Should propose meaningful invariants"
        
        # Verify at least one invariant relates to web security
        auth_related = any("auth" in inv["rule"].lower() or "auth" in inv["id"].lower() for inv in invariants)
        input_related = any("input" in inv["rule"].lower() or "valid" in inv["rule"].lower() for inv in invariants)
        assert auth_related or input_related, "Should include security-related invariants for web apps"
        
        # Verify reviewers are enabled appropriately
        reviewers = parsed_context["reviewers"]
        assert reviewers["engineer"]["enabled"] is True
        assert reviewers["architect"]["enabled"] is True
        assert reviewers["sre"]["enabled"] is True
        # Deploy might be disabled for this test case


@pytest.mark.asyncio
async def test_analyze_e2e_pr_creation(
    temp_project_root,
    github_token,
    mock_claude_client,
    mock_analysis_result,
    mock_subprocess
):
    """Test analyze creates PR with proper title and context."""
    # Setup git repository
    temp_project_root.mkdir(parents=True)
    git_dir = temp_project_root / ".git"
    git_dir.mkdir()
    
    with patch("cli.init.RepoAnalyzer") as mock_analyzer_class, \
         patch("cli.init._create_github_pr") as mock_create_github_pr, \
         patch("subprocess.run") as mock_subprocess_run:
        
        # Setup subprocess mocks for git operations
        mock_subprocess_run.side_effect = [
            MagicMock(stdout="main", returncode=0),  # git branch --show-current
            MagicMock(returncode=0),  # git checkout -b
            MagicMock(returncode=0),  # git add
            MagicMock(returncode=0),  # git commit
            MagicMock(returncode=0),  # git push
            MagicMock(stdout="git@github.com:testowner/testrepo.git", returncode=0),  # git remote get-url
            MagicMock(returncode=0),  # git checkout main (cleanup)
        ]
        
        # Setup analyzer mock
        mock_analyzer = MagicMock()
        mock_analyzer_class.return_value = mock_analyzer
        mock_analyzer.analyze_repository = AsyncMock(return_value=mock_analysis_result)
        
        await init_analyze(temp_project_root, github_token, mock_claude_client)
        
        # Verify GitHub PR creation was attempted
        mock_create_github_pr.assert_called_once()
        
        # Verify PR creation arguments
        create_pr_args = mock_create_github_pr.call_args
        kwargs = create_pr_args.kwargs
        
        assert kwargs["repo_full_name"] == "testowner/testrepo"
        assert kwargs["base_branch"] == "main"
        assert kwargs["github_token"] == github_token
        # The analysis_result passed will be the actual result returned by analyzer mock
        assert hasattr(kwargs["analysis_result"], 'proposed_context')
        assert hasattr(kwargs["analysis_result"], 'confidence_score')
        assert hasattr(kwargs["analysis_result"], 'analysis_notes')
        
        # Verify branch name follows expected pattern
        head_branch = kwargs["head_branch"]
        assert head_branch.startswith("factory/proposed-context-")
        assert len(head_branch.split("-")) >= 3, "Branch name should include timestamp"


def test_analyze_e2e_finalize_after_merge(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token,
    mock_subprocess
):
    """Test finalize flow completion after PR merge simulation."""
    # Setup project with merged context (simulating PR merge)
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    
    # Create a realistic project_context.md (as if merged from analyze PR)
    context_content = """---
project:
  name: "testowner/finalize-test-project"
  description: "A project ready for finalization after context PR merge"

stack:
  language: "Python"
  framework: "FastAPI"
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
  - id: "input_validation"
    rule: "All user inputs must be validated"
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

This project context was created via analyze and is ready for finalization.
"""
    context_path = factory_dir / "project_context.md"
    context_path.write_text(context_content)
    
    # Mock all external dependencies for finalize flow
    with patch("cli.init.render_agents") as mock_render, \
         patch("cli.init.register_webhook_sync", return_value=99999) as mock_webhook, \
         patch("cli.init.httpx.Client") as mock_client_class:
        
        # Setup HTTP client mock for Stonehaven
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.return_value.status_code = 200
        
        # Execute finalize flow
        init_finalize(temp_project_root, mock_templates_dir, stonehaven_url, github_token)
        
        # Verify complete finalization occurred
        # 1. Agents directory created and rendered
        agents_dir = factory_dir / "agents"
        assert agents_dir.exists()
        mock_render.assert_called_once()
        
        # 2. Webhook registered
        mock_webhook.assert_called_once()
        webhook_args = mock_webhook.call_args
        assert webhook_args.kwargs["repo_owner"] == "testowner"  # From project name parsing
        assert webhook_args.kwargs["github_token"] == github_token
        
        # 3. Stonehaven registration completed
        mock_client.post.assert_called_once()
        
        # 4. All manifests created
        harness_toml = factory_dir / "harness.toml"
        assert harness_toml.exists()
        harness_content = harness_toml.read_text()
        assert 'project_name = "testowner/finalize-test-project"' in harness_content
        assert 'webhook_id = 99999' in harness_content
        
        webhook_config = factory_dir / "webhook_config.yml"
        assert webhook_config.exists()


@pytest.mark.asyncio
async def test_analyze_e2e_existing_factory_error(
    temp_project_root,
    github_token,
    mock_claude_client
):
    """Test analyze fails when .factory directory already exists."""
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
    assert "remove .factory/ to re-analyze" in str(exc_info.value)


@pytest.mark.asyncio
async def test_analyze_e2e_not_git_repo_error(
    temp_project_root,
    github_token,
    mock_claude_client
):
    """Test analyze fails when directory is not a git repository."""
    # Setup directory without .git
    temp_project_root.mkdir(parents=True)
    # Note: NOT creating .git directory
    
    with pytest.raises(InitError) as exc_info:
        await init_analyze(temp_project_root, github_token, mock_claude_client)
    
    assert "not a git repository" in str(exc_info.value)
    assert "no .git directory" in str(exc_info.value)


@pytest.mark.asyncio 
async def test_analyze_e2e_analysis_failure_cleanup(
    temp_project_root,
    github_token,
    mock_claude_client
):
    """Test analyze cleans up on analysis failure."""
    # Setup git repository
    temp_project_root.mkdir(parents=True)
    git_dir = temp_project_root / ".git"
    git_dir.mkdir()
    
    with patch("cli.init.RepoAnalyzer") as mock_analyzer_class:
        from interview.analyzer import AnalysisError
        
        # Setup analyzer to fail
        mock_analyzer = AsyncMock()
        mock_analyzer_class.return_value = mock_analyzer
        mock_analyzer.analyze_repository = AsyncMock(side_effect=AnalysisError("Analysis failed due to unreadable code"))
        
        with pytest.raises(InitError) as exc_info:
            await init_analyze(temp_project_root, github_token, mock_claude_client)
        
        assert "Repository analysis failed" in str(exc_info.value)
        assert "Analysis failed due to unreadable code" in str(exc_info.value)
        
        # GATE REQUIREMENT: Verify .factory directory was cleaned up on failure
        factory_dir = temp_project_root / ".factory"
        assert not factory_dir.exists(), ".factory directory should be removed on analysis failure"


@pytest.mark.asyncio
async def test_analyze_e2e_pr_creation_failure_cleanup(
    temp_project_root,
    github_token,
    mock_claude_client,
    mock_analysis_result
):
    """Test analyze cleans up on PR creation failure."""
    # Setup git repository
    temp_project_root.mkdir(parents=True)
    git_dir = temp_project_root / ".git"
    git_dir.mkdir()
    
    with patch("cli.init.RepoAnalyzer") as mock_analyzer_class, \
         patch("cli.init._create_context_pr", side_effect=Exception("PR creation failed")):
        
        # Setup analyzer mock to succeed but PR creation to fail
        mock_analyzer = MagicMock()
        mock_analyzer_class.return_value = mock_analyzer
        mock_analyzer.analyze_repository = AsyncMock(return_value=mock_analysis_result)
        
        with pytest.raises(InitError) as exc_info:
            await init_analyze(temp_project_root, github_token, mock_claude_client)
        
        assert "Failed to analyze repository" in str(exc_info.value)
        assert "PR creation failed" in str(exc_info.value)
        
        # Verify .factory directory was cleaned up on PR failure
        factory_dir = temp_project_root / ".factory"
        assert not factory_dir.exists(), ".factory directory should be removed on PR creation failure"


def test_finalize_missing_factory_dir_error(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token
):
    """Test finalize fails when .factory directory doesn't exist."""
    temp_project_root.mkdir(parents=True)
    # Note: NOT creating .factory directory
    
    with pytest.raises(InitError) as exc_info:
        init_finalize(temp_project_root, mock_templates_dir, stonehaven_url, github_token)
    
    assert ".factory directory not found" in str(exc_info.value)
    assert "Run init_analyze() first" in str(exc_info.value)


def test_finalize_missing_context_file_error(
    temp_project_root,
    mock_templates_dir,
    stonehaven_url,
    github_token
):
    """Test finalize fails when project_context.md doesn't exist."""
    temp_project_root.mkdir(parents=True)
    factory_dir = temp_project_root / ".factory"
    factory_dir.mkdir()
    # Note: NOT creating project_context.md
    
    with pytest.raises(InitError) as exc_info:
        init_finalize(temp_project_root, mock_templates_dir, stonehaven_url, github_token)
    
    assert "project_context.md not found" in str(exc_info.value)
    assert "context PR may not have been merged" in str(exc_info.value)
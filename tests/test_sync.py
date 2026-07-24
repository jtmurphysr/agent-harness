"""Tests for template synchronization functionality."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
import respx
import yaml

from cli.sync import SyncError, TemplateSyncer, TemplateUpdate
from stonehaven.registry import ProjectRegistry
from verdict_store.client import VerdictStoreClient


@pytest.fixture
def mock_registry():
    """Create a mock ProjectRegistry for testing."""
    mock_client = Mock(spec=VerdictStoreClient)
    return ProjectRegistry(mock_client)


@pytest.fixture
def templates_dir(tmp_path):
    """Create a temporary templates directory with test templates."""
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    
    # Create test template files
    engineer_template = templates_dir / "engineer.template.md"
    engineer_template.write_text("""---
version: "1.1.0"
propagation: opt_in
---

Engineer template content here.
""")
    
    architect_template = templates_dir / "architect.template.md" 
    architect_template.write_text("""---
version: "2.0.0"
propagation: auto
---

Architect template content here.
""")
    
    sre_template = templates_dir / "sre.template.md"
    sre_template.write_text("""---
version: "1.5.0"
propagation: security
---

SRE template content here.
""")
    
    return templates_dir


@pytest.fixture
def syncer(mock_registry, templates_dir):
    """Create a TemplateSyncer instance for testing."""
    return TemplateSyncer(mock_registry, templates_dir)


@pytest.mark.asyncio
async def test_sync_fleet_no_updates_needed(syncer):
    """Test sync_fleet when no updates are needed."""
    # Mock the methods that would normally interact with external services
    with patch.object(syncer, '_get_current_template_versions') as mock_current, \
         patch.object(syncer, '_list_fleet_projects') as mock_projects, \
         patch.object(syncer, '_get_project_template_lock') as mock_lock:
        
        mock_current.return_value = {
            "engineer.template.md": "1.1.0",
            "architect.template.md": "2.0.0",
            "sre.template.md": "1.5.0"
        }
        
        mock_projects.return_value = [
            {"repo": "owner/project1", "project_name": "Project One"},
            {"repo": "owner/project2", "project_name": "Project Two"}
        ]
        
        # Both projects have up-to-date templates
        mock_lock.return_value = {
            "engineer.template.md": "1.1.0",
            "architect.template.md": "2.0.0",
            "sre.template.md": "1.5.0"
        }
        
        result = await syncer.sync_fleet("test-token", dry_run=True)
        
        assert result == {
            "updated": [],
            "skipped": ["owner/project1", "owner/project2"]
        }


@pytest.mark.asyncio
async def test_sync_fleet_single_template_upgrade(syncer):
    """Test sync_fleet with a single template needing upgrade."""
    with patch.object(syncer, '_get_current_template_versions') as mock_current, \
         patch.object(syncer, '_list_fleet_projects') as mock_projects, \
         patch.object(syncer, '_get_project_template_lock') as mock_lock, \
         patch.object(syncer, '_create_template_upgrade_pr') as mock_create_pr:
        
        mock_current.return_value = {
            "engineer.template.md": "1.2.0",  # Updated
            "architect.template.md": "2.0.0",
            "sre.template.md": "1.5.0"
        }
        
        mock_projects.return_value = [
            {"repo": "owner/project1", "project_name": "Project One"}
        ]
        
        # Project has old engineer template
        mock_lock.return_value = {
            "engineer.template.md": "1.1.0",  # Old version
            "architect.template.md": "2.0.0",
            "sre.template.md": "1.5.0"
        }
        
        mock_create_pr.return_value = None
        
        result = await syncer.sync_fleet("test-token", dry_run=False)
        
        assert result == {
            "updated": ["owner/project1"],
            "skipped": []
        }
        
        # Verify PR creation was called
        mock_create_pr.assert_called_once()
        call_args = mock_create_pr.call_args
        assert call_args[0][0] == "owner/project1"  # repo
        updates = call_args[0][1]  # updates list
        assert len(updates) == 1
        assert updates[0].template_name == "engineer.template.md"
        assert updates[0].old_version == "1.1.0"
        assert updates[0].new_version == "1.2.0"


@pytest.mark.asyncio
async def test_sync_fleet_multiple_template_upgrades(syncer):
    """Test sync_fleet with multiple templates needing upgrades."""
    with patch.object(syncer, '_get_current_template_versions') as mock_current, \
         patch.object(syncer, '_list_fleet_projects') as mock_projects, \
         patch.object(syncer, '_get_project_template_lock') as mock_lock, \
         patch.object(syncer, '_create_template_upgrade_pr') as mock_create_pr:
        
        mock_current.return_value = {
            "engineer.template.md": "1.2.0",  # Updated
            "architect.template.md": "2.1.0",  # Updated
            "sre.template.md": "1.5.0"
        }
        
        mock_projects.return_value = [
            {"repo": "owner/project1", "project_name": "Project One"}
        ]
        
        # Project has old versions of engineer and architect
        mock_lock.return_value = {
            "engineer.template.md": "1.1.0",  # Old
            "architect.template.md": "2.0.0",  # Old
            "sre.template.md": "1.5.0"
        }
        
        mock_create_pr.return_value = None
        
        result = await syncer.sync_fleet("test-token", dry_run=False)
        
        assert result == {
            "updated": ["owner/project1"],
            "skipped": []
        }
        
        # Verify PR creation was called with multiple updates
        mock_create_pr.assert_called_once()
        call_args = mock_create_pr.call_args
        updates = call_args[0][1]  # updates list
        assert len(updates) == 2
        
        template_names = {u.template_name for u in updates}
        assert "engineer.template.md" in template_names
        assert "architect.template.md" in template_names


@pytest.mark.asyncio
async def test_sync_fleet_dry_run_mode(syncer):
    """Test sync_fleet in dry run mode."""
    with patch.object(syncer, '_get_current_template_versions') as mock_current, \
         patch.object(syncer, '_list_fleet_projects') as mock_projects, \
         patch.object(syncer, '_get_project_template_lock') as mock_lock, \
         patch.object(syncer, '_create_template_upgrade_pr') as mock_create_pr:
        
        mock_current.return_value = {
            "engineer.template.md": "1.2.0",
            "architect.template.md": "2.0.0",
            "sre.template.md": "1.5.0"
        }
        
        mock_projects.return_value = [
            {"repo": "owner/project1", "project_name": "Project One"}
        ]
        
        mock_lock.return_value = {
            "engineer.template.md": "1.1.0",  # Old version
            "architect.template.md": "2.0.0",
            "sre.template.md": "1.5.0"
        }
        
        result = await syncer.sync_fleet("test-token", dry_run=True)
        
        assert result == {
            "updated": ["owner/project1"],  # Would be updated
            "skipped": []
        }
        
        # Verify PR creation was NOT called in dry run mode
        mock_create_pr.assert_not_called()


@pytest.mark.asyncio
async def test_sync_fleet_pr_creation(syncer):
    """Test the full PR creation flow."""
    # This test uses respx to mock GitHub API calls
    with respx.mock:
        # Mock the GitHub API endpoints
        
        # 1. Get repository info
        respx.get("https://api.github.com/repos/owner/project1").mock(
            httpx.Response(200, json={
                "default_branch": "main"
            })
        )
        
        # 2. Get default branch ref
        respx.get("https://api.github.com/repos/owner/project1/git/refs/heads/main").mock(
            httpx.Response(200, json={
                "object": {"sha": "abc123"}
            })
        )
        
        # 3. Create new branch
        respx.post("https://api.github.com/repos/owner/project1/git/refs").mock(
            httpx.Response(201, json={
                "ref": "refs/heads/factory/template-upgrade-123456"
            })
        )
        
        # 4. Get current templates_lock.yml
        current_lock_content = yaml.safe_dump({
            "engineer.template.md": "1.1.0",
            "architect.template.md": "2.0.0"
        })
        import base64
        encoded_content = base64.b64encode(current_lock_content.encode()).decode()
        
        respx.get(
            "https://api.github.com/repos/owner/project1/contents/.factory/templates_lock.yml"
        ).mock(
            httpx.Response(200, json={
                "content": encoded_content,
                "sha": "def456"
            })
        )
        
        # 5. Update templates_lock.yml
        respx.put(
            "https://api.github.com/repos/owner/project1/contents/.factory/templates_lock.yml"
        ).mock(
            httpx.Response(200, json={})
        )
        
        # 6. Create pull request
        respx.post("https://api.github.com/repos/owner/project1/pulls").mock(
            httpx.Response(201, json={
                "number": 42,
                "html_url": "https://github.com/owner/project1/pull/42"
            })
        )
        
        # Create the update
        update = TemplateUpdate(
            template_name="engineer.template.md",
            old_version="1.1.0",
            new_version="1.2.0",
            repo="owner/project1",
            project_name="Project One"
        )
        
        # Test the PR creation
        await syncer._create_template_upgrade_pr(
            "owner/project1",
            [update],
            "test-token"
        )
        
        # Verify all expected API calls were made
        assert len(respx.calls) == 6


def test_get_current_template_versions(syncer, templates_dir):
    """Test extracting current template versions from files."""
    # This method is async but doesn't actually use async operations in the current implementation
    import asyncio
    
    async def run_test():
        versions = await syncer._get_current_template_versions()
        
        assert versions == {
            "engineer.template.md": "1.1.0",
            "architect.template.md": "2.0.0", 
            "sre.template.md": "1.5.0"
        }
    
    asyncio.run(run_test())


def test_find_template_updates(syncer):
    """Test finding which templates need updates."""
    project_lock = {
        "engineer.template.md": "1.0.0",  # Old
        "architect.template.md": "2.0.0",  # Current
        "sre.template.md": "1.4.0",  # Old
    }
    
    current_versions = {
        "engineer.template.md": "1.1.0",  # Newer
        "architect.template.md": "2.0.0",  # Same
        "sre.template.md": "1.5.0",  # Newer
    }
    
    updates = syncer._find_template_updates(
        project_lock,
        current_versions,
        "owner/repo",
        "Test Project"
    )
    
    assert len(updates) == 2
    
    # Check engineer update
    engineer_update = next(u for u in updates if u.template_name == "engineer.template.md")
    assert engineer_update.old_version == "1.0.0"
    assert engineer_update.new_version == "1.1.0"
    assert engineer_update.repo == "owner/repo"
    
    # Check SRE update
    sre_update = next(u for u in updates if u.template_name == "sre.template.md")
    assert sre_update.old_version == "1.4.0"
    assert sre_update.new_version == "1.5.0"


def test_create_upgrade_pr_body(syncer):
    """Test PR body creation for template upgrades."""
    updates = [
        TemplateUpdate(
            template_name="engineer.template.md",
            old_version="1.0.0",
            new_version="1.1.0",
            repo="owner/repo",
            project_name="Test Project"
        ),
        TemplateUpdate(
            template_name="sre.template.md",
            old_version="1.4.0",
            new_version="1.5.0",
            repo="owner/repo",
            project_name="Test Project"
        )
    ]
    
    body = syncer._create_upgrade_pr_body(updates)
    
    assert "Template Upgrade" in body
    assert "engineer.template.md" in body
    assert "v1.0.0" in body and "v1.1.0" in body
    assert "sre.template.md" in body  
    assert "v1.4.0" in body and "v1.5.0" in body
    assert "Claude Code" in body


def test_create_commit_message(syncer):
    """Test commit message creation for template updates."""
    # Single update
    single_update = [
        TemplateUpdate(
            template_name="engineer.template.md",
            old_version="1.0.0",
            new_version="1.1.0",
            repo="owner/repo",
            project_name="Test Project"
        )
    ]
    
    single_message = syncer._create_commit_message(single_update)
    assert "Update engineer.template.md from v1.0.0 to v1.1.0" == single_message
    
    # Multiple updates
    multiple_updates = [
        TemplateUpdate(
            template_name="engineer.template.md",
            old_version="1.0.0",
            new_version="1.1.0",
            repo="owner/repo",
            project_name="Test Project"
        ),
        TemplateUpdate(
            template_name="sre.template.md",
            old_version="1.4.0", 
            new_version="1.5.0",
            repo="owner/repo",
            project_name="Test Project"
        )
    ]
    
    multiple_message = syncer._create_commit_message(multiple_updates)
    assert "Update 2 templates:" in multiple_message
    assert "engineer.template.md" in multiple_message
    assert "sre.template.md" in multiple_message


@pytest.mark.asyncio
async def test_get_project_template_lock_success():
    """Test successfully fetching project template lock."""
    syncer = TemplateSyncer(Mock(), Path("/tmp"))
    
    lock_data = {
        "engineer.template.md": "1.0.0",
        "architect.template.md": "2.0.0"
    }
    lock_yaml = yaml.safe_dump(lock_data)
    
    with respx.mock:
        respx.get(
            "https://api.github.com/repos/owner/repo/contents/.factory/templates_lock.yml"
        ).mock(
            httpx.Response(200, text=lock_yaml)
        )
        
        result = await syncer._get_project_template_lock("owner/repo", "test-token")
        assert result == lock_data


@pytest.mark.asyncio
async def test_get_project_template_lock_not_found():
    """Test handling of missing template lock file."""
    syncer = TemplateSyncer(Mock(), Path("/tmp"))
    
    with respx.mock:
        respx.get(
            "https://api.github.com/repos/owner/repo/contents/.factory/templates_lock.yml"
        ).mock(
            httpx.Response(404)
        )
        
        result = await syncer._get_project_template_lock("owner/repo", "test-token")
        assert result == {}


@pytest.mark.asyncio
async def test_sync_fleet_handles_project_errors(syncer):
    """Test that sync_fleet continues when individual projects fail."""
    with patch.object(syncer, '_get_current_template_versions') as mock_current, \
         patch.object(syncer, '_list_fleet_projects') as mock_projects, \
         patch.object(syncer, '_get_project_template_lock') as mock_lock:
        
        mock_current.return_value = {"engineer.template.md": "1.1.0"}
        
        mock_projects.return_value = [
            {"repo": "owner/good-project", "project_name": "Good Project"},
            {"repo": "owner/bad-project", "project_name": "Bad Project"}
        ]
        
        # First call (good project) succeeds, second call (bad project) fails
        mock_lock.side_effect = [
            {"engineer.template.md": "1.1.0"},  # Good project - no updates needed
            Exception("Network error")  # Bad project - fails
        ]
        
        result = await syncer.sync_fleet("test-token", dry_run=True)
        
        # Good project should be in skipped (no updates needed)
        # Bad project should be in skipped (error occurred)
        assert "owner/good-project" in result["skipped"]
        assert "owner/bad-project" in result["skipped"]
        assert result["updated"] == []
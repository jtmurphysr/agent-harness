"""End-to-end template upgrade propagation tests.

This is a GATE issue - No reconcile/review path progress until these tests pass.
Tests the complete template upgrade propagation flow across the fleet,
including PR creation with version diffs and templates_lock.yml updates.

⚠️ WARNING: This is a GATE issue — No reconcile/review path progress until this passes
⚠️ WARNING: Test must verify PR creation with version diff
⚠️ WARNING: Test must verify templates_lock.yml updates
"""

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
import respx
import yaml

from cli.sync import SyncError, TemplateSyncer, TemplateUpdate
from stonehaven.registry import ProjectRegistry
from verdict_store.client import ProjectRecord, VerdictStoreClient


class TestTemplatePropagationE2E:
    """End-to-end template upgrade propagation tests."""

    @pytest.fixture
    def temp_templates_dir(self):
        """Create temporary templates directory with versioned templates."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            templates_dir = Path(tmp_dir) / "templates"
            templates_dir.mkdir()

            # Create template files with different versions
            engineer_template = templates_dir / "engineer.template.md"
            engineer_template.write_text("""---
version: "1.2.0"
propagation: opt_in
---

Updated engineer template content here.
""")

            architect_template = templates_dir / "architect.template.md"
            architect_template.write_text("""---
version: "2.1.0"
propagation: auto
---

Updated architect template content here.
""")

            sre_template = templates_dir / "sre.template.md"
            sre_template.write_text("""---
version: "1.6.0"
propagation: security
---

Updated SRE template content here.
""")

            yield templates_dir

    @pytest.fixture
    def mock_verdict_store_client(self):
        """Create mock verdict store client."""
        return Mock(spec=VerdictStoreClient)

    @pytest.fixture
    def mock_registry(self, mock_verdict_store_client):
        """Create mock registry with fleet projects."""
        registry = Mock(spec=ProjectRegistry)
        registry.client = mock_verdict_store_client

        # Mock project data
        test_projects = [
            ProjectRecord(
                id=1,
                stonehaven_id=str(uuid.uuid4()),
                repo="owner/project1",
                project_name="Project One",
                registered_at="2024-01-01T00:00:00Z",
                harness_version="0.1.0",
                active=True,
            ),
            ProjectRecord(
                id=2,
                stonehaven_id=str(uuid.uuid4()),
                repo="owner/project2",
                project_name="Project Two",
                registered_at="2024-01-01T00:00:00Z",
                harness_version="0.1.0",
                active=True,
            ),
        ]

        # Mock the list_projects method that would be called
        registry.list_projects.return_value = test_projects
        return registry

    @pytest.fixture
    def template_syncer(self, mock_registry, temp_templates_dir):
        """Create TemplateSyncer instance for testing."""
        return TemplateSyncer(mock_registry, temp_templates_dir)

    @pytest.mark.asyncio
    async def test_template_upgrade_propagation_e2e(self, template_syncer):
        """End-to-end test of template version upgrade across fleet."""
        with patch.object(template_syncer, '_list_fleet_projects') as mock_projects, \
             patch.object(template_syncer, '_get_project_template_lock') as mock_lock, \
             patch.object(template_syncer, '_create_template_upgrade_pr') as mock_create_pr:

            # Mock fleet projects
            mock_projects.return_value = [
                {"repo": "owner/project1", "project_name": "Project One"},
                {"repo": "owner/project2", "project_name": "Project Two"},
            ]

            # Mock project template locks with outdated versions
            def mock_lock_side_effect(repo, token):
                if repo == "owner/project1":
                    return {
                        "engineer.template.md": "1.1.0",  # Old version
                        "architect.template.md": "2.0.0",  # Old version
                        "sre.template.md": "1.6.0",  # Current version
                    }
                elif repo == "owner/project2":
                    return {
                        "engineer.template.md": "1.2.0",  # Current version
                        "architect.template.md": "2.0.0",  # Old version
                        "sre.template.md": "1.5.0",  # Old version
                    }
                return {}

            mock_lock.side_effect = mock_lock_side_effect
            mock_create_pr.return_value = None

            # Run the sync
            result = await template_syncer.sync_fleet("test-token", dry_run=False)

            # Verify both projects were updated
            assert sorted(result["updated"]) == ["owner/project1", "owner/project2"]
            assert result["skipped"] == []

            # Verify PR creation was called twice (once per project)
            assert mock_create_pr.call_count == 2

            # Verify the first project's updates
            project1_call = [call for call in mock_create_pr.call_args_list 
                             if call[0][0] == "owner/project1"][0]
            project1_updates = project1_call[0][1]
            assert len(project1_updates) == 2  # engineer and architect updates

            project1_template_names = {u.template_name for u in project1_updates}
            assert "engineer.template.md" in project1_template_names
            assert "architect.template.md" in project1_template_names

            # Verify the second project's updates
            project2_call = [call for call in mock_create_pr.call_args_list 
                             if call[0][0] == "owner/project2"][0]
            project2_updates = project2_call[0][1]
            assert len(project2_updates) == 2  # architect and sre updates

            project2_template_names = {u.template_name for u in project2_updates}
            assert "architect.template.md" in project2_template_names
            assert "sre.template.md" in project2_template_names

    @pytest.mark.asyncio
    async def test_template_upgrade_pr_content(self, template_syncer):
        """Test PR creation with correct title and body content."""
        # Create sample template updates
        updates = [
            TemplateUpdate(
                template_name="engineer.template.md",
                old_version="1.1.0",
                new_version="1.2.0",
                repo="owner/test-project",
                project_name="Test Project"
            ),
            TemplateUpdate(
                template_name="architect.template.md",
                old_version="2.0.0",
                new_version="2.1.0",
                repo="owner/test-project",
                project_name="Test Project"
            )
        ]

        # Mock GitHub API calls
        with respx.mock:
            # Mock repository info
            respx.get("https://api.github.com/repos/owner/test-project").mock(
                httpx.Response(200, json={"default_branch": "main"})
            )

            # Mock branch ref
            respx.get("https://api.github.com/repos/owner/test-project/git/refs/heads/main").mock(
                httpx.Response(200, json={"object": {"sha": "abc123"}})
            )

            # Mock branch creation
            respx.post("https://api.github.com/repos/owner/test-project/git/refs").mock(
                httpx.Response(201, json={})
            )

            # Mock lock file get
            current_lock = {
                "engineer.template.md": "1.1.0",
                "architect.template.md": "2.0.0"
            }
            lock_content = yaml.safe_dump(current_lock)
            import base64
            encoded_content = base64.b64encode(lock_content.encode()).decode()

            respx.get(
                "https://api.github.com/repos/owner/test-project/contents/.factory/templates_lock.yml"
            ).mock(
                httpx.Response(200, json={
                    "content": encoded_content,
                    "sha": "def456"
                })
            )

            # Mock lock file update
            respx.put(
                "https://api.github.com/repos/owner/test-project/contents/.factory/templates_lock.yml"
            ).mock(
                httpx.Response(200, json={})
            )

            # Mock PR creation with verification
            def verify_pr_payload(request):
                payload = json.loads(request.content)
                
                # Verify title contains version diff
                expected_title = "factory: template upgrade — 2 templates updated"
                assert payload["title"] == expected_title

                # Verify body contains version changes
                body = payload["body"]
                assert "engineer.template.md" in body
                assert "v1.1.0" in body and "v1.2.0" in body
                assert "architect.template.md" in body
                assert "v2.0.0" in body and "v2.1.0" in body
                assert "Claude Code" in body

                # Verify base and head branches
                assert payload["base"] == "main"
                assert payload["head"].startswith("factory/template-upgrade-")

                return httpx.Response(201, json={
                    "number": 42,
                    "html_url": "https://github.com/owner/test-project/pull/42"
                })

            respx.post("https://api.github.com/repos/owner/test-project/pulls").mock(
                side_effect=verify_pr_payload
            )

            # Execute PR creation
            await template_syncer._create_template_upgrade_pr(
                "owner/test-project", updates, "test-token"
            )

            # Verify all expected calls were made
            assert len(respx.calls) == 6

    @pytest.mark.asyncio
    async def test_template_upgrade_lock_file_updates(self, template_syncer):
        """Test that templates_lock.yml is correctly updated with new versions."""
        updates = [
            TemplateUpdate(
                template_name="engineer.template.md",
                old_version="1.1.0",
                new_version="1.2.0",
                repo="owner/test-project",
                project_name="Test Project"
            )
        ]

        # Mock GitHub API calls
        with respx.mock:
            # Setup basic mocks
            respx.get("https://api.github.com/repos/owner/test-project").mock(
                httpx.Response(200, json={"default_branch": "main"})
            )
            respx.get("https://api.github.com/repos/owner/test-project/git/refs/heads/main").mock(
                httpx.Response(200, json={"object": {"sha": "abc123"}})
            )
            respx.post("https://api.github.com/repos/owner/test-project/git/refs").mock(
                httpx.Response(201, json={})
            )

            # Mock current lock file content
            original_lock = {
                "engineer.template.md": "1.1.0",
                "architect.template.md": "2.0.0",
                "sre.template.md": "1.5.0"
            }
            lock_content = yaml.safe_dump(original_lock, default_flow_style=False, sort_keys=True)
            import base64
            encoded_content = base64.b64encode(lock_content.encode()).decode()

            respx.get(
                "https://api.github.com/repos/owner/test-project/contents/.factory/templates_lock.yml"
            ).mock(
                httpx.Response(200, json={
                    "content": encoded_content,
                    "sha": "def456"
                })
            )

            # Mock lock file update with verification
            def verify_lock_update(request):
                payload = json.loads(request.content)
                
                # Decode and verify the updated content
                new_content = base64.b64decode(payload["content"]).decode("utf-8")
                updated_lock = yaml.safe_load(new_content)
                
                # Verify that only the engineer template was updated
                expected_lock = {
                    "architect.template.md": "2.0.0",
                    "engineer.template.md": "1.2.0",  # Updated
                    "sre.template.md": "1.5.0"
                }
                assert updated_lock == expected_lock
                
                # Verify commit message
                assert "Update template versions" in payload["message"]
                assert "engineer.template.md from v1.1.0 to v1.2.0" in payload["message"]

                return httpx.Response(200, json={})

            respx.put(
                "https://api.github.com/repos/owner/test-project/contents/.factory/templates_lock.yml"
            ).mock(side_effect=verify_lock_update)

            # Mock PR creation
            respx.post("https://api.github.com/repos/owner/test-project/pulls").mock(
                httpx.Response(201, json={"number": 42})
            )

            # Execute PR creation
            await template_syncer._create_template_upgrade_pr(
                "owner/test-project", updates, "test-token"
            )

    @pytest.mark.asyncio
    async def test_template_upgrade_fleet_wide(self, template_syncer):
        """Test template upgrades across multiple projects in the fleet."""
        with patch.object(template_syncer, '_list_fleet_projects') as mock_projects, \
             patch.object(template_syncer, '_get_project_template_lock') as mock_lock, \
             patch.object(template_syncer, '_create_template_upgrade_pr') as mock_create_pr:

            # Mock a large fleet of projects
            mock_projects.return_value = [
                {"repo": f"owner/project{i}", "project_name": f"Project {i}"}
                for i in range(1, 6)  # 5 projects
            ]

            # Mock varied template states across projects
            def mock_lock_side_effect(repo, token):
                if "project1" in repo or "project2" in repo:
                    return {
                        "engineer.template.md": "1.1.0",  # Old
                        "architect.template.md": "2.1.0",  # Current
                        "sre.template.md": "1.6.0",  # Current
                    }
                elif "project3" in repo:
                    return {
                        "engineer.template.md": "1.2.0",  # Current
                        "architect.template.md": "2.0.0",  # Old
                        "sre.template.md": "1.5.0",  # Old
                    }
                elif "project4" in repo:
                    return {
                        "engineer.template.md": "1.2.0",  # Current
                        "architect.template.md": "2.1.0",  # Current
                        "sre.template.md": "1.6.0",  # Current
                    }
                else:  # project5 - missing lock file (new project)
                    return {}

            mock_lock.side_effect = mock_lock_side_effect
            mock_create_pr.return_value = None

            # Run fleet sync
            result = await template_syncer.sync_fleet("test-token", dry_run=False)

            # Verify correct projects were updated
            expected_updated = ["owner/project1", "owner/project2", "owner/project3"]
            assert sorted(result["updated"]) == sorted(expected_updated)
            
            # Project4 has current versions, project5 has no lock file (both skipped)
            expected_skipped = ["owner/project4", "owner/project5"]
            assert sorted(result["skipped"]) == sorted(expected_skipped)

            # Verify PR creation was called for updated projects only
            assert mock_create_pr.call_count == 3

            # Verify each project gets the right updates
            pr_calls_by_repo = {
                call[0][0]: call[0][1] for call in mock_create_pr.call_args_list
            }

            # Project1 and project2 should get engineer update
            for repo in ["owner/project1", "owner/project2"]:
                updates = pr_calls_by_repo[repo]
                assert len(updates) == 1
                assert updates[0].template_name == "engineer.template.md"
                assert updates[0].old_version == "1.1.0"
                assert updates[0].new_version == "1.2.0"

            # Project3 should get architect and sre updates
            project3_updates = pr_calls_by_repo["owner/project3"]
            assert len(project3_updates) == 2
            template_names = {u.template_name for u in project3_updates}
            assert "architect.template.md" in template_names
            assert "sre.template.md" in template_names

    @pytest.mark.asyncio
    async def test_template_upgrade_dry_run_mode(self, template_syncer):
        """Test template upgrade in dry run mode - no PRs created."""
        with patch.object(template_syncer, '_list_fleet_projects') as mock_projects, \
             patch.object(template_syncer, '_get_project_template_lock') as mock_lock, \
             patch.object(template_syncer, '_create_template_upgrade_pr') as mock_create_pr:

            mock_projects.return_value = [
                {"repo": "owner/project1", "project_name": "Project One"}
            ]

            mock_lock.return_value = {
                "engineer.template.md": "1.1.0",  # Old version
                "architect.template.md": "2.1.0",  # Current
                "sre.template.md": "1.6.0",  # Current
            }

            # Run in dry run mode
            result = await template_syncer.sync_fleet("test-token", dry_run=True)

            # Should report what would be updated
            assert result["updated"] == ["owner/project1"]
            assert result["skipped"] == []

            # But no PRs should actually be created
            mock_create_pr.assert_not_called()

    @pytest.mark.asyncio
    async def test_template_upgrade_handles_errors_gracefully(self, template_syncer):
        """Test that template upgrade handles individual project errors gracefully."""
        with patch.object(template_syncer, '_list_fleet_projects') as mock_projects, \
             patch.object(template_syncer, '_get_project_template_lock') as mock_lock, \
             patch.object(template_syncer, '_create_template_upgrade_pr') as mock_create_pr:

            mock_projects.return_value = [
                {"repo": "owner/good-project", "project_name": "Good Project"},
                {"repo": "owner/bad-project", "project_name": "Bad Project"},
                {"repo": "owner/another-good-project", "project_name": "Another Good Project"},
            ]

            # Mock lock retrieval - one project fails
            def mock_lock_side_effect(repo, token):
                if repo == "owner/bad-project":
                    raise Exception("Network error fetching lock file")
                return {
                    "engineer.template.md": "1.1.0",  # Old version
                }

            mock_lock.side_effect = mock_lock_side_effect

            # Mock PR creation - one succeeds, one fails
            def mock_pr_side_effect(repo, updates, token):
                if repo == "owner/another-good-project":
                    raise Exception("GitHub API error creating PR")
                return None

            mock_create_pr.side_effect = mock_pr_side_effect

            # Run sync - should not fail entirely
            result = await template_syncer.sync_fleet("test-token", dry_run=False)

            # Good project should be updated, others skipped due to errors
            assert result["updated"] == ["owner/good-project"]
            assert sorted(result["skipped"]) == [
                "owner/another-good-project",  # PR creation failed
                "owner/bad-project"  # Lock retrieval failed
            ]

    @pytest.mark.asyncio
    async def test_template_upgrade_error_handling(self, template_syncer):
        """Test proper error handling and reporting in template upgrade."""
        with patch.object(template_syncer, '_get_current_template_versions') as mock_versions:
            # Test sync failure when getting current versions fails
            mock_versions.side_effect = Exception("Template parsing error")

            with pytest.raises(SyncError) as exc_info:
                await template_syncer.sync_fleet("test-token")

            assert "Fleet sync failed" in str(exc_info.value)
            assert "Template parsing error" in str(exc_info.value)
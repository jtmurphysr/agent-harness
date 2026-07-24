"""Template upgrade propagation.

Compares templates_lock.yml against current template versions and creates
pull requests for template upgrades across the fleet. This is the self-healing
loop that ensures template improvements reach all managed projects.

⚠️ WARNING: Template version drift across fleet — This mechanism is load-bearing infrastructure
⚠️ WARNING: Compares templates_lock.yml against current template versions
⚠️ WARNING: Opens PR titled 'factory: template upgrade — {template} v{old} → v{new}'
"""

from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel

from renderer.compose import _extract_template_version
from stonehaven.registry import ProjectRegistry

__all__ = ["SyncError", "TemplateSyncer"]


class SyncError(Exception):
    """Raised when template sync fails."""


class TemplateUpdate(BaseModel):
    """Represents a single template update to be applied."""

    template_name: str
    old_version: str
    new_version: str
    repo: str
    project_name: str


class TemplateSyncer:
    """Fleet template synchronization service.

    Compares template lockfiles across the fleet against current template versions
    and opens PRs to propagate template upgrades.
    """

    def __init__(self, registry: ProjectRegistry, templates_dir: Path) -> None:
        """Initialize the template syncer.

        Args:
            registry: ProjectRegistry instance for fleet management
            templates_dir: Path to directory containing current template files
        """
        self.registry = registry
        self.templates_dir = templates_dir

    async def sync_fleet(self, github_token: str, dry_run: bool = False) -> dict[str, list[str]]:
        """Synchronize template versions across the fleet.

        Compares templates_lock.yml in each project against current template versions,
        and creates pull requests for any that are out of date.

        Args:
            github_token: GitHub Personal Access Token for PR creation
            dry_run: If True, report what would be updated without making changes

        Returns:
            Dict with 'updated' and 'skipped' lists of repo names

        Raises:
            SyncError: If sync operation fails
        """
        try:
            # Get current template versions
            current_versions = await self._get_current_template_versions()

            # Get all registered projects
            projects = await self._list_fleet_projects()

            updates_needed = []
            skipped_repos = []

            for project in projects:
                try:
                    # Get project's current template lock
                    project_lock = await self._get_project_template_lock(
                        project["repo"], github_token
                    )

                    # Find templates that need updates
                    project_updates = self._find_template_updates(
                        project_lock, current_versions, project["repo"], project["project_name"]
                    )

                    if project_updates:
                        updates_needed.extend(project_updates)
                    else:
                        skipped_repos.append(project["repo"])

                except Exception:
                    # Skip project if we can't check its templates, but don't fail entire sync
                    skipped_repos.append(project["repo"])
                    continue

            updated_repos = []

            if not dry_run and updates_needed:
                # Group updates by repository
                updates_by_repo: dict[str, list[TemplateUpdate]] = {}
                for update in updates_needed:
                    if update.repo not in updates_by_repo:
                        updates_by_repo[update.repo] = []
                    updates_by_repo[update.repo].append(update)

                # Create PRs for each repository that needs updates
                for repo, repo_updates in updates_by_repo.items():
                    try:
                        await self._create_template_upgrade_pr(repo, repo_updates, github_token)
                        updated_repos.append(repo)
                    except Exception:
                        # Continue with other repositories if one fails
                        skipped_repos.append(repo)
                        continue
            elif dry_run:
                # In dry run mode, just report what would be updated
                updated_repos = list({update.repo for update in updates_needed})

            return {"updated": updated_repos, "skipped": skipped_repos}

        except Exception as e:
            raise SyncError(f"Fleet sync failed: {e}") from e

    async def _get_current_template_versions(self) -> dict[str, str]:
        """Get current versions of all template files.

        Returns:
            Dict mapping template filenames to their versions
        """
        versions = {}

        template_files = list(self.templates_dir.glob("*.template.md"))

        for template_file in template_files:
            try:
                content = template_file.read_text(encoding="utf-8")
                version = _extract_template_version(content)
                versions[template_file.name] = version
            except Exception:
                # Skip templates that can't be parsed, but don't fail entirely
                continue

        return versions

    async def _list_fleet_projects(self) -> list[dict[str, str]]:
        """List all projects in the fleet.

        Returns:
            List of project records with 'repo' and 'project_name' keys
        """
        # Note: ProjectRegistry.list_projects is not implemented yet
        # For now, we'll need to implement a workaround or stub this
        # The actual implementation would call self.registry.list_projects()
        raise NotImplementedError(
            "Fleet project listing requires ProjectRegistry.list_projects() implementation"
        )

    async def _get_project_template_lock(self, repo: str, github_token: str) -> dict[str, str]:
        """Get templates_lock.yml content from a project repository.

        Args:
            repo: Repository name in 'owner/name' format
            github_token: GitHub Personal Access Token

        Returns:
            Dict mapping template names to versions from the lockfile
        """
        async with httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3.raw",
                "User-Agent": "agent-harness/1.0",
            },
            timeout=30.0,
        ) as client:
            # Try to get templates_lock.yml from .factory directory
            lock_url = f"https://api.github.com/repos/{repo}/contents/.factory/templates_lock.yml"

            try:
                response = await client.get(lock_url)

                if response.status_code == 200:
                    # Parse YAML content
                    lock_content = response.text
                    lock_data = yaml.safe_load(lock_content)
                    return lock_data or {}
                elif response.status_code == 404:
                    # No templates_lock.yml file - project may not be fully initialized
                    return {}
                else:
                    raise SyncError(
                        f"Failed to fetch templates_lock.yml from {repo}: {response.status_code}"
                    )

            except httpx.RequestError as e:
                raise SyncError(
                    f"Network error fetching templates_lock.yml from {repo}: {e}"
                ) from e

    def _find_template_updates(
        self,
        project_lock: dict[str, str],
        current_versions: dict[str, str],
        repo: str,
        project_name: str,
    ) -> list[TemplateUpdate]:
        """Find templates that need updates for a project.

        Args:
            project_lock: Project's current template versions
            current_versions: Current template versions available
            repo: Repository name
            project_name: Human-readable project name

        Returns:
            List of TemplateUpdate objects for templates that need updating
        """
        updates = []

        for template_name, current_version in current_versions.items():
            locked_version = project_lock.get(template_name)

            if locked_version is None:
                # Template not in lock file - project may not use this template
                continue

            if locked_version != current_version:
                updates.append(
                    TemplateUpdate(
                        template_name=template_name,
                        old_version=locked_version,
                        new_version=current_version,
                        repo=repo,
                        project_name=project_name,
                    )
                )

        return updates

    async def _create_template_upgrade_pr(
        self, repo: str, updates: list[TemplateUpdate], github_token: str
    ) -> None:
        """Create a pull request for template upgrades.

        Args:
            repo: Repository name in 'owner/name' format
            updates: List of template updates to include in the PR
            github_token: GitHub Personal Access Token for PR creation
        """
        # Create PR title based on updates
        if len(updates) == 1:
            update = updates[0]
            pr_title = f"factory: template upgrade — {update.template_name} v{update.old_version} → v{update.new_version}"
        else:
            pr_title = f"factory: template upgrade — {len(updates)} templates updated"

        # Create PR body with details
        pr_body = self._create_upgrade_pr_body(updates)

        # Create the PR using GitHub API
        async with httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "agent-harness/1.0",
            },
            timeout=30.0,
        ) as client:
            # First, create a branch for the updates
            branch_name = f"factory/template-upgrade-{hash(tuple(sorted(u.template_name for u in updates))) & 0xFFFFFF:06x}"

            try:
                # Get the default branch SHA
                repo_url = f"https://api.github.com/repos/{repo}"
                repo_response = await client.get(repo_url)
                repo_response.raise_for_status()
                repo_data = repo_response.json()
                default_branch = repo_data["default_branch"]

                # Get the default branch ref
                ref_url = f"https://api.github.com/repos/{repo}/git/refs/heads/{default_branch}"
                ref_response = await client.get(ref_url)
                ref_response.raise_for_status()
                ref_data = ref_response.json()
                base_sha = ref_data["object"]["sha"]

                # Create new branch
                create_ref_url = f"https://api.github.com/repos/{repo}/git/refs"
                create_ref_payload = {"ref": f"refs/heads/{branch_name}", "sha": base_sha}
                create_ref_response = await client.post(create_ref_url, json=create_ref_payload)
                create_ref_response.raise_for_status()

                # Update templates_lock.yml on the new branch
                await self._update_templates_lock_on_branch(client, repo, branch_name, updates)

                # Create the pull request
                pr_url = f"https://api.github.com/repos/{repo}/pulls"
                pr_payload = {
                    "title": pr_title,
                    "body": pr_body,
                    "head": branch_name,
                    "base": default_branch,
                }

                pr_response = await client.post(pr_url, json=pr_payload)
                pr_response.raise_for_status()

            except httpx.HTTPStatusError as e:
                raise SyncError(
                    f"GitHub API error creating PR for {repo}: {e.response.status_code} {e.response.text}"
                ) from e
            except httpx.RequestError as e:
                raise SyncError(f"Network error creating PR for {repo}: {e}") from e

    async def _update_templates_lock_on_branch(
        self, client: httpx.AsyncClient, repo: str, branch_name: str, updates: list[TemplateUpdate]
    ) -> None:
        """Update templates_lock.yml file on a branch with new versions.

        Args:
            client: HTTP client with GitHub authentication
            repo: Repository name in 'owner/name' format
            branch_name: Branch to update
            updates: List of template updates to apply
        """
        # Get current templates_lock.yml content
        lock_url = f"https://api.github.com/repos/{repo}/contents/.factory/templates_lock.yml"

        try:
            # Get the current file content and SHA
            get_response = await client.get(lock_url, params={"ref": branch_name})
            get_response.raise_for_status()
            file_data = get_response.json()

            # Decode the current content
            import base64

            current_content = base64.b64decode(file_data["content"]).decode("utf-8")
            current_lock = yaml.safe_load(current_content) or {}

            # Apply updates
            for update in updates:
                current_lock[update.template_name] = update.new_version

            # Generate new content
            new_content = yaml.safe_dump(current_lock, default_flow_style=False, sort_keys=True)

            # Update the file
            update_payload = {
                "message": f"Update template versions\n\n{self._create_commit_message(updates)}",
                "content": base64.b64encode(new_content.encode("utf-8")).decode("utf-8"),
                "sha": file_data["sha"],
                "branch": branch_name,
            }

            put_response = await client.put(lock_url, json=update_payload)
            put_response.raise_for_status()

        except httpx.HTTPStatusError as e:
            raise SyncError(
                f"Failed to update templates_lock.yml for {repo}: {e.response.status_code}"
            ) from e

    def _create_upgrade_pr_body(self, updates: list[TemplateUpdate]) -> str:
        """Create PR body text for template upgrades.

        Args:
            updates: List of template updates

        Returns:
            Formatted PR body as string
        """
        body_parts = [
            "## Template Upgrade",
            "",
            "This PR updates the following template versions:",
            "",
        ]

        for update in updates:
            body_parts.append(
                f"- **{update.template_name}**: `v{update.old_version}` → `v{update.new_version}`"
            )

        body_parts.extend(
            [
                "",
                "## Changes",
                "",
                "- Updated `.factory/templates_lock.yml` with new template versions",
                "- Agent files will be re-rendered on next `harness render`",
                "",
                "## Verification",
                "",
                "- [ ] Review template changes in harness repository",
                "- [ ] Run `harness render` locally to verify agent updates",
                "- [ ] Test that updated agents work as expected",
                "",
                "---",
                "",
                "🤖 Generated with [Claude Code](https://claude.ai/code)",
                "",
                "Co-Authored-By: Claude <noreply@anthropic.com>",
            ]
        )

        return "\n".join(body_parts)

    def _create_commit_message(self, updates: list[TemplateUpdate]) -> str:
        """Create commit message for template updates.

        Args:
            updates: List of template updates

        Returns:
            Formatted commit message
        """
        if len(updates) == 1:
            update = updates[0]
            return (
                f"Update {update.template_name} from v{update.old_version} to v{update.new_version}"
            )
        else:
            template_names = [update.template_name for update in updates]
            return f"Update {len(updates)} templates: {', '.join(template_names)}"

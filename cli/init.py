"""Harness initialization for greenfield projects.

Reads existing project_context.md and renders agent files.
This module handles the greenfield path only - expects project_context.md to exist.
Interview logic is handled by the prd-generator skill (external).
"""

import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from cli.render import render_agents
from github.webhook import register_webhook_sync
from interview.analyzer import AnalysisError, RepoAnalyzer
from renderer.validators import ProjectContextError, validate_project_context

__all__ = ["InitError", "init_analyze", "init_finalize", "init_greenfield"]


class InitError(Exception):
    """Raised when harness initialization fails."""


def init_greenfield(
    project_root: Path,
    templates_dir: Path,
    stonehaven_url: str,
    github_token: str,
) -> None:
    """Complete greenfield initialization with webhook registration.

    Creates .factory/agents/ directory structure, renders agent files,
    registers with Stonehaven, and configures GitHub webhook.
    Idempotent - safe to run multiple times.

    Args:
        project_root: Path to project root directory
        templates_dir: Path to directory containing template files
        stonehaven_url: URL of the Stonehaven listener
        github_token: GitHub Personal Access Token with webhooks:write scope

    Raises:
        InitError: If initialization fails
    """
    # Define key paths
    factory_dir = project_root / ".factory"
    agents_dir = factory_dir / "agents"
    project_context_path = factory_dir / "project_context.md"
    webhook_config_path = factory_dir / "webhook_config.yml"
    harness_toml_path = factory_dir / "harness.toml"

    # Validate prerequisites
    if not project_context_path.exists():
        raise InitError(
            f"project_context.md not found at {project_context_path}. "
            "For greenfield projects, run the prd-generator skill first to create this file."
        )

    # Validate project context file
    try:
        project_context = validate_project_context(project_context_path)
    except ProjectContextError as e:
        raise InitError(f"Invalid project_context.md: {e}") from e

    # Create .factory directory structure (idempotent)
    factory_dir.mkdir(exist_ok=True)
    agents_dir.mkdir(exist_ok=True)

    # Render agent files
    try:
        render_agents(
            project_context_path=project_context_path,
            templates_dir=templates_dir,
            output_dir=agents_dir,
            update_lock=True,
        )
    except Exception as e:
        raise InitError(f"Failed to render agent files: {e}") from e

    # Generate stonehaven ID for this project (idempotent)
    stonehaven_id = _get_or_generate_stonehaven_id(harness_toml_path)

    # Extract repository information from project context
    repo_info = _extract_repo_info(project_root, project_context)

    # Generate webhook secret (idempotent)
    webhook_secret = _get_or_generate_webhook_secret(webhook_config_path)

    # Register with Stonehaven
    try:
        _register_with_stonehaven(
            stonehaven_url=stonehaven_url,
            stonehaven_id=stonehaven_id,
            repo=repo_info["full_name"],
            project_name=project_context["project"]["name"],
        )
    except Exception as e:
        raise InitError(f"Failed to register with Stonehaven: {e}") from e

    # Register GitHub webhook
    webhook_url = f"{stonehaven_url.rstrip('/')}/webhooks/{stonehaven_id}"
    try:
        webhook_id = register_webhook_sync(
            repo_owner=repo_info["owner"],
            repo_name=repo_info["name"],
            webhook_url=webhook_url,
            secret=webhook_secret,
            github_token=github_token,
        )
    except Exception as e:
        raise InitError(f"Failed to register GitHub webhook: {e}") from e

    # Create configuration files
    _create_webhook_config(webhook_config_path, stonehaven_id, webhook_secret, webhook_url)
    _create_harness_toml(
        harness_toml_path,
        stonehaven_id=stonehaven_id,
        project_name=project_context["project"]["name"],
        repo=repo_info["full_name"],
        webhook_id=webhook_id,
    )


def _get_or_generate_stonehaven_id(harness_toml_path: Path) -> str:
    """Get existing stonehaven ID or generate new one.

    Args:
        harness_toml_path: Path to harness.toml file

    Returns:
        Stonehaven ID (UUID4 string)
    """
    if harness_toml_path.exists():
        try:
            with harness_toml_path.open() as f:
                # Simple YAML parser for TOML-like format
                content = f.read()
                for line in content.split("\n"):
                    if line.strip().startswith("stonehaven_id = "):
                        stonehaven_id = line.split("=", 1)[1].strip().strip("\"'")
                        # Validate it's a proper UUID
                        uuid.UUID(stonehaven_id, version=4)
                        return stonehaven_id
        except Exception:
            # If parsing fails, generate new ID
            pass

    # Generate new UUID4
    return str(uuid.uuid4())


def _get_or_generate_webhook_secret(webhook_config_path: Path) -> str:
    """Get existing webhook secret or generate new one.

    Args:
        webhook_config_path: Path to webhook_config.yml file

    Returns:
        Webhook secret for HMAC verification
    """
    if webhook_config_path.exists():
        try:
            with webhook_config_path.open() as f:
                config = yaml.safe_load(f)
                if config and isinstance(config, dict):
                    secret = config.get("secret")
                    if isinstance(secret, str):
                        return secret
        except Exception:
            # If parsing fails, generate new secret
            pass

    # Generate new secret (32 bytes, hex encoded)
    return secrets.token_hex(32)


def _extract_repo_info(project_root: Path, project_context: dict[str, Any]) -> dict[str, str]:
    """Extract repository information from git or project context.

    Args:
        project_root: Path to project root directory
        project_context: Parsed project_context.md data

    Returns:
        Dictionary with 'owner', 'name', and 'full_name' keys

    Raises:
        InitError: If repository information cannot be determined
    """
    # Try to get from git remote origin first
    try:
        import subprocess

        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )

        remote_url = result.stdout.strip()

        # Parse GitHub URL (both HTTPS and SSH formats)
        if "github.com" in remote_url:
            if remote_url.startswith("git@github.com:"):
                # SSH format: git@github.com:owner/repo.git
                repo_part = remote_url.split(":", 1)[1]
            elif "github.com/" in remote_url:
                # HTTPS format: https://github.com/owner/repo.git
                repo_part = remote_url.split("github.com/", 1)[1]
            else:
                raise ValueError("Unrecognized GitHub URL format")

            # Remove .git suffix if present
            if repo_part.endswith(".git"):
                repo_part = repo_part[:-4]

            if "/" in repo_part:
                owner, name = repo_part.split("/", 1)
                return {
                    "owner": owner,
                    "name": name,
                    "full_name": f"{owner}/{name}",
                }
    except Exception:
        # Git command failed or URL parsing failed, continue to fallback
        pass

    # Fallback: try to infer from project context or directory name
    project_name = project_context.get("project", {}).get("name", "")
    if "/" in project_name:
        # Project name might be in "owner/repo" format
        owner, name = project_name.split("/", 1)
        return {
            "owner": owner,
            "name": name,
            "full_name": f"{owner}/{name}",
        }

    # Final fallback: use directory name with a placeholder owner
    dir_name = project_root.name
    raise InitError(
        f"Cannot determine repository owner/name. Ensure git remote 'origin' is set "
        f"to a GitHub repository, or set project.name in project_context.md to 'owner/repo' format. "
        f"Current directory: {dir_name}, project.name: {project_name}"
    )


def _register_with_stonehaven(
    stonehaven_url: str, stonehaven_id: str, repo: str, project_name: str
) -> None:
    """Register project with Stonehaven listener.

    Args:
        stonehaven_url: Base URL of Stonehaven listener
        stonehaven_id: UUID4 identifier for this project
        repo: Repository name in owner/name format
        project_name: Human-readable project name

    Raises:
        InitError: If registration fails
    """
    admin_url = f"{stonehaven_url.rstrip('/')}/api/v1/projects/register"

    registration_request = {
        "stonehaven_id": stonehaven_id,
        "repo": repo,
        "project_name": project_name,
    }

    headers = {
        "Authorization": "Bearer admin-token",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                admin_url,
                json=registration_request,
                headers=headers,
            )

            if response.status_code == 409:
                # Already registered - this is fine for idempotency
                return
            elif response.status_code == 200:
                # Successfully registered
                return
            else:
                # Some other error
                error_detail = "Unknown error"
                try:
                    error_data = response.json()
                    error_detail = error_data.get("detail", str(response.status_code))
                except Exception:
                    error_detail = f"{response.status_code} {response.reason_phrase}"

                raise InitError(f"Stonehaven registration failed: {error_detail}")

    except httpx.RequestError as e:
        raise InitError(f"Failed to connect to Stonehaven at {admin_url}: {e}") from e


def _create_webhook_config(
    webhook_config_path: Path, stonehaven_id: str, secret: str, url: str
) -> None:
    """Create webhook configuration file.

    Args:
        webhook_config_path: Path to webhook_config.yml file
        stonehaven_id: UUID4 identifier for this project
        secret: HMAC secret for webhook verification
        url: Webhook URL that GitHub will POST to
    """
    config = {
        "stonehaven_id": stonehaven_id,
        "secret": secret,
        "url": url,
        "created_at": datetime.now(UTC).isoformat(),
    }

    with webhook_config_path.open("w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def _create_harness_toml(
    harness_toml_path: Path,
    stonehaven_id: str,
    project_name: str,
    repo: str,
    webhook_id: int,
) -> None:
    """Create harness.toml disaster recovery manifest.

    Args:
        harness_toml_path: Path to harness.toml file
        stonehaven_id: UUID4 identifier for this project
        project_name: Human-readable project name
        repo: Repository name in owner/name format
        webhook_id: GitHub webhook ID for tracking
    """
    now = datetime.now(UTC).isoformat()

    # Create TOML-like content manually (using simple string formatting)
    content = f'''# Harness disaster recovery manifest
# This file enables re-registration if Stonehaven data is lost
# Committed to repository for durability

stonehaven_id = "{stonehaven_id}"
project_name = "{project_name}"
repo = "{repo}"
webhook_id = {webhook_id}
harness_version = "0.1.0"
registered_at = "{now}"
'''

    with harness_toml_path.open("w") as f:
        f.write(content)


async def init_analyze(repo_path: Path, github_token: str, claude_client: Any) -> None:
    """Analyze existing repo and create proposed context PR.

    This function is used for existing repositories that don't have a .factory/ directory.
    It uses Claude Code to analyze the repository and create a proposed project_context.md
    via a GitHub PR for operator review.

    Args:
        repo_path: Path to the repository root
        github_token: GitHub Personal Access Token with PR creation permissions
        claude_client: Claude client instance for repo analysis

    Raises:
        InitError: If analysis fails or .factory/ directory already exists
    """
    # Check prerequisites
    factory_dir = repo_path / ".factory"
    if factory_dir.exists():
        raise InitError(
            f".factory directory already exists at {factory_dir}. "
            "Use init_finalize() after context PR is merged, or remove .factory/ to re-analyze."
        )

    if not (repo_path / ".git").exists():
        raise InitError(f"Path is not a git repository (no .git directory): {repo_path}")

    try:
        # Analyze repository with Claude Code
        analyzer = RepoAnalyzer(claude_client)
        analysis_result = await analyzer.analyze_repository(repo_path)

        # Create .factory directory and write proposed context
        factory_dir.mkdir(exist_ok=True)
        context_path = factory_dir / "project_context.md"

        # Generate YAML frontmatter + markdown content
        yaml_content = yaml.dump(
            analysis_result.proposed_context, default_flow_style=False, sort_keys=False
        )

        context_content = f"""---
{yaml_content}---

# Proposed Project Context

This file was generated by automated repository analysis.
Please review and edit as needed before merging.

## Analysis Notes

{analysis_result.analysis_notes}

## Next Steps

1. Review the proposed project configuration above
2. Edit any sections that need adjustment
3. Merge this PR to finalize the context
4. Run `harness init --finalize` to complete initialization
"""

        context_path.write_text(context_content)

        # Create PR with proposed context
        _create_context_pr(repo_path, github_token, analysis_result)

    except AnalysisError as e:
        # Clean up on failure
        if factory_dir.exists():
            import shutil

            shutil.rmtree(factory_dir)
        raise InitError(f"Repository analysis failed: {e}") from e
    except Exception as e:
        # Clean up on failure
        if factory_dir.exists():
            import shutil

            shutil.rmtree(factory_dir)
        raise InitError(f"Failed to analyze repository: {e}") from e


def init_finalize(
    repo_path: Path, templates_dir: Path, stonehaven_url: str, github_token: str
) -> None:
    """Complete initialization after context PR is merged.

    This function completes the harness initialization flow after the operator
    has reviewed and merged the context PR created by init_analyze().
    It rejoins the greenfield flow at agent rendering.

    Args:
        repo_path: Path to the repository root
        templates_dir: Path to directory containing template files
        stonehaven_url: URL of the Stonehaven listener
        github_token: GitHub Personal Access Token with webhooks:write scope

    Raises:
        InitError: If finalization fails or prerequisites are not met
    """
    factory_dir = repo_path / ".factory"
    project_context_path = factory_dir / "project_context.md"

    # Check prerequisites
    if not factory_dir.exists():
        raise InitError(
            f".factory directory not found at {factory_dir}. "
            "Run init_analyze() first to analyze the repository."
        )

    if not project_context_path.exists():
        raise InitError(
            f"project_context.md not found at {project_context_path}. "
            "The context PR may not have been merged yet."
        )

    # Validate project context file
    try:
        project_context = validate_project_context(project_context_path)
    except ProjectContextError as e:
        raise InitError(f"Invalid project_context.md: {e}") from e

    # Continue with standard greenfield flow
    try:
        # Use the same logic as init_greenfield, but skip project_context validation
        # since we already validated it above
        agents_dir = factory_dir / "agents"
        webhook_config_path = factory_dir / "webhook_config.yml"
        harness_toml_path = factory_dir / "harness.toml"

        # Create agents directory (idempotent)
        agents_dir.mkdir(exist_ok=True)

        # Render agent files
        render_agents(
            project_context_path=project_context_path,
            templates_dir=templates_dir,
            output_dir=agents_dir,
            update_lock=True,
        )

        # Generate stonehaven ID for this project (idempotent)
        stonehaven_id = _get_or_generate_stonehaven_id(harness_toml_path)

        # Extract repository information from project context
        repo_info = _extract_repo_info(repo_path, project_context)

        # Generate webhook secret (idempotent)
        webhook_secret = _get_or_generate_webhook_secret(webhook_config_path)

        # Register with Stonehaven
        _register_with_stonehaven(
            stonehaven_url=stonehaven_url,
            stonehaven_id=stonehaven_id,
            repo=repo_info["full_name"],
            project_name=project_context["project"]["name"],
        )

        # Register GitHub webhook
        webhook_url = f"{stonehaven_url.rstrip('/')}/webhooks/{stonehaven_id}"
        webhook_id = register_webhook_sync(
            repo_owner=repo_info["owner"],
            repo_name=repo_info["name"],
            webhook_url=webhook_url,
            secret=webhook_secret,
            github_token=github_token,
        )

        # Create configuration files
        _create_webhook_config(webhook_config_path, stonehaven_id, webhook_secret, webhook_url)
        _create_harness_toml(
            harness_toml_path,
            stonehaven_id=stonehaven_id,
            project_name=project_context["project"]["name"],
            repo=repo_info["full_name"],
            webhook_id=webhook_id,
        )

    except Exception as e:
        raise InitError(f"Failed to finalize initialization: {e}") from e


def _create_context_pr(repo_path: Path, github_token: str, analysis_result: Any) -> None:
    """Create GitHub PR with proposed project context.

    Args:
        repo_path: Path to the repository root
        github_token: GitHub Personal Access Token
        analysis_result: Analysis result from RepoAnalyzer

    Raises:
        InitError: If PR creation fails
    """
    try:
        import subprocess

        # Create a new branch for the context PR
        branch_name = f"factory/proposed-context-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

        # Get current branch to return to it later
        current_branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        current_branch = current_branch_result.stdout.strip()

        # Create and switch to new branch
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=repo_path,
            check=True,
        )

        try:
            # Stage the .factory directory
            subprocess.run(
                ["git", "add", ".factory/"],
                cwd=repo_path,
                check=True,
            )

            # Commit the changes
            commit_message = f"""factory: proposed project context

Automated repository analysis completed.
Confidence score: {analysis_result.confidence_score:.2f}

Please review the proposed project_context.md and edit as needed.
After merging, run `harness init --finalize` to complete setup.

🤖 Generated with Claude Code

Co-authored-by: Claude <noreply@anthropic.com>"""

            subprocess.run(
                ["git", "commit", "-m", commit_message],
                cwd=repo_path,
                check=True,
            )

            # Push the branch
            subprocess.run(
                ["git", "push", "origin", branch_name],
                cwd=repo_path,
                check=True,
            )

            # Get repository information for PR creation
            remote_result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )

            remote_url = remote_result.stdout.strip()

            # Parse GitHub repository name
            repo_full_name = _parse_github_repo_from_url(remote_url)

            # Create PR using GitHub API
            _create_github_pr(
                repo_full_name=repo_full_name,
                head_branch=branch_name,
                base_branch=current_branch,
                github_token=github_token,
                analysis_result=analysis_result,
            )

        finally:
            # Always return to original branch
            subprocess.run(
                ["git", "checkout", current_branch],
                cwd=repo_path,
                check=False,  # Don't fail if this fails
            )

    except subprocess.CalledProcessError as e:
        raise InitError(f"Failed to create context PR: Git command failed: {e}") from e
    except Exception as e:
        raise InitError(f"Failed to create context PR: {e}") from e


def _parse_github_repo_from_url(remote_url: str) -> str:
    """Parse GitHub repository name from git remote URL.

    Args:
        remote_url: Git remote URL (SSH or HTTPS)

    Returns:
        Repository name in 'owner/repo' format

    Raises:
        ValueError: If URL format is not recognized
    """
    if "github.com" not in remote_url:
        raise ValueError(f"Not a GitHub repository URL: {remote_url}")

    if remote_url.startswith("git@github.com:"):
        # SSH format: git@github.com:owner/repo.git
        repo_part = remote_url.split(":", 1)[1]
    elif "github.com/" in remote_url:
        # HTTPS format: https://github.com/owner/repo.git
        repo_part = remote_url.split("github.com/", 1)[1]
    else:
        raise ValueError(f"Unrecognized GitHub URL format: {remote_url}")

    # Remove .git suffix if present
    if repo_part.endswith(".git"):
        repo_part = repo_part[:-4]

    if "/" not in repo_part:
        raise ValueError(f"Invalid repository format: {repo_part}")

    return repo_part


def _create_github_pr(
    repo_full_name: str,
    head_branch: str,
    base_branch: str,
    github_token: str,
    analysis_result: Any,
) -> None:
    """Create GitHub PR using the GitHub API.

    Args:
        repo_full_name: Repository name in 'owner/repo' format
        head_branch: Branch with the changes
        base_branch: Target branch for the PR
        github_token: GitHub Personal Access Token
        analysis_result: Analysis result from RepoAnalyzer

    Raises:
        InitError: If PR creation fails
    """
    try:
        pr_title = "factory: proposed project context"

        pr_body = f"""## 🏭 Harness Context Analysis

This PR contains an automatically generated project context based on repository analysis.

**Confidence Score:** {analysis_result.confidence_score:.2f}/1.0

### 📋 What's Included

- `.factory/project_context.md` - Proposed project configuration
- Analysis notes and recommendations

### 🔍 Analysis Summary

{analysis_result.analysis_notes}

### ✅ Next Steps

1. **Review** the proposed configuration in `.factory/project_context.md`
2. **Edit** any sections that need adjustment for your project
3. **Merge** this PR when you're satisfied with the configuration
4. **Run** `harness init --finalize` to complete the harness setup

### ⚠️ Important Notes

- The proposed context is based on automated analysis and may need manual adjustments
- Review all sections carefully, especially `invariants` and `sharp_edges`
- The `deployment.surface` setting affects which reviewers are enabled

---

🤖 Generated with [Claude Code](https://claude.ai/code)"""

        api_url = f"https://api.github.com/repos/{repo_full_name}/pulls"

        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }

        payload = {
            "title": pr_title,
            "body": pr_body,
            "head": head_branch,
            "base": base_branch,
            "draft": False,
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(api_url, json=payload, headers=headers)

            if response.status_code == 201:
                pr_data = response.json()
                pr_url = pr_data.get("html_url", "<URL not available>")
                print(f"✅ Created PR: {pr_url}")
            elif response.status_code == 422:
                # PR might already exist or other validation error
                error_detail = "Validation error"
                try:
                    error_data = response.json()
                    if "errors" in error_data:
                        error_messages = [err.get("message", "") for err in error_data["errors"]]
                        error_detail = "; ".join(error_messages)
                    else:
                        error_detail = error_data.get("message", error_detail)
                except Exception:
                    pass

                raise InitError(f"Failed to create PR: {error_detail}")
            else:
                # Other error
                error_detail = "Unknown error"
                try:
                    error_data = response.json()
                    error_detail = error_data.get("message", str(response.status_code))
                except Exception:
                    error_detail = f"{response.status_code} {response.reason_phrase}"

                raise InitError(f"Failed to create PR: {error_detail}")

    except httpx.RequestError as e:
        raise InitError(f"Failed to connect to GitHub API: {e}") from e

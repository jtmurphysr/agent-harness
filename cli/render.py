"""Template rendering end-to-end.

Orchestrates the full agent rendering pipeline:
1. Validates project_context.md
2. Identifies enabled reviewers
3. Renders only enabled agents
4. Updates templates_lock.yml
"""

from pathlib import Path

from renderer.compose import CompositionError, compose_agent
from renderer.lockfile import read_lock, write_lock
from renderer.validators import ProjectContextError, validate_project_context

__all__ = ["RenderError", "render_agents"]


class RenderError(Exception):
    """Raised when agent rendering fails."""


def render_agents(
    project_context_path: Path,
    templates_dir: Path,
    output_dir: Path,
    update_lock: bool = True,
) -> None:
    """Render all enabled agents from templates + context.

    Args:
        project_context_path: Path to project_context.md file
        templates_dir: Path to directory containing template files
        output_dir: Path to directory where agents should be written
        update_lock: Whether to update templates_lock.yml with current versions

    Raises:
        RenderError: If rendering fails
    """
    # Validate project context
    try:
        context_data = validate_project_context(project_context_path)
    except ProjectContextError as e:
        raise RenderError(f"Invalid project context: {e}") from e

    # Get reviewers configuration
    reviewers_config = context_data["reviewers"]

    # Map reviewer names to template files
    reviewer_templates = {
        "engineer": "engineer.template.md",
        "architect": "architect.template.md",
        "sre": "sre.template.md",
        "deploy": "deploy.template.md",  # Not implemented yet, but handle gracefully
    }

    # Track template versions for lock file
    template_versions = {}
    if update_lock:
        # Read existing lock to preserve versions of templates we don't touch
        lock_path = output_dir / "templates_lock.yml"
        template_versions = read_lock(lock_path)

    # Render each enabled reviewer
    for reviewer_name, config in reviewers_config.items():
        if not config.get("enabled", False):
            continue

        template_filename = reviewer_templates.get(reviewer_name)
        if not template_filename:
            raise RenderError(f"Unknown reviewer type: {reviewer_name}")

        template_path = templates_dir / template_filename

        # Check if template exists (deploy might not exist yet)
        if not template_path.exists():
            if reviewer_name == "deploy":
                # Deploy templates are optional for now
                continue
            else:
                raise RenderError(f"Template file not found: {template_path}")

        output_file = output_dir / f"{reviewer_name}.md"

        try:
            # Add reviewer-specific variables to context
            enhanced_context = {
                **context_data,
                "reviewer_role": reviewer_name.title(),
                "project_context": context_data["project"]["name"],
            }
            compose_agent(template_path, enhanced_context, output_file)

            if update_lock:
                # Extract and store template version
                template_version = _extract_template_version_from_file(template_path)
                template_versions[template_filename] = template_version

        except CompositionError as e:
            raise RenderError(f"Failed to render {reviewer_name}: {e}") from e

    # Update lock file with current template versions
    if update_lock and template_versions:
        lock_path = output_dir / "templates_lock.yml"
        write_lock(lock_path, template_versions)


def _extract_template_version_from_file(template_path: Path) -> str:
    """Extract version from template file frontmatter.

    Args:
        template_path: Path to template file

    Returns:
        Version string from template frontmatter

    Raises:
        RenderError: If version cannot be extracted
    """
    try:
        from renderer.compose import _extract_template_version

        content = template_path.read_text(encoding="utf-8")
        return _extract_template_version(content)
    except Exception as e:
        raise RenderError(f"Failed to extract version from {template_path}: {e}") from e

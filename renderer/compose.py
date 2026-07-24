"""Jinja2 template composition logic."""

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

__all__ = ["CompositionError", "compose_agent"]


class CompositionError(Exception):
    """Raised when template composition fails."""


def compose_agent(
    template_path: Path,
    context_data: dict[str, Any],
    output_path: Path,
) -> None:
    """Compose Layer 1 template + Layer 2 context into Layer 3 agent file.

    Args:
        template_path: Path to the Layer 1 template file
        context_data: Validated context data from project_context.md
        output_path: Path where the composed agent file should be written

    Raises:
        CompositionError: If template composition fails
    """
    # Verify template exists
    if not template_path.exists():
        raise CompositionError(f"Template file not found: {template_path}")

    try:
        template_content = template_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise CompositionError(f"Failed to read template file: {e}") from e

    # Extract template version from frontmatter
    template_version = _extract_template_version(template_content)

    # Set up Jinja2 environment with template directory as base for includes
    template_dir = template_path.parent
    loader = FileSystemLoader(template_dir)
    env = Environment(
        loader=loader,
        undefined=StrictUndefined,  # Catch undefined variables
        trim_blocks=True,
        lstrip_blocks=True,
    )

    try:
        # Load and render the template
        template = env.get_template(template_path.name)
        rendered_content = template.render(**context_data)
    except TemplateNotFound as e:
        raise CompositionError(f"Template not found: {e}") from e
    except Exception as e:
        raise CompositionError(f"Template rendering failed: {e}") from e

    # Create generation header
    generation_header = _create_generation_header(template_path, template_version)

    # Combine header with rendered content
    final_content = generation_header + rendered_content

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the composed agent file
    try:
        output_path.write_text(final_content, encoding="utf-8")
    except OSError as e:
        raise CompositionError(f"Failed to write output file: {e}") from e


def _extract_template_version(template_content: str) -> str:
    """Extract version from template frontmatter.

    Args:
        template_content: Raw template content

    Returns:
        Version string from frontmatter

    Raises:
        CompositionError: If version cannot be extracted
    """
    frontmatter_match = re.match(r"^---\n(.*?)\n---", template_content, re.DOTALL)
    if not frontmatter_match:
        raise CompositionError("No YAML frontmatter found in template")

    frontmatter_text = frontmatter_match.group(1)

    # Look for version line in frontmatter
    version_match = re.search(
        r'^version:\s*["\']?([^"\'\n]+)["\']?\s*$', frontmatter_text, re.MULTILINE
    )
    if not version_match:
        raise CompositionError("No version found in template frontmatter")

    return version_match.group(1)


def _create_generation_header(template_path: Path, template_version: str) -> str:
    """Create the generation header for composed agent files.

    Args:
        template_path: Path to the source template
        template_version: Version extracted from template frontmatter

    Returns:
        Generation header as string
    """
    return f"""<!-- GENERATED FILE — DO NOT EDIT -->
<!-- Source: {template_path.name} v{template_version} + project_context.md -->
<!-- Regenerate with: harness render -->

"""

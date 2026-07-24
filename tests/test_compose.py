"""Tests for renderer/compose.py."""

import tempfile
from pathlib import Path

import pytest

from renderer.compose import CompositionError, compose_agent


class TestComposeAgent:
    """Tests for compose_agent function."""

    def test_compose_agent_valid_template_and_context(self, tmp_path: Path) -> None:
        """Test composition with valid template and context."""
        # Create template file
        template_file = tmp_path / "test.template.md"
        template_file.write_text("""---
version: "1.2.3"
propagation: opt_in
---

# {{ project.name }} Review

**Description:** {{ project.description }}

**Stack:** {{ stack.language }} / {{ stack.framework }}

**Invariants:**
{% for invariant in invariants %}
- {{ invariant.rule }} ({{ invariant.id }}){% endfor %}
""")

        # Create context data
        context_data = {
            "project": {
                "name": "test-project",
                "description": "A test project"
            },
            "stack": {
                "language": "Python",
                "framework": "FastAPI"
            },
            "invariants": [
                {"id": "auth_required", "rule": "All endpoints need auth"},
                {"id": "validate_input", "rule": "Validate all inputs"}
            ]
        }

        # Create output path
        output_file = tmp_path / "composed_agent.md"

        # Compose the agent
        compose_agent(template_file, context_data, output_file)

        # Verify output exists
        assert output_file.exists()

        # Read and verify content
        content = output_file.read_text(encoding="utf-8")
        
        # Check generation header
        assert "<!-- GENERATED FILE — DO NOT EDIT -->" in content
        assert "test.template.md v1.2.3 + project_context.md" in content
        assert "harness render" in content
        
        # Check rendered content
        assert "# test-project Review" in content
        assert "**Description:** A test project" in content
        assert "**Stack:** Python / FastAPI" in content
        assert "- All endpoints need auth (auth_required)" in content
        assert "- Validate all inputs (validate_input)" in content

    def test_compose_agent_missing_template_file(self, tmp_path: Path) -> None:
        """Test error when template file doesn't exist."""
        nonexistent_template = tmp_path / "nonexistent.template.md"
        context_data = {"project": {"name": "test"}}
        output_file = tmp_path / "output.md"
        
        with pytest.raises(CompositionError, match="Template file not found"):
            compose_agent(nonexistent_template, context_data, output_file)

    def test_compose_agent_invalid_jinja2_syntax(self, tmp_path: Path) -> None:
        """Test error with invalid Jinja2 syntax in template."""
        template_file = tmp_path / "invalid.template.md"
        template_file.write_text("""---
version: "1.0.0"
---

# Invalid Template

{{ project.name } missing closing brace
""")

        context_data = {"project": {"name": "test"}}
        output_file = tmp_path / "output.md"
        
        with pytest.raises(CompositionError, match="Template rendering failed"):
            compose_agent(template_file, context_data, output_file)

    def test_compose_agent_undefined_variables(self, tmp_path: Path) -> None:
        """Test error with undefined variables in template."""
        template_file = tmp_path / "undefined.template.md"
        template_file.write_text("""---
version: "1.0.0"
---

# Template with undefined variable

Project: {{ project.name }}
Undefined: {{ missing_variable }}
""")

        context_data = {"project": {"name": "test"}}
        output_file = tmp_path / "output.md"
        
        with pytest.raises(CompositionError, match="Template rendering failed"):
            compose_agent(template_file, context_data, output_file)

    def test_compose_agent_includes_generation_header(self, tmp_path: Path) -> None:
        """Test that output includes the required generation header."""
        template_file = tmp_path / "simple.template.md"
        template_file.write_text("""---
version: "2.1.0"
---

Simple template content.
""")

        context_data = {}
        output_file = tmp_path / "output.md"
        
        compose_agent(template_file, context_data, output_file)
        
        content = output_file.read_text(encoding="utf-8")
        lines = content.split('\n')
        
        # Verify header format
        assert lines[0] == "<!-- GENERATED FILE — DO NOT EDIT -->"
        assert "simple.template.md v2.1.0 + project_context.md" in lines[1]
        assert "harness render" in lines[2]
        assert lines[3] == ""  # Empty line after header

    def test_compose_agent_preserves_template_version(self, tmp_path: Path) -> None:
        """Test that template version is extracted and preserved in output."""
        template_file = tmp_path / "versioned.template.md"
        template_file.write_text("""---
version: "3.14.159"
propagation: auto
other_field: value
---

Template content here.
""")

        context_data = {}
        output_file = tmp_path / "output.md"
        
        compose_agent(template_file, context_data, output_file)
        
        content = output_file.read_text(encoding="utf-8")
        assert "versioned.template.md v3.14.159 + project_context.md" in content

    def test_compose_agent_no_frontmatter(self, tmp_path: Path) -> None:
        """Test error when template has no frontmatter."""
        template_file = tmp_path / "no_frontmatter.template.md"
        template_file.write_text("Just content without frontmatter")

        context_data = {}
        output_file = tmp_path / "output.md"
        
        with pytest.raises(CompositionError, match="No YAML frontmatter found in template"):
            compose_agent(template_file, context_data, output_file)

    def test_compose_agent_no_version_in_frontmatter(self, tmp_path: Path) -> None:
        """Test error when template frontmatter has no version."""
        template_file = tmp_path / "no_version.template.md"
        template_file.write_text("""---
propagation: opt_in
description: A template without version
---

Template content.
""")

        context_data = {}
        output_file = tmp_path / "output.md"
        
        with pytest.raises(CompositionError, match="No version found in template frontmatter"):
            compose_agent(template_file, context_data, output_file)

    def test_compose_agent_creates_output_directory(self, tmp_path: Path) -> None:
        """Test that output directory is created if it doesn't exist."""
        template_file = tmp_path / "test.template.md"
        template_file.write_text("""---
version: "1.0.0"
---

Content.
""")

        context_data = {}
        # Output file in nested directory that doesn't exist
        output_file = tmp_path / "nested" / "deep" / "output.md"
        
        compose_agent(template_file, context_data, output_file)
        
        assert output_file.exists()
        assert output_file.parent.exists()

    def test_compose_agent_with_includes(self, tmp_path: Path) -> None:
        """Test template composition with Jinja2 includes."""
        # Create a partial template
        partial_dir = tmp_path / "_shared"
        partial_dir.mkdir()
        partial_file = partial_dir / "partial.md"
        partial_file.write_text("Shared content from partial.")

        # Create main template that includes the partial
        template_file = tmp_path / "main.template.md"
        template_file.write_text("""---
version: "1.0.0"
---

# Main Template

{% include '_shared/partial.md' %}

Project: {{ project.name }}
""")

        context_data = {"project": {"name": "test-project"}}
        output_file = tmp_path / "output.md"
        
        compose_agent(template_file, context_data, output_file)
        
        content = output_file.read_text(encoding="utf-8")
        assert "Shared content from partial." in content
        assert "Project: test-project" in content

    def test_compose_agent_version_quoted_formats(self, tmp_path: Path) -> None:
        """Test version extraction with different quote formats."""
        test_cases = [
            ('version: "1.0.0"', "1.0.0"),
            ("version: '1.0.0'", "1.0.0"),
            ("version: 1.0.0", "1.0.0"),
            ('version: "1.0.0-beta"', "1.0.0-beta"),
            ("version: 2.1", "2.1"),
        ]
        
        for frontmatter_version, expected_version in test_cases:
            template_file = tmp_path / f"version_test_{expected_version.replace('.', '_').replace('-', '_')}.template.md"
            template_file.write_text(f"""---
{frontmatter_version}
---

Content.
""")

            context_data = {}
            output_file = tmp_path / f"output_{expected_version.replace('.', '_').replace('-', '_')}.md"
            
            compose_agent(template_file, context_data, output_file)
            
            content = output_file.read_text(encoding="utf-8")
            assert f"v{expected_version} + project_context.md" in content

    def test_compose_agent_read_error(self, tmp_path: Path) -> None:
        """Test error handling when template file cannot be read."""
        template_file = tmp_path / "test.template.md"
        template_file.write_text("""---
version: "1.0.0"
---

Content.
""")
        
        # Make file unreadable (this might not work on all systems)
        template_file.chmod(0o000)
        
        context_data = {}
        output_file = tmp_path / "output.md"
        
        try:
            with pytest.raises(CompositionError, match="Failed to read template file"):
                compose_agent(template_file, context_data, output_file)
        finally:
            # Restore permissions for cleanup
            template_file.chmod(0o644)

    def test_compose_agent_write_error(self, tmp_path: Path) -> None:
        """Test error handling when output file cannot be written."""
        template_file = tmp_path / "test.template.md"
        template_file.write_text("""---
version: "1.0.0"
---

Content.
""")
        
        context_data = {}
        
        # Try to write to a directory instead of a file
        output_file = tmp_path / "directory_not_file"
        output_file.mkdir()
        
        with pytest.raises(CompositionError, match="Failed to write output file"):
            compose_agent(template_file, context_data, output_file)
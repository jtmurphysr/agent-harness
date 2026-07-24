"""Tests for cli/render.py."""

import tempfile
from pathlib import Path

import pytest

from cli.render import RenderError, render_agents


class TestRenderAgents:
    """Tests for render_agents function."""

    def test_render_agents_all_enabled(self, tmp_path: Path) -> None:
        """Test rendering when all reviewers are enabled."""
        # Create templates directory with test templates
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create engineer template
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text("""---
version: "1.0.0"
propagation: opt_in
---

# Engineer Review for {{ project.name }}

**Description:** {{ project.description }}
**Stack:** {{ stack.language }}
""")

        # Create architect template  
        architect_template = templates_dir / "architect.template.md"
        architect_template.write_text("""---
version: "2.0.0"
propagation: opt_in
---

# Architect Review for {{ project.name }}

**Description:** {{ project.description }}
**Framework:** {{ stack.framework }}
""")

        # Create SRE template
        sre_template = templates_dir / "sre.template.md"
        sre_template.write_text("""---
version: "1.5.0"
propagation: opt_in
---

# SRE Review for {{ project.name }}

**Description:** {{ project.description }}
**Surface:** {{ deployment.surface }}
""")

        # Create project context file
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "A test project for validation"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants:
  - id: "test-rule"
    rule: "Always validate inputs"
    severity: "correctness"

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
---

This is a test project.
""")

        # Create output directory
        output_dir = tmp_path / "output"

        # Render agents
        render_agents(context_file, templates_dir, output_dir)

        # Verify all agents were created
        assert (output_dir / "engineer.md").exists()
        assert (output_dir / "architect.md").exists()
        assert (output_dir / "sre.md").exists()

        # Verify lock file was created
        lock_file = output_dir / "templates_lock.yml"
        assert lock_file.exists()
        
        # Check lock file content
        lock_content = lock_file.read_text()
        assert "engineer.template.md: 1.0.0" in lock_content
        assert "architect.template.md: 2.0.0" in lock_content
        assert "sre.template.md: 1.5.0" in lock_content

        # Verify generated files have headers
        engineer_content = (output_dir / "engineer.md").read_text()
        assert "<!-- GENERATED FILE — DO NOT EDIT -->" in engineer_content
        assert "Source: engineer.template.md v1.0.0 + project_context.md" in engineer_content
        assert "Regenerate with: harness render" in engineer_content
        
        # Verify template was rendered with context
        assert "Engineer Review for test-project" in engineer_content
        assert "A test project for validation" in engineer_content

    def test_render_agents_deploy_disabled(self, tmp_path: Path) -> None:
        """Test rendering when deploy reviewer is disabled."""
        # Create templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create engineer template
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text("""---
version: "1.0.0"
propagation: opt_in
---

# Engineer Review for {{ project.name }}
""")

        # Create project context file with deploy disabled
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "A test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer:
    enabled: true
    model_class: "code_review"
  architect:
    enabled: false
    model_class: "structural_review"
  sre:
    enabled: false
    model_class: "adversarial_review"
  deploy:
    enabled: false
    surfaces: []
---

Test project.
""")

        # Create output directory
        output_dir = tmp_path / "output"

        # Render agents
        render_agents(context_file, templates_dir, output_dir)

        # Verify only engineer was created
        assert (output_dir / "engineer.md").exists()
        assert not (output_dir / "architect.md").exists()
        assert not (output_dir / "sre.md").exists()
        assert not (output_dir / "deploy.md").exists()

    def test_render_agents_invalid_context(self, tmp_path: Path) -> None:
        """Test rendering with invalid project context."""
        # Create templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create invalid project context file (missing required fields)
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  # missing description

stack:
  language: "Python"
  # missing framework

# missing deployment, invariants, reviewers sections
---

Invalid context.
""")

        # Create output directory
        output_dir = tmp_path / "output"

        # Rendering should fail
        with pytest.raises(RenderError) as exc_info:
            render_agents(context_file, templates_dir, output_dir)
        
        assert "Invalid project context" in str(exc_info.value)

    def test_render_agents_missing_templates(self, tmp_path: Path) -> None:
        """Test rendering when template files are missing."""
        # Create empty templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create valid project context file
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "A test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer:
    enabled: true
    model_class: "code_review"
  architect:
    enabled: false
    model_class: "structural_review"
  sre:
    enabled: false
    model_class: "adversarial_review"
---

Test project.
""")

        # Create output directory
        output_dir = tmp_path / "output"

        # Rendering should fail because engineer template is missing
        with pytest.raises(RenderError) as exc_info:
            render_agents(context_file, templates_dir, output_dir)
        
        assert "Template file not found" in str(exc_info.value)

    def test_render_agents_updates_lock_file(self, tmp_path: Path) -> None:
        """Test that lock file is properly updated with template versions."""
        # Create templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create engineer template
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text("""---
version: "2.5.0"
propagation: opt_in
---

# Engineer Review for {{ project.name }}
""")

        # Create project context file
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "A test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer:
    enabled: true
    model_class: "code_review"
  architect:
    enabled: false
    model_class: "structural_review"
  sre:
    enabled: false
    model_class: "adversarial_review"
---

Test project.
""")

        # Create output directory with existing lock file
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        existing_lock = output_dir / "templates_lock.yml"
        existing_lock.write_text("""architect.template.md: '1.0.0'
engineer.template.md: '1.0.0'
sre.template.md: '1.0.0'
""")

        # Render agents
        render_agents(context_file, templates_dir, output_dir, update_lock=True)

        # Verify lock file was updated
        lock_content = existing_lock.read_text()
        assert "engineer.template.md: 2.5.0" in lock_content
        # Other templates should be preserved since they weren't rendered
        assert "architect.template.md: 1.0.0" in lock_content
        assert "sre.template.md: 1.0.0" in lock_content

    def test_render_agents_preserves_existing_output_dir(self, tmp_path: Path) -> None:
        """Test that existing files in output directory are preserved when not overwritten."""
        # Create templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create engineer template
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text("""---
version: "1.0.0"
propagation: opt_in
---

# Engineer Review for {{ project.name }}
""")

        # Create project context file
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "A test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer:
    enabled: true
    model_class: "code_review"
  architect:
    enabled: false
    model_class: "structural_review"
  sre:
    enabled: false
    model_class: "adversarial_review"
---

Test project.
""")

        # Create output directory with some existing files
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        existing_file = output_dir / "existing.txt"
        existing_file.write_text("This should be preserved")

        # Render agents
        render_agents(context_file, templates_dir, output_dir)

        # Verify existing file is preserved
        assert existing_file.exists()
        assert existing_file.read_text() == "This should be preserved"
        
        # Verify new file was created
        assert (output_dir / "engineer.md").exists()

    def test_render_agents_template_version_error(self, tmp_path: Path) -> None:
        """Test handling of template version extraction errors."""
        # Create templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create template without version in frontmatter
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text("""---
propagation: opt_in
---

# Engineer Review for {{ project.name }}
""")

        # Create project context file
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "A test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer:
    enabled: true
    model_class: "code_review"
  architect:
    enabled: false
    model_class: "structural_review"
  sre:
    enabled: false
    model_class: "adversarial_review"
---

Test project.
""")

        # Create output directory
        output_dir = tmp_path / "output"

        # Rendering should fail with version extraction error
        with pytest.raises(RenderError) as exc_info:
            render_agents(context_file, templates_dir, output_dir)
        
        assert "No version found in template frontmatter" in str(exc_info.value)

    def test_render_agents_deploy_missing_template_continues(self, tmp_path: Path) -> None:
        """Test that missing deploy template is gracefully handled."""
        # Create templates directory (without deploy template)
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create engineer template
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text("""---
version: "1.0.0"
propagation: opt_in
---

# Engineer Review for {{ project.name }}
""")

        # Create project context file with deploy enabled
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "A test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer:
    enabled: true
    model_class: "code_review"
  architect:
    enabled: false
    model_class: "structural_review"
  sre:
    enabled: false
    model_class: "adversarial_review"
  deploy:
    enabled: true
    surfaces: ["server"]
---

Test project.
""")

        # Create output directory
        output_dir = tmp_path / "output"

        # Rendering should succeed, skipping deploy
        render_agents(context_file, templates_dir, output_dir)

        # Verify engineer was created but not deploy
        assert (output_dir / "engineer.md").exists()
        assert not (output_dir / "deploy.md").exists()

    def test_render_agents_composition_error(self, tmp_path: Path) -> None:
        """Test handling of composition errors during rendering."""
        # Create templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create broken template with invalid Jinja2 syntax
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text("""---
version: "1.0.0"
propagation: opt_in
---

# Engineer Review for {{ project.name

This template has broken Jinja2 syntax!
""")

        # Create project context file
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "A test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer:
    enabled: true
    model_class: "code_review"
  architect:
    enabled: false
    model_class: "structural_review"
  sre:
    enabled: false
    model_class: "adversarial_review"
---

Test project.
""")

        # Create output directory
        output_dir = tmp_path / "output"

        # Rendering should fail with composition error
        with pytest.raises(RenderError) as exc_info:
            render_agents(context_file, templates_dir, output_dir)
        
        assert "Failed to render engineer" in str(exc_info.value)

    def test_render_agents_no_lock_update(self, tmp_path: Path) -> None:
        """Test rendering without updating lock file."""
        # Create templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create engineer template
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text("""---
version: "1.0.0"
propagation: opt_in
---

# Engineer Review for {{ project.name }}
""")

        # Create project context file
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "A test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer:
    enabled: true
    model_class: "code_review"
  architect:
    enabled: false
    model_class: "structural_review"
  sre:
    enabled: false
    model_class: "adversarial_review"
---

Test project.
""")

        # Create output directory
        output_dir = tmp_path / "output"

        # Render agents without lock update
        render_agents(context_file, templates_dir, output_dir, update_lock=False)

        # Verify agent was created
        assert (output_dir / "engineer.md").exists()
        
        # Verify lock file was NOT created
        assert not (output_dir / "templates_lock.yml").exists()
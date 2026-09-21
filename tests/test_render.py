"""Tests for cli/render.py."""

import re
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


REAL_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# Severities are interleaved on purpose: no role's matches are the first N
# entries, so a template that numbers with `loop.index` over the unfiltered
# list prints a gapped sequence (1, 3, 5) instead of 1, 2, 3.
SHAPE_CONTEXT = """---
project:
  name: "shape-fixture"
  description: "Fixture project used to assert the shape of the rendered output."

stack:
  language: "python"
  framework: "fastapi"
  database: "sqlite"
  primary_files:
    high_blast_radius:
      - "blast/one.py"
      - "blast/two.py"
    generated:
      - "generated/one.py"
      - "generated/two.py"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true
  production_record_count: 42

invariants:
  - id: "inv_perf_one"
    rule: "Invariant perf one."
    severity: "performance"
  - id: "inv_correct_one"
    rule: "Invariant correct one."
    severity: "correctness"
  - id: "inv_irrev_one"
    rule: "Invariant irrev one."
    severity: "irreversibility"
  - id: "inv_data_loss_one"
    rule: "Invariant data loss one."
    severity: "data_loss"
  - id: "inv_consistency_one"
    rule: "Invariant consistency one."
    severity: "data_consistency"
  - id: "inv_irrev_two"
    rule: "Invariant irrev two."
    severity: "irreversibility"
  - id: "inv_perf_two"
    rule: "Invariant perf two."
    severity: "performance"

sharp_edges:
  - location: "edge/one.py"
    issue: "Edge one issue"
    fix: "Edge one fix"
  - location: "edge/two.py"
    issue: "Edge two issue"
    fix: "Edge two fix"
  - location: "edge/three.py"
    issue: "Edge three issue"
    fix: "Edge three fix"

structural_decisions:
  - decision: "Decision alpha"
    rationale: "Rationale alpha"
  - decision: "Decision beta"
    rationale: "Rationale beta"

becoming:
  - "Becoming goal alpha"
  - "Becoming goal beta"

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

Fixture context for rendered-shape assertions.
"""

# Which invariants each role's severity filter selects, in source order.
EXPECTED_INVARIANT_IDS = {
    "engineer": ["inv_correct_one", "inv_data_loss_one", "inv_consistency_one"],
    "architect": ["inv_perf_one", "inv_consistency_one", "inv_perf_two"],
    "sre": ["inv_irrev_one", "inv_data_loss_one", "inv_irrev_two"],
}

SHARP_EDGE_LOCATIONS = ["edge/one.py", "edge/two.py", "edge/three.py"]
STRUCTURAL_DECISIONS = ["Decision alpha", "Decision beta"]
BECOMING_GOALS = ["Becoming goal alpha", "Becoming goal beta"]

INVARIANT_LINE = re.compile(r"^(?P<number>\d+)\. (?P<rule>.+) `\(invariant: (?P<id>[a-z_]+)\)`$")


def _lines_with(lines: list[str], needles: list[str]) -> list[str]:
    """Return the lines that mention at least one of `needles`."""
    return [line for line in lines if any(needle in line for needle in needles)]


def _invariant_ids_on(line: str, invariant_ids: list[str]) -> int:
    """Count how many of `invariant_ids` are cited on one line."""
    return sum(f"(invariant: {invariant_id})" in line for invariant_id in invariant_ids)


def _invariant_lines(content: str, invariant_ids: list[str]) -> list[str]:
    """Return the rendered lines citing a fixture invariant.

    Matched by id, not by the `(invariant: ...)` marker alone: the shared output
    contract partial documents that marker in prose, and those lines are not the
    list under test.
    """
    return [line for line in content.splitlines() if _invariant_ids_on(line, invariant_ids)]


class TestRenderedListShape:
    """The rendered agent files must put one list item on one physical line.

    validate_harness.py Pass 3 diffs .claude/agents/ against a fresh render of the
    same templates, so it is self-consistent by construction and stayed green while
    every list in every rendered reviewer was collapsed onto a single line: with
    trim_blocks on, a block tag at the end of a content line eats that line's
    newline. These tests read the real templates/ and assert on the shape of what
    they produce, which is what nothing was doing.
    """

    @pytest.fixture
    def rendered(self, tmp_path: Path) -> dict[str, str]:
        """Render the shipped templates against the shape fixture context."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text(SHAPE_CONTEXT)
        output_dir = tmp_path / "agents"

        render_agents(context_file, REAL_TEMPLATES_DIR, output_dir, update_lock=False)

        return {
            role: (output_dir / f"{role}.md").read_text(encoding="utf-8")
            for role in ("engineer", "architect", "sre")
        }

    @pytest.mark.parametrize("role", ["engineer", "architect", "sre"])
    def test_invariants_render_one_per_line(self, rendered: dict[str, str], role: str) -> None:
        """Each invariant this role's filter selects gets its own physical line."""
        expected_ids = EXPECTED_INVARIANT_IDS[role]
        invariant_lines = _invariant_lines(rendered[role], expected_ids)

        for line in invariant_lines:
            assert _invariant_ids_on(line, expected_ids) == 1, (
                f"{role}: two invariants share one line: {line}"
            )

        assert len(invariant_lines) == len(expected_ids)

    @pytest.mark.parametrize("role", ["engineer", "architect", "sre"])
    def test_invariant_numbering_is_contiguous_from_one(
        self, rendered: dict[str, str], role: str
    ) -> None:
        """Numbering counts the filtered subset, not the position in `invariants`."""
        expected_ids = EXPECTED_INVARIANT_IDS[role]
        matches = [
            INVARIANT_LINE.match(line) for line in _invariant_lines(rendered[role], expected_ids)
        ]

        assert all(matches), f"{role}: an invariant line is not `N. rule (invariant: id)`"

        numbers = [int(m.group("number")) for m in matches if m]
        ids = [m.group("id") for m in matches if m]

        assert numbers == list(range(1, len(expected_ids) + 1))
        assert ids == expected_ids

    @pytest.mark.parametrize("role", ["engineer", "architect", "sre"])
    def test_only_the_roles_severities_are_rendered(
        self, rendered: dict[str, str], role: str
    ) -> None:
        """The severity filter still filters — renumbering did not widen the set."""
        all_ids = {invariant_id for ids in EXPECTED_INVARIANT_IDS.values() for invariant_id in ids}
        for invariant_id in all_ids:
            present = f"(invariant: {invariant_id})" in rendered[role]
            assert present is (invariant_id in EXPECTED_INVARIANT_IDS[role]), (
                f"{role}: unexpected presence/absence of {invariant_id}"
            )

    @pytest.mark.parametrize("role", ["engineer", "sre"])
    def test_sharp_edges_render_one_per_line(self, rendered: dict[str, str], role: str) -> None:
        """Each sharp edge gets its own bullet on its own line."""
        lines = rendered[role].splitlines()
        edge_lines = _lines_with(lines, SHARP_EDGE_LOCATIONS)

        assert len(edge_lines) == len(SHARP_EDGE_LOCATIONS)
        for line in edge_lines:
            assert sum(loc in line for loc in SHARP_EDGE_LOCATIONS) == 1, (
                f"{role}: two sharp edges share one line: {line}"
            )
            assert line.startswith("- "), f"{role}: sharp edge does not start its line: {line}"

    @pytest.mark.parametrize("role", ["engineer", "architect"])
    def test_structural_decisions_render_one_per_line(
        self, rendered: dict[str, str], role: str
    ) -> None:
        """Each structural decision gets its own bullet on its own line."""
        lines = rendered[role].splitlines()
        decision_lines = _lines_with(lines, STRUCTURAL_DECISIONS)

        assert len(decision_lines) == len(STRUCTURAL_DECISIONS)
        for line in decision_lines:
            assert sum(text in line for text in STRUCTURAL_DECISIONS) == 1, (
                f"{role}: two decisions share one line: {line}"
            )
            assert line.startswith("- ")

    def test_becoming_goals_render_one_per_line(self, rendered: dict[str, str]) -> None:
        """Each 12-month-horizon goal gets its own bullet on its own line."""
        lines = rendered["architect"].splitlines()
        goal_lines = _lines_with(lines, BECOMING_GOALS)

        assert len(goal_lines) == len(BECOMING_GOALS)
        for line in goal_lines:
            assert sum(goal in line for goal in BECOMING_GOALS) == 1
            assert line.startswith("- ")

    def test_section_headers_stand_alone(self, rendered: dict[str, str]) -> None:
        """A section header is its own line, with the list starting on the next one."""
        expected = {
            "engineer": [
                "**Critical correctness invariants:**",
                "**Known sharp edges:**",
                "**Pass 1 — Correctness checklist:**",
                "**Pass 2 — Coverage checklist:**",
            ],
            "architect": [
                "**Key abstractions:**",
                "**What this is becoming (12-month horizon):**",
                "**Known structural decisions worth preserving:**",
                "**Critical architectural invariants:**",
            ],
            "sre": [
                "**Production environment:**",
                "**Critical production invariants:**",
                "**Known operational pain points:**",
            ],
        }

        for role, headers in expected.items():
            lines = rendered[role].splitlines()
            for header in headers:
                assert header in lines, f"{role}: {header} is not on a line of its own"

    def test_engineer_conditional_checklist_bullets_stay_separate(
        self, rendered: dict[str, str]
    ) -> None:
        """Bullets guarded by an `{% if %}` are bullets, not a run-on line."""
        lines = rendered["engineer"].splitlines()

        assert "- Database queries: parameterized? Required filters present where specified?" in (
            lines
        )
        assert (
            "- Generated files (generated/one.py, generated/two.py): "
            "do not edit manually; re-run build tools after schema changes" in lines
        )

    def test_sre_production_environment_bullets_stay_separate(
        self, rendered: dict[str, str]
    ) -> None:
        """A bullet whose line ends in an inline `{% endif %}` keeps its newline."""
        lines = rendered["sre"].splitlines()

        assert "- Server application managing 42 production records" in lines
        assert "- Rollback available via deployment pipeline" in lines
        assert "- Data persistence via sqlite" in lines

    def test_architect_intent_paragraph_is_separated_from_next_section(
        self, rendered: dict[str, str]
    ) -> None:
        """The blank line Markdown needs between two blocks survives the render."""
        lines = rendered["architect"].splitlines()
        index = lines.index("**Key abstractions:**")

        assert lines[index - 1] == ""
        assert lines[index - 2].startswith("**Architectural intent:**")

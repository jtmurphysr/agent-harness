"""Tests for cli/render.py."""

import functools
import re
import tempfile
from pathlib import Path

import pytest

from cli.render import RenderError, render_agents

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"

# A context whose lists are long enough that a collapsed render is detectable, and
# whose invariants are ordered so that each role's filtered subset sits at
# positions the unfiltered list would number differently. `loop.index` over the
# unfiltered list would print 2, 4, 5 for engineer, 3, 5 for architect and 1, 4 for
# sre; over the filtered subset it prints 1, 2, 3 and 1, 2 and 1, 2.
SHAPE_CONTEXT = """---
project:
  name: "shape-project"
  description: "A project used to assert the shape of the rendered output."

stack:
  language: "python"
  framework: "fastapi"
  database: "postgresql"
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
  user_data_recoverable: false

invariants:
  - id: "inv_delta"
    rule: "Delta rule, irreversibility."
    severity: "irreversibility"
  - id: "inv_alpha"
    rule: "Alpha rule, correctness."
    severity: "correctness"
  - id: "inv_echo"
    rule: "Echo rule, performance."
    severity: "performance"
  - id: "inv_bravo"
    rule: "Bravo rule, data loss."
    severity: "data_loss"
  - id: "inv_charlie"
    rule: "Charlie rule, data consistency."
    severity: "data_consistency"

sharp_edges:
  - location: "edge/one.py"
    issue: "Issue one"
    fix: "Fix one"
  - location: "edge/two.py"
    issue: "Issue two"
    fix: "Fix two"
  - location: "edge/three.py"
    issue: "Issue three"
    fix: "Fix three"

structural_decisions:
  - decision: "Decision alpha"
    rationale: "Rationale alpha"
  - decision: "Decision beta"
    rationale: "Rationale beta"

becoming:
  - "Goal alpha"
  - "Goal beta"

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

Context body.
"""


@functools.cache
def _render_shape_agents() -> dict[str, str]:
    """Render engineer, architect and sre from the real templates + SHAPE_CONTEXT.

    Cached: the three files are identical for every test in this module, and the
    scratch directory is thrown away once their text has been read.
    """
    with tempfile.TemporaryDirectory() as scratch:
        tmp_path = Path(scratch)
        context_file = tmp_path / "project_context.md"
        context_file.write_text(SHAPE_CONTEXT)
        output_dir = tmp_path / "agents"
        render_agents(context_file, TEMPLATES_DIR, output_dir, update_lock=False)
        return {
            role: (output_dir / f"{role}.md").read_text()
            for role in ("engineer", "architect", "sre")
        }


def _item_numbers(block: list[str]) -> list[int]:
    """Return the leading `N.` ordinal of every line in an invariant block."""
    numbers = []
    for line in block:
        match = re.match(r"(\d+)\. ", line)
        assert match is not None, f"invariant line is not numbered: {line!r}"
        numbers.append(int(match.group(1)))
    return numbers


def _block_after(content: str, marker: str) -> list[str]:
    """Return the lines of the first non-empty block following `marker`.

    Blank lines between the marker and the block are skipped; collection stops at
    the first blank line after it. A collapsed render therefore shows up as a
    one-element list whose single element carries every item's text.
    """
    lines = content.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == marker]
    assert starts, f"marker not found in rendered output: {marker!r}"
    i = starts[0] + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    block = []
    while i < len(lines) and lines[i].strip():
        block.append(lines[i])
        i += 1
    return block


class TestRenderedListShape:
    """The rendered agent files must put each list item on its own physical line.

    `trim_blocks=True` (renderer/compose.py) deletes the newline immediately after
    a block tag. A loop body that ends in `{% endif %}{% endfor %}` therefore loses
    the newline that separates one item from the next, and the whole list renders
    as one line. The same setting made `{% if %}`-guarded checklist bullets run
    into the bullet below them.

    Separately, filtering inside the loop (`{% for x in xs %}{% if ... %}`) leaves
    `loop.index` counting the *unfiltered* list, so a role's invariants printed as
    1, 3, 5 — a visible gap that reads as two dropped items.

    These tests render the real shipped templates, so a future template edit that
    re-collapses a list fails here rather than shipping to every generated project.
    validate_harness.py Pass 3 cannot catch it: it diffs the rendered agents against
    a fresh render of the same templates, so it is self-consistent by construction.
    """

    @pytest.fixture
    def rendered(self) -> dict[str, str]:
        """The three agent files rendered from the real templates."""
        return _render_shape_agents()

    # --- invariants: one per line, numbered contiguously from 1 ----------------

    def test_engineer_invariants_render_one_per_line(self, rendered: dict[str, str]) -> None:
        """Engineer's three matching invariants occupy three separate lines."""
        block = _block_after(rendered["engineer"], "**Critical correctness invariants:**")
        assert len(block) == 3, block
        assert "inv_alpha" in block[0]
        assert "inv_bravo" in block[1]
        assert "inv_charlie" in block[2]

    def test_engineer_invariant_numbering_counts_the_filtered_set(
        self, rendered: dict[str, str]
    ) -> None:
        """Numbering is 1, 2, 3 — not the 2, 4, 5 of the unfiltered list."""
        block = _block_after(rendered["engineer"], "**Critical correctness invariants:**")
        assert _item_numbers(block) == [1, 2, 3]

    def test_architect_invariants_render_one_per_line(self, rendered: dict[str, str]) -> None:
        """Architect's two matching invariants occupy two separate lines."""
        block = _block_after(rendered["architect"], "**Critical architectural invariants:**")
        assert len(block) == 2, block
        assert "inv_echo" in block[0]
        assert "inv_charlie" in block[1]

    def test_architect_invariant_numbering_counts_the_filtered_set(
        self, rendered: dict[str, str]
    ) -> None:
        """Numbering is 1, 2 — not the 3, 5 of the unfiltered list."""
        block = _block_after(rendered["architect"], "**Critical architectural invariants:**")
        assert _item_numbers(block) == [1, 2]

    def test_sre_invariants_render_one_per_line(self, rendered: dict[str, str]) -> None:
        """SRE's two matching invariants occupy two separate lines."""
        block = _block_after(rendered["sre"], "**Critical production invariants:**")
        assert len(block) == 2, block
        assert "inv_delta" in block[0]
        assert "inv_bravo" in block[1]

    def test_sre_invariant_numbering_counts_the_filtered_set(
        self, rendered: dict[str, str]
    ) -> None:
        """Numbering is 1, 2 — not the 1, 4 of the unfiltered list."""
        block = _block_after(rendered["sre"], "**Critical production invariants:**")
        assert _item_numbers(block) == [1, 2]

    def test_no_role_renumbers_an_invariant_above_its_own_count(
        self, rendered: dict[str, str]
    ) -> None:
        """No numbered invariant line carries an index past the block's length.

        This is the gap the symptom reported — 1, 3, 5 for a three-item set.
        """
        markers = {
            "engineer": "**Critical correctness invariants:**",
            "architect": "**Critical architectural invariants:**",
            "sre": "**Critical production invariants:**",
        }
        for role, marker in markers.items():
            block = _block_after(rendered[role], marker)
            numbers = _item_numbers(block)
            assert numbers == list(range(1, len(block) + 1)), (role, numbers)

    # --- sharp edges -----------------------------------------------------------

    def test_engineer_sharp_edges_render_one_per_line(self, rendered: dict[str, str]) -> None:
        """Each sharp edge gets its own line, carrying location, issue and fix."""
        block = _block_after(rendered["engineer"], "**Known sharp edges:**")
        assert len(block) == 3, block
        for line, name in zip(block, ("one", "two", "three"), strict=True):
            assert line.startswith(f"- edge/{name}.py — ")
            assert f"Issue {name}" in line
            assert f"Fix {name}" in line

    def test_sre_operational_pain_points_render_one_per_line(
        self, rendered: dict[str, str]
    ) -> None:
        """SRE lists the same sharp edges, one per line, without the fix."""
        block = _block_after(rendered["sre"], "**Known operational pain points:**")
        assert len(block) == 3, block
        for line, name in zip(block, ("one", "two", "three"), strict=True):
            assert line == f"- edge/{name}.py: Issue {name}"

    # --- structural decisions, becoming, key abstractions ----------------------

    def test_engineer_structural_decisions_render_one_per_line(
        self, rendered: dict[str, str]
    ) -> None:
        """Pass 2's checklist keeps its fixed bullet and one bullet per decision."""
        block = _block_after(rendered["engineer"], "**Pass 2 — Coverage checklist:**")
        assert len(block) == 3, block
        assert block[1] == "- Decision alpha: Rationale alpha"
        assert block[2] == "- Decision beta: Rationale beta"

    def test_architect_structural_decisions_render_one_per_line(
        self, rendered: dict[str, str]
    ) -> None:
        """Architect renders decision and rationale one per line."""
        block = _block_after(
            rendered["architect"], "**Known structural decisions worth preserving:**"
        )
        assert block == [
            "- Decision alpha — Rationale alpha",
            "- Decision beta — Rationale beta",
        ]

    def test_architect_becoming_goals_render_one_per_line(self, rendered: dict[str, str]) -> None:
        """The 12-month horizon list is one goal per line."""
        block = _block_after(rendered["architect"], "**What this is becoming (12-month horizon):**")
        assert block == ["- Goal alpha", "- Goal beta"]

    def test_architect_key_abstractions_render_one_per_line(self, rendered: dict[str, str]) -> None:
        """Data layer, framework and each high-blast-radius file get their own line."""
        block = _block_after(rendered["architect"], "**Key abstractions:**")
        assert len(block) == 4, block
        assert block[0].startswith("- **Data layer** (postgresql) — ")
        assert block[1].startswith("- **fastapi framework** — ")
        assert block[2].startswith("- **blast/one.py** — ")
        assert block[3].startswith("- **blast/two.py** — ")

    def test_architect_intent_stays_its_own_markdown_block(self, rendered: dict[str, str]) -> None:
        """A blank line separates the intent paragraph from the next heading.

        The inline `{% endif %}` that closed the intent chain ate it, so the two
        merged into a single Markdown paragraph.
        """
        content = rendered["architect"]
        assert "production data management.\n\n**Key abstractions:**" in content

    # --- {% if %}-guarded bullets ---------------------------------------------

    def test_engineer_pass_one_checklist_renders_one_bullet_per_line(
        self, rendered: dict[str, str]
    ) -> None:
        """The database and generated-files bullets do not run into each other."""
        block = _block_after(rendered["engineer"], "**Pass 1 — Correctness checklist:**")
        assert len(block) == 3, block
        assert block[1].startswith("- Database queries:")
        assert block[2].startswith("- Generated files (generated/one.py, generated/two.py):")

    def test_engineer_question_set_renders_one_bullet_per_line(
        self, rendered: dict[str, str]
    ) -> None:
        """The guarded database question does not swallow the bullet after it."""
        block = _block_after(rendered["engineer"], "## Your Standing Question Set")
        assert len(block) == 6, block
        assert block[4].startswith("- **What's the database query doing?**")
        assert block[5].startswith("- **What would surprise the next person?**")

    def test_engineer_what_you_dont_do_renders_one_bullet_per_line(
        self, rendered: dict[str, str]
    ) -> None:
        """The guarded deploy bullet does not swallow the bullet after it."""
        block = _block_after(rendered["engineer"], "## What You Don't Do")
        assert block == [
            "- Architectural critique. That's the architect.",
            "- Deploy/release concerns. That's the deploy agent.",
            "- Generic style commentary unrelated to bugs.",
        ]

    def test_sre_production_environment_renders_one_bullet_per_line(
        self, rendered: dict[str, str]
    ) -> None:
        """Surface, rollback and persistence bullets are three separate lines."""
        block = _block_after(rendered["sre"], "**Production environment:**")
        assert block == [
            "- Server application",
            "- Rollback available via deployment pipeline",
            "- Data persistence via postgresql with no server-side recovery",
        ]

    def test_sre_question_set_renders_one_bullet_per_line(self, rendered: dict[str, str]) -> None:
        """The surface branch, the blast-radius line and both guarded bullets separate."""
        block = _block_after(rendered["sre"], "## Your Standing Question Set")
        assert len(block) == 6, block
        assert block[1].startswith("- **Is the rollback plan tested?**")
        assert block[2] == "- **What's the blast radius?** Service unavailable or data corruption?"
        assert block[3].startswith("- **Are data changes reversible?**")
        assert block[4].startswith("- **What's the user data recovery path?**")
        assert block[5].startswith("- **Is there monitoring/alerting for this failure mode?**")

    def test_architect_question_set_renders_one_bullet_per_line(
        self, rendered: dict[str, str]
    ) -> None:
        """Both guarded questions render on their own lines."""
        block = _block_after(rendered["architect"], "## Your Standing Question Set")
        assert len(block) == 6, block
        assert block[2].startswith("- **Where is the system fighting its framework's grain?**")
        assert block[3].startswith("- **Is the data model the right shape for the access")

    def test_architect_what_you_dont_do_renders_one_bullet_per_line(
        self, rendered: dict[str, str]
    ) -> None:
        """The guarded SRE bullet does not swallow the bullet after it."""
        block = _block_after(rendered["architect"], "## What You Don't Do")
        assert block == [
            "- Implementation critique. That's the engineer.",
            "- Deploy/release safety. That's the SRE.",
            "- Micro-optimizations. Focus on structural decisions.",
        ]

    # --- a catch-all that does not depend on knowing every section -------------

    def test_no_rendered_line_carries_two_markdown_bullets(self, rendered: dict[str, str]) -> None:
        """No line contains a second `- ` bullet marker glued onto the first.

        The symptom's signature. This catches a collapse in a section none of the
        tests above names, including one a future template edit introduces.
        """
        for role, content in rendered.items():
            for number, line in enumerate(content.splitlines(), start=1):
                if not line.startswith("- "):
                    continue
                assert not re.search(r"\S- \*\*", line), f"{role}.md:{number}: {line}"

    def test_no_rendered_line_carries_two_numbered_invariants(
        self, rendered: dict[str, str]
    ) -> None:
        """No line contains a second `N. ` item glued onto the first."""
        for role, content in rendered.items():
            for number, line in enumerate(content.splitlines(), start=1):
                if not re.match(r"\d+\. ", line):
                    continue
                assert not re.search(r"`\d+\. ", line), f"{role}.md:{number}: {line}"


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

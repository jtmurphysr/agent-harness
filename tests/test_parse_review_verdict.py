"""Tests for scripts/parse_review_verdict.py — the reviewer CI gate's verify step.

The exit code IS the contract: 0 lets `review-<role>` succeed, 1 and 2 both fail
it. Every test here asserts on the exit code first and the comment body second,
because the comment is advisory and the exit code is what stops a merge.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from renderer.validators import ProjectContextError
from scripts.parse_review_verdict import (
    EXIT_BLOCK,
    EXIT_OK,
    EXIT_PARSE_ERROR,
    build_comment,
    load_project_invariants,
    main,
    marker,
)

# A minimal but schema-valid project_context.md. renderer.validators enforces the
# full schema, so this cannot be trimmed to just `invariants:`.
CONTEXT_TEMPLATE = """---
project:
  name: "fixture-project"
  description: "A fixture project used to exercise the reviewer verdict gate."

stack:
  language: "python"
  framework: "fastapi"
  database: "sqlite"
  primary_files:
    high_blast_radius:
      - ".github/workflows/ci.yml"
    generated:
      - ".claude/agents/engineer.md"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants:
{invariants}

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

# fixture-project — project context
"""

INVARIANT_BLOCK = """  - id: "gate_fails_closed"
    rule: "Every gate that can block a merge must fail closed."
    severity: "irreversibility"
  - id: "layering"
    rule: "No module imports upward."
    severity: "correctness"
"""


@pytest.fixture
def context(tmp_path: Path) -> Path:
    """A valid project_context.md declaring `gate_fails_closed` and `layering`."""
    path = tmp_path / "project_context.md"
    path.write_text(CONTEXT_TEMPLATE.format(invariants=INVARIANT_BLOCK), encoding="utf-8")
    return path


def run(
    monkeypatch: pytest.MonkeyPatch,
    review: str,
    context_path: Path,
    reviewer: str = "engineer",
) -> int:
    """Feed *review* to main() on stdin and return its exit code."""
    monkeypatch.setattr("sys.stdin", _Stdin(review))
    return main(["--reviewer", reviewer, "--context", str(context_path)])


class _Stdin:
    """The one method main() uses on stdin."""

    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


PASS_REVIEW = """## Good
The change is small and the tests cover it.

## Verdict
VERDICT: PASS
BLOCKING:
WARNINGS:
"""

WARN_REVIEW = """## Ugly
Naming drift.

## Verdict
VERDICT: WARN
BLOCKING:
WARNINGS:
- `_flush` has no docstring
- the fixture name shadows the module
"""

BLOCK_REVIEW = """## Bad
The gate opens on a lookup miss.

## Verdict
VERDICT: BLOCK
BLOCKING:
- ci.yml:301 treats a skipped reviewer as success (invariant: gate_fails_closed)
WARNINGS:
- the comment marker is not documented
"""


class TestExitCodes:
    """The six named acceptance cases from the issue, plus their neighbours."""

    def test_pass_verdict_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch, context: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(monkeypatch, PASS_REVIEW, context) == EXIT_OK

        out = capsys.readouterr().out
        assert out.splitlines()[0] == "PASS"
        # A silent pass posts nothing -- there is no comment body after the
        # severity line and its blank separator.
        assert out == "PASS\n\n"

    def test_warn_verdict_exits_zero_and_prints_warnings(
        self, monkeypatch: pytest.MonkeyPatch, context: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(monkeypatch, WARN_REVIEW, context) == EXIT_OK

        out = capsys.readouterr().out
        assert out.splitlines()[0] == "WARN"
        assert marker("engineer") in out
        assert "**WARNINGS**" in out
        assert "`_flush` has no docstring" in out
        assert "the fixture name shadows the module" in out
        # A WARN is not a block and must not claim to be one.
        assert "**BLOCKING**" not in out
        assert "hard merge-fail" not in out

    def test_block_verdict_exits_one_and_prints_blocking(
        self, monkeypatch: pytest.MonkeyPatch, context: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(monkeypatch, BLOCK_REVIEW, context) == EXIT_BLOCK

        out = capsys.readouterr().out
        assert out.splitlines()[0] == "BLOCK"
        assert marker("engineer") in out
        assert "**BLOCKING**" in out
        assert "ci.yml:301 treats a skipped reviewer as success" in out
        # The citation survives into the comment -- it is what makes the finding
        # answerable rather than a matter of taste.
        assert "(invariant: gate_fails_closed)" in out
        assert "hard merge-fail" in out
        # A BLOCK carries its WARNINGS too; they are not dropped.
        assert "the comment marker is not documented" in out

    def test_missing_verdict_block_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, context: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        review = "## Good\nLooks fine to me. Nothing critical here.\n"

        assert run(monkeypatch, review, context) == EXIT_PARSE_ERROR

        captured = capsys.readouterr()
        assert captured.out.splitlines()[0] == "ERROR"
        assert "parse error" in captured.out
        assert "no VERDICT: line" in captured.out
        assert "no VERDICT: line" in captured.err

    def test_block_without_citation_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, context: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        review = """## Verdict
VERDICT: BLOCK
BLOCKING:
- I do not like the shape of this
WARNINGS:
"""

        assert run(monkeypatch, review, context) == EXIT_PARSE_ERROR

        out = capsys.readouterr().out
        assert out.splitlines()[0] == "ERROR"
        assert "no citable BLOCKING finding" in out

    def test_unknown_invariant_id_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, context: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        review = """## Verdict
VERDICT: BLOCK
BLOCKING:
- the worker drops a verdict (invariant: verdicts_are_durable)
WARNINGS:
"""

        assert run(monkeypatch, review, context) == EXIT_PARSE_ERROR

        out = capsys.readouterr().out
        assert out.splitlines()[0] == "ERROR"
        assert "verdicts_are_durable" in out
        # The message names what IS declared, so the reviewer can correct itself.
        assert "gate_fails_closed" in out

    def test_empty_output_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, context: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A reviewer that said nothing at all did not review."""
        assert run(monkeypatch, "", context) == EXIT_PARSE_ERROR
        assert capsys.readouterr().out.splitlines()[0] == "ERROR"

    def test_template_echo_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, context: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Echoing `PASS | WARN | BLOCK` is a parse failure, not a PASS."""
        review = "## Verdict\nVERDICT: PASS | WARN | BLOCK\nBLOCKING:\nWARNINGS:\n"

        assert run(monkeypatch, review, context) == EXIT_PARSE_ERROR
        assert capsys.readouterr().out.splitlines()[0] == "ERROR"


class TestReviewerRole:
    """The role reaches both the parser and the comment marker."""

    @pytest.mark.parametrize("reviewer", ["engineer", "architect", "sre"])
    def test_marker_is_per_role(
        self,
        monkeypatch: pytest.MonkeyPatch,
        context: Path,
        capsys: pytest.CaptureFixture[str],
        reviewer: str,
    ) -> None:
        assert run(monkeypatch, BLOCK_REVIEW, context, reviewer=reviewer) == EXIT_BLOCK

        out = capsys.readouterr().out
        assert out.startswith("BLOCK\n\n" + marker(reviewer))
        assert f"`{reviewer}`" in out

    def test_unknown_role_is_rejected(self, monkeypatch: pytest.MonkeyPatch, context: Path) -> None:
        """A typo in ci.yml fails the job rather than labelling a phantom role."""
        with pytest.raises(SystemExit) as exc:
            run(monkeypatch, PASS_REVIEW, context, reviewer="enginer")
        assert exc.value.code == 2


class TestInvariantLoading:
    """Reading the declared ids is part of the gate, so it fails closed."""

    def test_ids_are_read_in_file_order(self, context: Path) -> None:
        assert load_project_invariants(context) == ["gate_fails_closed", "layering"]

    def test_repo_context_declares_its_own_invariants(self) -> None:
        """The default context is this repository's, and it must load."""
        ids = load_project_invariants(Path(".factory/project_context.md"))
        assert "gate_fails_closed" in ids
        assert "rendered_agents_match_templates" in ids

    def test_entry_without_id_is_rejected(self, tmp_path: Path) -> None:
        """Shape is the validator's job; this asserts the delegation holds."""
        path = tmp_path / "project_context.md"
        path.write_text(
            CONTEXT_TEMPLATE.format(
                invariants='  - rule: "an invariant nobody can cite"\n    severity: "correctness"\n'
            ),
            encoding="utf-8",
        )

        with pytest.raises(ProjectContextError, match="missing required fields: id"):
            load_project_invariants(path)

    def test_missing_context_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An unreadable invariant list cannot check a citation, so it blocks."""
        absent = tmp_path / "nowhere" / "project_context.md"

        assert run(monkeypatch, PASS_REVIEW, absent) == EXIT_PARSE_ERROR

        captured = capsys.readouterr()
        assert captured.out.splitlines()[0] == "ERROR"
        assert "could not read declared invariant ids" in captured.out
        assert "could not read declared invariant ids" in captured.err


class TestCommentBody:
    """build_comment() is what a retrying agent reads."""

    def test_pass_renders_nothing(self) -> None:
        from reviewers.verdicts import ParsedVerdict

        verdict = ParsedVerdict(
            reviewer="sre",
            severity="PASS",
            good=None,
            bad=None,
            ugly=None,
            closing_question=None,
            findings=[],
        )
        assert build_comment(verdict) == ""

    def test_block_with_no_warnings_omits_the_warnings_heading(
        self, monkeypatch: pytest.MonkeyPatch, context: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        review = """## Verdict
VERDICT: BLOCK
BLOCKING:
- cli/render.py imports stonehaven (invariant: layering)
WARNINGS:
"""

        assert run(monkeypatch, review, context) == EXIT_BLOCK

        out = capsys.readouterr().out
        assert "**BLOCKING**" in out
        assert "**WARNINGS**" not in out

    def test_every_non_pass_body_tells_a_retry_what_to_do(
        self, monkeypatch: pytest.MonkeyPatch, context: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(monkeypatch, WARN_REVIEW, context) == EXIT_OK
        assert "the reviewer, not the implementing" in capsys.readouterr().out


class TestInvokedAsCi:
    """The CI step runs this as a process, so prove the process contract too.

    In-process tests cannot show that `python scripts/parse_review_verdict.py`
    resolves `reviewers.verdicts` from a script-relative sys.path, nor that the
    parser's structlog records land on stderr rather than on the line the step
    reads as a verdict.
    """

    @staticmethod
    def _run(review: str) -> subprocess.CompletedProcess[str]:
        """Invoke the script the way ci.yml does — default context, stdin, no cwd assumptions."""
        return subprocess.run(
            [sys.executable, "scripts/parse_review_verdict.py", "--reviewer", "sre"],
            input=review,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_block_exits_one_with_severity_alone_on_the_first_line(self) -> None:
        result = self._run(BLOCK_REVIEW)

        assert result.returncode == EXIT_BLOCK
        assert result.stdout.splitlines()[0] == "BLOCK"
        assert marker("sre") in result.stdout
        # The parser logs on every parse. Those records are evidence, but they
        # belong on stderr -- on stdout they would be read as the verdict.
        assert "Verdict parsed successfully" in result.stderr

    def test_pass_exits_zero_as_a_process(self) -> None:
        result = self._run(PASS_REVIEW)

        assert result.returncode == EXIT_OK
        assert result.stdout == "PASS\n\n"

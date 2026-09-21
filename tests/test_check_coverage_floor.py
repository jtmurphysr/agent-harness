"""Tests for the per-file coverage floor gate.

`scripts/check_coverage_floor.py` is the mechanism behind AGENTS.md's 85% floor
and until this file existed it had no unit tests at all: CI ran it end-to-end
and read the exit code, which only ever exercised the all-pass path. Every
branch that matters -- a shortfall, a missing input, an honoured exception, an
exception with no tracking issue, an empty report -- had never run.

The most important assertion here is `test_file_percentages_reads_raw_float_not_display`:
the whole reason the module exists is that it reads `percent_covered` and never
`percent_covered_display`, and a fixture where the two disagree is the only way
to prove it.
"""

import ast
import json
from pathlib import Path

import pytest

from scripts import check_coverage_floor as ccf


def _report(files: dict[str, tuple[float, str, int]]) -> dict[str, object]:
    """Build a `coverage json`-shaped payload.

    Args:
        files: path -> (percent_covered, percent_covered_display, missing_lines).
    """
    return {
        "files": {
            path: {
                "summary": {
                    "percent_covered": percent,
                    "percent_covered_display": display,
                    "missing_lines": missing,
                }
            }
            for path, (percent, display, missing) in files.items()
        },
        "totals": {"percent_covered": 100.0},
    }


def _write_report(tmp_path: Path, files: dict[str, tuple[float, str, int]]) -> Path:
    """Write a coverage report fixture to *tmp_path* and return its path."""
    target = tmp_path / "coverage.json"
    target.write_text(json.dumps(_report(files)), encoding="utf-8")
    return target


class TestLoadCoverage:
    """`load_coverage` is the only I/O in the module."""

    def test_load_coverage_returns_parsed_json(self, tmp_path: Path) -> None:
        """A well-formed report round-trips into a dict."""
        path = _write_report(tmp_path, {"a.py": (90.0, "90%", 1)})

        data = ccf.load_coverage(path)

        assert data["files"]["a.py"]["summary"]["percent_covered"] == 90.0

    def test_load_coverage_raises_on_malformed_json(self, tmp_path: Path) -> None:
        """A truncated report is a hard error, not a silent empty result."""
        path = tmp_path / "coverage.json"
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            ccf.load_coverage(path)


class TestFilePercentages:
    """The raw-float contract -- the reason this module exists."""

    def test_file_percentages_reads_raw_float_not_display(self) -> None:
        """`percent_covered` wins over the pre-rounded `percent_covered_display`.

        84.69 prints as "85%" at coverage's default integer precision. Reading
        the display string is exactly the bug the gate was written to close, so
        the fixture deliberately makes the two fields disagree.
        """
        data = _report({"conformance/monday_arc_test.py": (84.69, "85%", 13)})

        percentages = ccf.file_percentages(data)

        assert percentages == {"conformance/monday_arc_test.py": 84.69}
        assert percentages["conformance/monday_arc_test.py"] < ccf.FLOOR

    def test_file_percentages_empty_files_map_is_empty_dict(self) -> None:
        """No `files` key at all yields an empty mapping rather than raising."""
        assert ccf.file_percentages({}) == {}

    def test_file_percentages_coerces_integral_values_to_float(self) -> None:
        """An integer `percent_covered` still comes back as a float."""
        data = _report({"a.py": (100, "100%", 0)})

        result = ccf.file_percentages(data)

        assert isinstance(result["a.py"], float)
        assert result["a.py"] == 100.0


class TestMissingStatements:
    """`_missing_statements` feeds the table's rightmost column."""

    def test_missing_statements_reads_missing_lines(self) -> None:
        """The count comes straight from `summary.missing_lines`."""
        data = _report({"a.py": (50.0, "50%", 7)})

        assert ccf._missing_statements(data) == {"a.py": 7}

    def test_missing_statements_defaults_to_zero_when_absent(self) -> None:
        """A summary without `missing_lines` degrades to 0, it does not raise."""
        data: dict[str, object] = {"files": {"a.py": {"summary": {"percent_covered": 50.0}}}}

        assert ccf._missing_statements(data) == {"a.py": 0}


class TestFloorFor:
    """`_floor_for` is the only place EXCEPTIONS changes the comparison."""

    def test_floor_for_unlisted_path_is_the_global_floor(self) -> None:
        """A path with no entry is held to FLOOR."""
        assert ccf._floor_for("github/webhook.py") == ccf.FLOOR

    def test_floor_for_listed_path_is_the_exception_minimum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An EXCEPTIONS entry lowers the floor for that path only."""
        monkeypatch.setattr(ccf, "EXCEPTIONS", {"legacy/thing.py": (60.0, "see #123, expires v2")})

        assert ccf._floor_for("legacy/thing.py") == 60.0
        assert ccf._floor_for("other/thing.py") == ccf.FLOOR


class TestPrintHelpers:
    """The printed output is the gate's entire diagnostic surface."""

    def test_print_exceptions_says_none_when_empty(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An empty EXCEPTIONS list is stated explicitly, not left blank."""
        ccf._print_exceptions()

        out = capsys.readouterr().out
        assert "(none" in out
        assert "85.00%" in out

    def test_print_exceptions_lists_every_active_entry(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Active entries print on every run so the list cannot go quiet."""
        monkeypatch.setattr(
            ccf,
            "EXCEPTIONS",
            {
                "b.py": (70.0, "tracked in #2"),
                "a.py": (60.0, "tracked in #1"),
            },
        )

        ccf._print_exceptions()

        out = capsys.readouterr().out
        assert out.index("a.py") < out.index("b.py")  # sorted
        assert "60.00%" in out
        assert "tracked in #1" in out

    def test_print_table_pads_to_the_longest_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Column width follows the longest path, and percents print at 2dp."""
        ccf._print_table([("a.py", 84.69, 13), ("a/much/longer/path.py", 99.0, 1)])

        lines = capsys.readouterr().out.splitlines()
        assert "84.69%" in lines[2]
        assert "99.00%" in lines[3]
        assert len(lines[2]) == len(lines[3])

    def test_print_table_width_never_shrinks_below_the_header(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Paths shorter than "Path" must not clip the header."""
        ccf._print_table([("a", 1.0, 1)])

        assert "Path" in capsys.readouterr().out


class TestMainExitCodes:
    """`main`'s three documented exit codes, plus the EXCEPTIONS paths."""

    def test_main_returns_zero_when_every_file_clears_the_floor(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 0: the happy path CI has always taken."""
        path = _write_report(tmp_path, {"a.py": (85.0, "85%", 0), "b.py": (99.5, "100%", 1)})

        assert ccf.main(["--input", str(path)]) == 0

        out = capsys.readouterr().out
        assert "All 2 files at or above their floor" in out

    def test_main_returns_one_on_a_shortfall(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 1: 84.69% is below 85.00% even though it displays as "85%"."""
        path = _write_report(tmp_path, {"low.py": (84.69, "85%", 13), "ok.py": (99.0, "99%", 1)})

        assert ccf.main(["--input", str(path)]) == 1

        out = capsys.readouterr().out
        assert "1 file(s) below the floor" in out
        assert "low.py: 84.69% < 85.00% (FLOOR)" in out
        assert "CI FAILED" in out

    def test_main_returns_two_when_the_input_is_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 2: a missing report is distinct from a failing one."""
        missing = tmp_path / "nope.json"

        assert ccf.main(["--input", str(missing)]) == 2

        out = capsys.readouterr().out
        assert "not found" in out
        assert "coverage json -o coverage.json" in out

    def test_main_defaults_its_input_to_coverage_json_in_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no `--input`, the gate reads ./coverage.json."""
        _write_report(tmp_path, {"a.py": (90.0, "90%", 1)})
        monkeypatch.chdir(tmp_path)

        assert ccf.main([]) == 0

    def test_main_rejects_an_exception_with_no_tracking_issue_before_any_io(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An unowned exemption is a config defect: exit 1, and never exit 2.

        The input path deliberately does not exist. If the self-check ran after
        the I/O this would return 2, so the exit code proves the ordering.
        """
        monkeypatch.setattr(ccf, "EXCEPTIONS", {"a.py": (60.0, "temporarily low, will fix")})

        assert ccf.main(["--input", str(tmp_path / "absent.json")]) == 1

        out = capsys.readouterr().out
        assert "EXCEPTIONS entries with no tracking issue" in out
        assert "a.py" in out

    def test_main_honours_an_exception_that_covers_the_shortfall(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A file below FLOOR but above its exception minimum passes."""
        monkeypatch.setattr(ccf, "EXCEPTIONS", {"low.py": (60.0, "tracked in #42, expires v2")})
        path = _write_report(tmp_path, {"low.py": (70.0, "70%", 20)})

        assert ccf.main(["--input", str(path)]) == 0

        out = capsys.readouterr().out
        assert "allowed minimum 60.00%" in out
        assert "tracked in #42" in out

    def test_main_still_fails_a_file_below_its_exception_minimum(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An exception lowers the bar; it does not remove it."""
        monkeypatch.setattr(ccf, "EXCEPTIONS", {"low.py": (80.0, "tracked in #42, expires v2")})
        path = _write_report(tmp_path, {"low.py": (70.0, "70%", 20)})

        assert ccf.main(["--input", str(path)]) == 1

        out = capsys.readouterr().out
        assert "low.py: 70.00% < 80.00% (EXCEPTIONS minimum)" in out
        assert "tracked in #42" in out

    def test_main_fails_when_nothing_was_measured(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An empty `files` map is a broken run, not a clean one."""
        path = tmp_path / "coverage.json"
        path.write_text(json.dumps({"files": {}, "totals": {}}), encoding="utf-8")

        assert ccf.main(["--input", str(path)]) == 1

        assert "nothing was measured" in capsys.readouterr().out

    def test_main_sorts_the_table_worst_first(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The report leads with the file closest to failing."""
        path = _write_report(
            tmp_path,
            {
                "high.py": (99.0, "99%", 1),
                "mid.py": (90.0, "90%", 5),
                "lowest.py": (86.0, "86%", 9),
            },
        )

        assert ccf.main(["--input", str(path)]) == 0

        out = capsys.readouterr().out
        assert out.index("lowest.py") < out.index("mid.py") < out.index("high.py")


class TestModuleInvariants:
    """Guardrails on the module's own configuration."""

    def test_every_shipped_exception_names_a_tracking_issue(self) -> None:
        """The rule the gate enforces at runtime also holds for what ships."""
        for path, (_, reason) in ccf.EXCEPTIONS.items():
            assert ccf._ISSUE_REF.search(reason), f"{path} exemption names no issue"

    def test_percent_covered_display_is_never_read(self) -> None:
        """LESSON 11 applied: forbid the rounded field with a test, not a comment.

        A reader adding `percent_covered_display` anywhere in this module would
        reintroduce the exact defect (#73) it was written to close.
        """
        tree = ast.parse(Path(ccf.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    node.body.pop(0)
                    if not node.body:
                        node.body.append(ast.Pass())

        executable = ast.unparse(tree)  # comments and docstrings, which name it, are gone
        assert "percent_covered" in executable
        assert "percent_covered_display" not in executable

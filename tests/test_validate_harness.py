"""Tests for the harness structural linter.

`scripts/validate_harness.py` is one of the four required status checks on
`main` and, until this file existed, had no unit tests. CI invoked it
end-to-end and read the exit code, which exercises exactly one path through
each pass: the clean one. Every branch that reports something -- a boundary
violation, a new cycle, omit drift, rendered-agent drift, and the
`files_checked == 0` guard that this linter was itself rewritten for -- had
never run.

From the module's own header: *"A check that cannot fail is a decoration."*
These tests are what make it falsifiable.

Most functions read module-level relative paths (`REPO_ROOT = Path(".")`,
`AGENTS_DIR`, `TEMPLATES_DIR`, `OWN_CONTEXT`), so the fixtures drive them with
`monkeypatch.chdir(tmp_path)` and a synthetic tree rather than by rewriting
globals -- the paths resolve at call time, so the real resolution logic runs.
"""

import ast
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from textwrap import dedent

import pytest

from scripts import validate_harness as vh


@pytest.fixture
def sys_path_guard() -> Iterator[None]:
    """Restore `sys.path` after tests that let `check_rendered_agents` extend it."""
    original = list(sys.path)
    yield
    sys.path[:] = original


def _write(path: Path, source: str) -> Path:
    """Write dedented *source* to *path*, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(source).lstrip(), encoding="utf-8")
    return path


def _pyproject(tmp_path: Path, body: str) -> None:
    """Write a `pyproject.toml` into *tmp_path*."""
    (tmp_path / "pyproject.toml").write_text(dedent(body).lstrip(), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────
# is_stub_only
# ─────────────────────────────────────────────────────────────────


class TestIsStubOnly:
    """Drives Pass 2's "is this module actually implemented?" decision."""

    def test_pass_only_body_is_stub(self, tmp_path: Path) -> None:
        """A function whose whole body is `pass` is a stub."""
        path = _write(tmp_path / "m.py", "def f():\n    pass\n")

        assert vh.is_stub_only(path) is True

    def test_ellipsis_body_is_stub(self, tmp_path: Path) -> None:
        """`...` is the other spelling of an unwritten body."""
        path = _write(tmp_path / "m.py", "def f():\n    ...\n")

        assert vh.is_stub_only(path) is True

    def test_raise_notimplementederror_call_is_stub(self, tmp_path: Path) -> None:
        """`raise NotImplementedError()` -- the call form."""
        path = _write(tmp_path / "m.py", "def f():\n    raise NotImplementedError('soon')\n")

        assert vh.is_stub_only(path) is True

    def test_raise_notimplementederror_bare_name_is_stub(self, tmp_path: Path) -> None:
        """`raise NotImplementedError` -- the bare-name form."""
        path = _write(tmp_path / "m.py", "def f():\n    raise NotImplementedError\n")

        assert vh.is_stub_only(path) is True

    def test_docstring_only_body_is_stub(self, tmp_path: Path) -> None:
        """A docstring is filtered out before the stub test, leaving nothing."""
        path = _write(tmp_path / "m.py", 'def f():\n    """Documented, unimplemented."""\n')

        assert vh.is_stub_only(path) is True

    def test_docstring_plus_real_statement_is_not_stub(self, tmp_path: Path) -> None:
        """A docstring does not launder a real body into a stub."""
        path = _write(
            tmp_path / "m.py",
            '''
            def f():
                """Docstring, then actual logic."""
                return 42
            ''',
        )

        assert vh.is_stub_only(path) is False

    def test_async_function_with_real_body_is_not_stub(self, tmp_path: Path) -> None:
        """`AsyncFunctionDef` is walked alongside `FunctionDef`."""
        path = _write(tmp_path / "m.py", "async def f():\n    return 1\n")

        assert vh.is_stub_only(path) is False

    def test_async_function_with_pass_body_is_stub(self, tmp_path: Path) -> None:
        """The async branch reaches the same stub verdict."""
        path = _write(tmp_path / "m.py", "async def f():\n    pass\n")

        assert vh.is_stub_only(path) is True

    def test_one_real_function_among_stubs_is_not_stub(self, tmp_path: Path) -> None:
        """Any single implemented function disqualifies the whole file."""
        path = _write(
            tmp_path / "m.py",
            """
            def a():
                pass

            def b():
                return 1
            """,
        )

        assert vh.is_stub_only(path) is False

    def test_raise_of_another_exception_is_not_stub(self, tmp_path: Path) -> None:
        """Only `NotImplementedError` counts as "unwritten"."""
        path = _write(tmp_path / "m.py", "def f():\n    raise ValueError('real')\n")

        assert vh.is_stub_only(path) is False

    def test_file_with_no_functions_is_stub(self, tmp_path: Path) -> None:
        """A module of pure declarations has no implemented function in it.

        Documents current behaviour: the walk only inspects function bodies, so
        a constants-only module reads as stub-only and is therefore allowed to
        stay in the omit list.
        """
        path = _write(tmp_path / "m.py", "CONSTANT = 1\n")

        assert vh.is_stub_only(path) is True

    def test_unparseable_file_is_stub(self, tmp_path: Path) -> None:
        """A `SyntaxError` fails safe toward "stub" -- it never reports drift."""
        path = _write(tmp_path / "m.py", "def f(:\n")

        assert vh.is_stub_only(path) is True

    def test_missing_file_is_stub(self, tmp_path: Path) -> None:
        """A path that does not exist fails safe the same way."""
        assert vh.is_stub_only(tmp_path / "absent.py") is True


# ─────────────────────────────────────────────────────────────────
# load_coverage_omit_list
# ─────────────────────────────────────────────────────────────────


class TestLoadCoverageOmitList:
    """Reads `[tool.coverage.run] omit` out of pyproject.toml."""

    def test_returns_the_omit_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A normal omit list comes back as a list of strings."""
        _pyproject(
            tmp_path,
            """
            [tool.coverage.run]
            omit = ["tests/*", "legacy.py"]
            """,
        )
        monkeypatch.chdir(tmp_path)

        assert vh.load_coverage_omit_list() == ["tests/*", "legacy.py"]

    def test_missing_pyproject_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No pyproject means "nothing to check", signalled as None."""
        monkeypatch.chdir(tmp_path)

        assert vh.load_coverage_omit_list() is None

    def test_unparseable_pyproject_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A broken TOML file is swallowed into None rather than crashing CI."""
        (tmp_path / "pyproject.toml").write_text("[tool.coverage.run\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        assert vh.load_coverage_omit_list() is None

    def test_omit_that_is_not_a_list_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A scalar `omit` is malformed config, not a one-entry list."""
        _pyproject(
            tmp_path,
            """
            [tool.coverage.run]
            omit = "tests/*"
            """,
        )
        monkeypatch.chdir(tmp_path)

        assert vh.load_coverage_omit_list() is None

    def test_absent_coverage_section_returns_empty_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid pyproject with no coverage config omits nothing.

        Empty list, not None: the file parsed, so the check *did* run and found
        zero entries. None is reserved for "could not look".
        """
        _pyproject(tmp_path, '[project]\nname = "x"\n')
        monkeypatch.chdir(tmp_path)

        assert vh.load_coverage_omit_list() == []

    def test_returns_none_without_a_toml_parser(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On a runtime with neither tomllib nor tomli, Pass 2 skips."""
        _pyproject(tmp_path, '[tool.coverage.run]\nomit = ["a.py"]\n')
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(vh, "tomllib", None)

        assert vh.load_coverage_omit_list() is None


# ─────────────────────────────────────────────────────────────────
# check_coverage_omit_drift
# ─────────────────────────────────────────────────────────────────


class TestCheckCoverageOmitDrift:
    """Pass 2: implemented modules must not hide inside the omit list."""

    def test_no_pyproject_marks_the_pass_unchecked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`checked` stays False so `main` can say "skipped" rather than "clean"."""
        monkeypatch.chdir(tmp_path)

        result = vh.check_coverage_omit_drift()

        assert result.checked is False
        assert result.clean is True
        assert result.omitted_modules == []

    def test_implemented_module_in_omit_list_is_a_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case the pass exists for."""
        _write(tmp_path / "legacy.py", "def f():\n    return 1\n")
        _pyproject(tmp_path, '[tool.coverage.run]\nomit = ["legacy.py"]\n')
        monkeypatch.chdir(tmp_path)

        result = vh.check_coverage_omit_drift()

        assert result.checked is True
        assert result.clean is False
        assert len(result.drift_violations) == 1
        assert "legacy.py" in result.drift_violations[0]
        assert "is implemented but still in omit list" in result.drift_violations[0]

    def test_stub_module_in_omit_list_is_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unimplemented module may legitimately still be omitted."""
        _write(tmp_path / "planned.py", "def f():\n    raise NotImplementedError\n")
        _pyproject(tmp_path, '[tool.coverage.run]\nomit = ["planned.py"]\n')
        monkeypatch.chdir(tmp_path)

        assert vh.check_coverage_omit_drift().clean is True

    def test_permanent_omit_entry_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`tests/*` and friends are infrastructure, never drift."""
        _pyproject(tmp_path, '[tool.coverage.run]\nomit = ["tests/*", ".venv/*"]\n')
        monkeypatch.chdir(tmp_path)

        result = vh.check_coverage_omit_drift()

        assert result.clean is True
        assert result.omitted_modules == ["tests/*", ".venv/*"]

    def test_non_source_extension_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `.json`/`.md` entry is not a Python module."""
        (tmp_path / "data.json").write_text("{}", encoding="utf-8")
        _pyproject(tmp_path, '[tool.coverage.run]\nomit = ["data.json"]\n')
        monkeypatch.chdir(tmp_path)

        assert vh.check_coverage_omit_drift().clean is True

    def test_directory_wildcard_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`vendor/*` and `vendor/**` are directory patterns, not files."""
        _write(tmp_path / "vendor" / "m.py", "def f():\n    return 1\n")
        _pyproject(tmp_path, '[tool.coverage.run]\nomit = ["vendor/*", "vendor/**"]\n')
        monkeypatch.chdir(tmp_path)

        assert vh.check_coverage_omit_drift().clean is True

    def test_embedded_glob_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A glob that is not a trailing `/*` -- `auth/*.py` -- is also skipped.

        Documents a real blind spot: an implemented module can still be hidden
        behind a glob. The entry falls through the `"*" in omit_entry` branch.
        """
        _write(tmp_path / "auth" / "m.py", "def f():\n    return 1\n")
        _pyproject(tmp_path, '[tool.coverage.run]\nomit = ["auth/*.py"]\n')
        monkeypatch.chdir(tmp_path)

        assert vh.check_coverage_omit_drift().clean is True

    def test_omit_entry_that_does_not_exist_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale path in the omit list is not drift -- there is no module."""
        _pyproject(tmp_path, '[tool.coverage.run]\nomit = ["deleted.py"]\n')
        monkeypatch.chdir(tmp_path)

        assert vh.check_coverage_omit_drift().clean is True

    def test_reports_every_drifted_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Violations accumulate; the pass does not stop at the first."""
        _write(tmp_path / "a.py", "def f():\n    return 1\n")
        _write(tmp_path / "b.py", "def g():\n    return 2\n")
        _pyproject(tmp_path, '[tool.coverage.run]\nomit = ["a.py", "b.py", "tests/*"]\n')
        monkeypatch.chdir(tmp_path)

        assert len(vh.check_coverage_omit_drift().drift_violations) == 2

    def test_this_repo_does_not_omit_scripts(self) -> None:
        """`scripts/*` must never be added to the omit list (issue #36).

        The directory is invisible to coverage's walk because it has no
        `__init__.py`; making that official in `omit` would convert an artefact
        into policy and is exactly the drift this pass exists to catch.
        """
        omit = vh.load_coverage_omit_list()

        assert omit is not None
        assert not any(entry.startswith("scripts") for entry in omit)


# ─────────────────────────────────────────────────────────────────
# get_module_layer / extract_internal_imports / lint_file
# ─────────────────────────────────────────────────────────────────


class TestGetModuleLayer:
    """Maps a path onto a boundary layer, or None if untracked."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            (Path("github/pr.py"), "github"),
            (Path("cli/render.py"), "cli"),
            (Path("renderer/compose.py"), "renderer"),
            (Path("stonehaven/sub/deep.py"), "stonehaven"),
        ],
    )
    def test_directory_module_resolves_to_its_top_level_package(
        self, path: Path, expected: str
    ) -> None:
        """Any depth under a tracked package maps to that package."""
        assert vh.get_module_layer(path) == expected

    def test_top_level_file_named_after_a_module_resolves(self) -> None:
        """A flat `github.py` would be the `github` layer."""
        assert vh.get_module_layer(Path("github.py")) == "github"

    @pytest.mark.parametrize(
        "path",
        [
            Path("scripts/validate_harness.py"),
            Path("tests/test_pr.py"),
            Path("app.py"),
            Path("README.md"),
            Path("templates/engineer.template.md"),
        ],
    )
    def test_untracked_paths_resolve_to_none(self, path: Path) -> None:
        """Files outside the boundary map are not the linter's business."""
        assert vh.get_module_layer(path) is None


class TestExtractInternalImports:
    """Pulls internal module references, with their line numbers, out of an AST."""

    def test_from_import_reports_the_root_package(self) -> None:
        """`from github.pr import PRDiff` is an import of `github`."""
        tree = ast.parse("from github.pr import PRDiff\n")

        assert vh.extract_internal_imports(tree) == [(1, "github")]

    def test_plain_import_reports_the_root_package(self) -> None:
        """`import github.pr` is caught by the `ast.Import` branch."""
        tree = ast.parse("import github.pr\n")

        assert vh.extract_internal_imports(tree) == [(1, "github")]

    def test_aliased_import_reports_the_real_name(self) -> None:
        """An `as` alias does not hide the imported package."""
        tree = ast.parse("import reviewers.dispatch as d\n")

        assert vh.extract_internal_imports(tree) == [(1, "reviewers")]

    def test_external_imports_are_ignored(self) -> None:
        """Third-party and stdlib imports are not boundary-relevant."""
        tree = ast.parse("import os\nimport httpx\nfrom pathlib import Path\n")

        assert vh.extract_internal_imports(tree) == []

    def test_relative_import_is_ignored(self) -> None:
        """`from . import x` has `node.module is None` and must not crash."""
        tree = ast.parse("from . import sibling\n")

        assert vh.extract_internal_imports(tree) == []

    def test_line_numbers_are_preserved(self) -> None:
        """The reported line is where a human will find the import."""
        tree = ast.parse("import os\n\n\nfrom cli.render import render_agents\n")

        assert vh.extract_internal_imports(tree) == [(4, "cli")]

    def test_imports_nested_inside_a_function_are_found(self) -> None:
        """`ast.walk` means a deferred import is not an escape hatch."""
        tree = ast.parse("def f():\n    from github.pr import PRDiff\n    return PRDiff\n")

        assert vh.extract_internal_imports(tree) == [(2, "github")]


class TestLintFile:
    """Pass 1 on a single file."""

    def test_untracked_file_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A file outside every tracked module yields no violations."""
        _write(tmp_path / "scripts" / "thing.py", "from github.pr import PRDiff\n")
        monkeypatch.chdir(tmp_path)

        assert vh.lint_file(Path("scripts/thing.py")) == []

    def test_cross_boundary_import_is_a_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`renderer` may import nothing internal, so `github` is forbidden."""
        _write(tmp_path / "renderer" / "compose.py", "import os\nfrom github.pr import PRDiff\n")
        monkeypatch.chdir(tmp_path)

        violations = vh.lint_file(Path("renderer/compose.py"))

        assert len(violations) == 1
        assert violations[0].importer == "renderer"
        assert violations[0].imported == "github"
        assert violations[0].line == 2
        assert "may only import from: (nothing)" in violations[0].message
        assert "AGENTS.md > Module Boundaries" in violations[0].message

    def test_violation_message_names_the_allowed_modules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A layer with allowances lists them, sorted, instead of "(nothing)"."""
        _write(tmp_path / "github" / "pr.py", "from cli.render import render_agents\n")
        monkeypatch.chdir(tmp_path)

        violations = vh.lint_file(Path("github/pr.py"))

        assert len(violations) == 1
        assert "may only import from: 'reviewers'" in violations[0].message

    def test_allowed_import_is_not_a_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`github` -> `reviewers` is in ALLOWED_IMPORTS."""
        _write(tmp_path / "github" / "issues.py", "from reviewers.verdicts import Finding\n")
        monkeypatch.chdir(tmp_path)

        assert vh.lint_file(Path("github/issues.py")) == []

    def test_intra_module_import_is_not_a_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A module importing itself is not crossing anything."""
        _write(tmp_path / "renderer" / "compose.py", "from renderer.lockfile import read_lock\n")
        monkeypatch.chdir(tmp_path)

        assert vh.lint_file(Path("renderer/compose.py")) == []

    def test_syntax_error_is_reported_not_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An unparseable tracked file logs to stderr and yields no violations."""
        _write(tmp_path / "renderer" / "broken.py", "def f(:\n")
        monkeypatch.chdir(tmp_path)

        assert vh.lint_file(Path("renderer/broken.py")) == []
        assert "SYNTAX ERROR" in capsys.readouterr().err

    def test_every_forbidden_import_in_a_file_is_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The linter does not stop at the first violation in a file."""
        _write(
            tmp_path / "interview" / "analyzer.py",
            "from github.pr import PRDiff\nfrom cli.render import render_agents\n",
        )
        monkeypatch.chdir(tmp_path)

        violations = vh.lint_file(Path("interview/analyzer.py"))

        assert {v.imported for v in violations} == {"github", "cli"}


# ─────────────────────────────────────────────────────────────────
# collect_python_files / run_lint
# ─────────────────────────────────────────────────────────────────


class TestCollectPythonFiles:
    """What Pass 1 walks -- the input to the `files_checked == 0` guard."""

    def test_collects_recursively_from_tracked_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`rglob` reaches nested modules."""
        _write(tmp_path / "github" / "pr.py", "x = 1\n")
        _write(tmp_path / "github" / "nested" / "deep.py", "x = 1\n")
        monkeypatch.chdir(tmp_path)

        assert vh.collect_python_files() == [
            Path("github/nested/deep.py"),
            Path("github/pr.py"),
        ]

    def test_ignores_untracked_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`scripts/` and `tests/` are not boundary-tracked."""
        _write(tmp_path / "scripts" / "thing.py", "x = 1\n")
        _write(tmp_path / "tests" / "test_thing.py", "x = 1\n")
        monkeypatch.chdir(tmp_path)

        assert vh.collect_python_files() == []

    def test_collects_tracked_top_level_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`migrate.py` is tracked by name even though it is not a package."""
        _write(tmp_path / "migrate.py", "x = 1\n")
        _write(tmp_path / "setup.py", "x = 1\n")
        monkeypatch.chdir(tmp_path)

        assert vh.collect_python_files() == [Path("migrate.py")]

    def test_empty_tree_collects_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The precondition for the zero-files guard in `main`."""
        monkeypatch.chdir(tmp_path)

        assert vh.collect_python_files() == []


class TestRunLint:
    """Pass 1 over the whole tree."""

    def test_counts_files_and_aggregates_violations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Violations from several files land in one result."""
        _write(tmp_path / "renderer" / "a.py", "from github.pr import PRDiff\n")
        _write(tmp_path / "interview" / "b.py", "from cli.render import render_agents\n")
        _write(tmp_path / "github" / "c.py", "from reviewers.verdicts import Finding\n")
        monkeypatch.chdir(tmp_path)

        result = vh.run_lint()

        assert result.files_checked == 3
        assert result.clean is False
        assert {v.importer for v in result.violations} == {"renderer", "interview"}

    def test_zero_files_is_reported_as_clean_but_counted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`clean` alone cannot distinguish "no violations" from "no files".

        That ambiguity is precisely why `main` gates on `files_checked == 0`
        separately -- this asserts the shape `main` has to defend against.
        """
        monkeypatch.chdir(tmp_path)

        result = vh.run_lint()

        assert result.files_checked == 0
        assert result.clean is True

    def test_the_real_repository_is_clean_and_non_empty(self) -> None:
        """The linter, pointed at this repo, walks real files and passes."""
        result = vh.run_lint()

        assert result.files_checked > 0
        assert result.clean is True, [v.message for v in result.violations]


class TestBoundaryMapInvariants:
    """The declared graph must describe modules that exist."""

    def test_every_allowed_target_is_itself_a_known_module(self) -> None:
        """A typo'd target would silently permit nothing and forbid nothing."""
        for module, allowed in vh.ALLOWED_IMPORTS.items():
            unknown = allowed - set(vh.ALLOWED_IMPORTS)
            assert not unknown, f"{module} may import unknown module(s) {unknown}"

    def test_known_cycles_still_exist_in_the_declared_graph(self) -> None:
        """A stale baseline entry is an allowlist quietly growing."""
        cycles = {
            frozenset({a, b})
            for a, deps in vh.ALLOWED_IMPORTS.items()
            for b in deps
            if a in vh.ALLOWED_IMPORTS.get(b, set())
        }

        assert vh.KNOWN_CYCLES.issubset(cycles)

    def test_no_undeclared_cycle_exists(self) -> None:
        """The contract must carry no cycle that is not explicitly accepted."""
        cycles = {
            frozenset({a, b})
            for a, deps in vh.ALLOWED_IMPORTS.items()
            for b in deps
            if a in vh.ALLOWED_IMPORTS.get(b, set())
        }

        assert cycles - vh.KNOWN_CYCLES == set()


# ─────────────────────────────────────────────────────────────────
# check_rendered_agents
# ─────────────────────────────────────────────────────────────────


def _fake_render(names_to_content: dict[str, str]) -> Callable[..., None]:
    """Build a `render_agents` stand-in that writes *names_to_content* to the out dir."""

    def _render(
        context_path: Path, templates_dir: Path, output_dir: Path, update_lock: bool = True
    ) -> None:
        for name, content in names_to_content.items():
            (output_dir / name).write_text(content, encoding="utf-8")

    return _render


@pytest.fixture
def rendered_agents_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A cwd with both render inputs present, so Pass 3 gets past its guards."""
    _write(tmp_path / ".factory" / "project_context.md", "# context\n")
    (tmp_path / "templates").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.usefixtures("sys_path_guard")
class TestCheckRenderedAgents:
    """Pass 3: `.claude/agents/*.md` must equal a fresh render."""

    def test_missing_project_context_is_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing inputs are reported, not skipped -- the harness cannot self-check."""
        (tmp_path / "templates").mkdir()
        monkeypatch.chdir(tmp_path)

        problems = vh.check_rendered_agents()

        assert len(problems) == 1
        assert "project_context.md is missing" in problems[0]

    def test_missing_templates_dir_is_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Context present but no templates is also reported."""
        _write(tmp_path / ".factory" / "project_context.md", "# context\n")
        monkeypatch.chdir(tmp_path)

        problems = vh.check_rendered_agents()

        assert problems == ["templates/ is missing"]

    def test_render_failure_is_drift(
        self, rendered_agents_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `RenderError` surfaces here first -- the harness dogfoods its renderer."""
        from cli.render import RenderError

        def _boom(*args: object, **kwargs: object) -> None:
            raise RenderError("bad frontmatter")

        monkeypatch.setattr("cli.render.render_agents", _boom)

        problems = vh.check_rendered_agents()

        assert len(problems) == 1
        assert "rendering" in problems[0]
        assert "bad frontmatter" in problems[0]

    def test_rendered_file_absent_from_agents_dir_is_drift(
        self, rendered_agents_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A template with no output on disk means someone did not re-render."""
        monkeypatch.setattr("cli.render.render_agents", _fake_render({"engineer.md": "body\n"}))

        problems = vh.check_rendered_agents()

        assert len(problems) == 1
        assert "engineer.md is missing" in problems[0]
        assert "render_own_agents.py" in problems[0]

    def test_no_agents_directory_at_all_is_drift(
        self, rendered_agents_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An absent `.claude/agents/` reports every expected file as missing."""
        monkeypatch.setattr(
            "cli.render.render_agents", _fake_render({"a.md": "x\n", "b.md": "y\n"})
        )

        problems = vh.check_rendered_agents()

        assert len(problems) == 2

    def test_differing_file_is_drift(
        self, rendered_agents_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hand-edited agent definition is exactly what this pass catches."""
        _write(rendered_agents_tree / ".claude" / "agents" / "engineer.md", "hand-edited\n")
        monkeypatch.setattr("cli.render.render_agents", _fake_render({"engineer.md": "rendered\n"}))

        problems = vh.check_rendered_agents()

        assert len(problems) == 1
        assert "differs from a fresh render" in problems[0]

    def test_orphan_file_on_disk_is_drift(
        self, rendered_agents_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An agent with no template behind it is deleted or enabled, not kept."""
        _write(rendered_agents_tree / ".claude" / "agents" / "ghost.md", "x\n")
        monkeypatch.setattr("cli.render.render_agents", _fake_render({}))

        problems = vh.check_rendered_agents()

        assert len(problems) == 1
        assert "has no template behind it" in problems[0]

    def test_in_sync_tree_reports_nothing(
        self, rendered_agents_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Byte-identical output is the only clean result."""
        _write(rendered_agents_tree / ".claude" / "agents" / "engineer.md", "rendered\n")
        monkeypatch.setattr("cli.render.render_agents", _fake_render({"engineer.md": "rendered\n"}))

        assert vh.check_rendered_agents() == []

    def test_problems_are_reported_in_sorted_order(
        self, rendered_agents_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deterministic output -- CI logs diff cleanly between runs."""
        monkeypatch.setattr(
            "cli.render.render_agents", _fake_render({"z.md": "x\n", "a.md": "x\n"})
        )

        problems = vh.check_rendered_agents()

        assert len(problems) == 2
        assert "a.md" in problems[0]
        assert "z.md" in problems[1]


# ─────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────


def _stub_passes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    lint: vh.LintResult | None = None,
    omit: vh.CoverageOmitResult | None = None,
    agents: list[str] | None = None,
) -> None:
    """Replace the three passes so `main`'s own branching is what is under test."""
    monkeypatch.setattr(vh, "run_lint", lambda: lint or vh.LintResult(files_checked=7))
    monkeypatch.setattr(
        vh,
        "check_coverage_omit_drift",
        lambda: omit if omit is not None else vh.CoverageOmitResult(checked=True),
    )
    monkeypatch.setattr(vh, "check_rendered_agents", lambda: list(agents or []))


class TestMain:
    """Exit codes and reporting for the CI entrypoint."""

    def test_all_clean_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Every pass clean -> exit 0."""
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        _stub_passes(monkeypatch)

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "All checks passed" in out
        assert "No boundary violations found" in out

    def test_zero_files_checked_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The regression this linter was rewritten for: a linter pointed at nothing.

        `clean` is True here -- zero violations out of zero files -- and the
        old code printed "No boundary violations found" and exited 0 as a
        required status check.
        """
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        _stub_passes(monkeypatch, lint=vh.LintResult(files_checked=0))

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "Checked 0 files" in out
        assert "ALLOWED_IMPORTS names modules with no directory" in out
        assert "No boundary violations found" not in out

    def test_zero_files_checked_exits_one_even_with_every_directory_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Nothing walked is a failure regardless of why -- the guard is unconditional."""
        for module in vh.INTERNAL_MODULES:
            (tmp_path / module).mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        _stub_passes(monkeypatch, lint=vh.LintResult(files_checked=0))

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "Checked 0 files" in out
        assert "no directory" not in out

    def test_declared_but_absent_module_is_warned_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Files were walked, so a missing declared module is a warning only."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        _stub_passes(monkeypatch, lint=vh.LintResult(files_checked=4))

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 0
        assert "Declared but absent from disk" in capsys.readouterr().out

    def test_boundary_violations_are_printed_and_exit_one(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Pass 1 failures reach stdout with file, line and message."""
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        violation = vh.Violation(
            file=Path("renderer/compose.py"),
            line=3,
            importer="renderer",
            imported="github",
            message="Boundary violation: 'renderer' imports from 'github'",
        )
        _stub_passes(monkeypatch, lint=vh.LintResult(violations=[violation], files_checked=7))

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "renderer/compose.py:3" in out
        assert "1 boundary violation(s)" in out
        assert "CI FAILED" in out

    def test_known_cycle_is_reported_and_accepted(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The github <-> reviewers baseline prints on every run, and passes."""
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        _stub_passes(monkeypatch)

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 0
        assert "Known cycle, accepted: github ↔ reviewers" in capsys.readouterr().out

    def test_new_cycle_exits_one(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A cycle absent from KNOWN_CYCLES stops the build."""
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        monkeypatch.setattr(vh, "ALLOWED_IMPORTS", {"a": {"b"}, "b": {"a"}})
        monkeypatch.setattr(vh, "KNOWN_CYCLES", set())
        monkeypatch.setattr(vh, "INTERNAL_MODULES", {"a", "b"})
        _stub_passes(monkeypatch)

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "1 new import cycle(s)" in out
        assert "a ↔ b" in out
        assert "Add to KNOWN_CYCLES only with a written reason" in out

    def test_stale_known_cycle_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A baseline entry that outlived its cycle is named, not left to rot."""
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        monkeypatch.setattr(vh, "ALLOWED_IMPORTS", {"a": set(), "b": set()})
        monkeypatch.setattr(vh, "KNOWN_CYCLES", {frozenset({"a", "b"})})
        monkeypatch.setattr(vh, "INTERNAL_MODULES", {"a", "b"})
        _stub_passes(monkeypatch)

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "KNOWN_CYCLES lists a ↔ b, which no longer exists. Delete it." in out
        assert "No cycles." in out

    def test_coverage_pass_skipped_when_unchecked(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No pyproject -> "skipped", which must not read as "clean"."""
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        _stub_passes(monkeypatch, omit=vh.CoverageOmitResult(checked=False))

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Skipped (no pyproject.toml or tomllib unavailable)" in out
        assert "No coverage omit drift" not in out

    def test_omit_drift_exits_one(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Pass 2 failures print the multi-line drift message and fail the build."""
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        _stub_passes(
            monkeypatch,
            omit=vh.CoverageOmitResult(
                drift_violations=["Coverage omit drift: 'legacy.py'\n  second line"],
                omitted_modules=["legacy.py"],
                checked=True,
            ),
        )

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "1 omit drift violation(s)" in out
        assert "second line" in out

    def test_rendered_agent_drift_exits_one(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Pass 3 failures count toward the total and fail the build."""
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        _stub_passes(monkeypatch, agents=[".claude/agents/engineer.md differs"])

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "1 rendered-agent drift violation(s)" in out
        assert "1 total violation(s)" in out

    def test_violation_total_sums_all_three_passes(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The final tally is the sum, not the count of failing passes."""
        monkeypatch.setattr(sys, "argv", ["validate_harness.py"])
        violation = vh.Violation(Path("renderer/a.py"), 1, "renderer", "github", "nope")
        _stub_passes(
            monkeypatch,
            lint=vh.LintResult(violations=[violation], files_checked=7),
            omit=vh.CoverageOmitResult(drift_violations=["drift"], checked=True),
            agents=["agent drift a", "agent drift b"],
        )

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 1
        assert "4 total violation(s)" in capsys.readouterr().out

    def test_report_mode_does_not_exit_nonzero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--report` is the GC agent's read-only mode: it reports and returns."""
        monkeypatch.setattr(sys, "argv", ["validate_harness.py", "--report"])
        _stub_passes(monkeypatch, agents=["some drift"])

        vh.main()  # must return normally -- no SystemExit at all

        out = capsys.readouterr().out
        assert "1 total violation(s)" in out
        assert "CI FAILED" not in out

    def test_report_mode_still_exits_zero_when_clean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A clean `--report` run takes the same exit-0 path as strict mode."""
        monkeypatch.setattr(sys, "argv", ["validate_harness.py", "--report"])
        _stub_passes(monkeypatch)

        with pytest.raises(SystemExit) as exc:
            vh.main()

        assert exc.value.code == 0

#!/usr/bin/env python3
"""
Harness structural linter.

Enforces:
  1. Module boundary rules defined in AGENTS.md
  2. Coverage omit hygiene — implemented modules must not be omitted

Exits 0 if clean. Exits 1 with actionable output on violations.

Usage:
    python scripts/validate_harness.py           # Strict (CI)
    python scripts/validate_harness.py --report  # Report mode (GC agent)
"""

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

# ─────────────────────────────────────────────────────────────────
# Boundary rules — CUSTOMIZE THESE to match your AGENTS.md module boundary table.
# Keys are top-level module names (directories) or filenames without .py.
# Values are sets of module names that the key module is allowed to import from.
#
# This map held the template's EXAMPLE modules -- auth/clients/resolvers/
# pipeline/reporter/models -- until 2026-08-24. None of them exist in this repo,
# so INTERNAL_MODULES resolved to nothing on disk, Pass 1 walked zero files, and
# "Harness Structure" passed green as a required check while verifying nothing.
# AGENTS.md still carries the same unfilled placeholder; the templating step was
# never completed. Below is this repo's real graph, derived by AST-walking every
# package in pyproject's packages list.
# ─────────────────────────────────────────────────────────────────
ALLOWED_IMPORTS: dict[str, set[str]] = {
    # Leaves — import nothing internal.
    "interview": set(),
    "notifications": set(),
    "renderer": set(),
    "verdict_store": set(),
    # Mid layer.
    "github": {"reviewers"},
    "reviewers": {"github"},
    # Orchestrators.
    "stonehaven": {"github", "notifications", "reviewers", "verdict_store"},
    "cli": {"github", "interview", "renderer", "stonehaven"},
    # `templates` is in pyproject's packages list but holds 6 .md files and zero
    # .py, so nothing can import it and it is not an internal module here.
}

# Cycles present when this map was first written, accepted explicitly so that
# any NEW cycle fails. A baseline, not an amnesty -- one line to delete once the
# refactor lands.
#
#   github/issues.py:20      from reviewers.verdicts import Finding
#   reviewers/dispatch.py:11 from github.pr import PRDiff
#
# Both are type-only imports, the usual sign that two names belong in a shared
# module neither package owns. Breaking it is a code change across two packages
# covered by 471 tests, deliberately not bundled into a commit whose job is to
# make this linter read real files.
KNOWN_CYCLES: set[frozenset[str]] = {frozenset({"github", "reviewers"})}

INTERNAL_MODULES = set(ALLOWED_IMPORTS.keys())
REPO_ROOT = Path(".")


@dataclass
class Violation:
    file: Path
    line: int
    importer: str
    imported: str
    message: str


@dataclass
class LintResult:
    violations: list[Violation] = field(default_factory=list)
    files_checked: int = 0

    @property
    def clean(self) -> bool:
        return len(self.violations) == 0


def get_module_layer(path: Path) -> str | None:
    """Return the boundary layer name for a given path."""
    parts = path.parts

    # Handle top-level files: pipeline.py, reporter.py, models.py, migrate.py
    if len(parts) == 1 and path.suffix == ".py":
        stem = path.stem
        return stem if stem in INTERNAL_MODULES else None

    # Handle directory modules: auth/, clients/, resolvers/
    if len(parts) >= 2 and parts[0] in INTERNAL_MODULES:
        return parts[0]

    return None


def extract_internal_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Extract all internal module references from an AST."""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in INTERNAL_MODULES:
                    imports.append((node.lineno, root))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in INTERNAL_MODULES:
                    imports.append((node.lineno, root))
    return imports


def lint_file(path: Path) -> list[Violation]:
    """Check a single file for boundary violations."""
    layer = get_module_layer(path)
    if layer not in ALLOWED_IMPORTS:
        return []

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        print(f"  SYNTAX ERROR in {path}: {e}", file=sys.stderr)
        return []

    allowed = ALLOWED_IMPORTS[layer]
    violations = []

    for lineno, imported in extract_internal_imports(tree):
        if imported == layer:
            continue  # Intra-module imports are fine
        if imported not in allowed:
            allowed_str = ", ".join(f"'{m}'" for m in sorted(allowed)) or "(nothing)"
            violations.append(
                Violation(
                    file=path,
                    line=lineno,
                    importer=layer,
                    imported=imported,
                    message=(
                        f"Boundary violation: '{layer}' imports from '{imported}'\n"
                        f"  '{layer}' may only import from: {allowed_str}\n"
                        f"  See AGENTS.md > Module Boundaries"
                    ),
                )
            )

    return violations


def collect_python_files() -> list[Path]:
    """Collect all Python files in boundary-tracked modules."""
    files: list[Path] = []
    tracked = [*INTERNAL_MODULES, "migrate"]

    for entry in REPO_ROOT.iterdir():
        if entry.is_file() and entry.suffix == ".py" and entry.stem in tracked:
            files.append(entry)
        elif entry.is_dir() and entry.name in INTERNAL_MODULES:
            files.extend(entry.rglob("*.py"))

    return sorted(files)


def run_lint() -> LintResult:
    result = LintResult()
    files = collect_python_files()
    result.files_checked = len(files)

    for path in files:
        result.violations.extend(lint_file(path))

    return result


# ─────────────────────────────────────────────────────────────────
# Coverage omit drift detection
# ─────────────────────────────────────────────────────────────────

# Paths that are legitimately always omitted regardless of implementation state
PERMANENT_OMITS = {
    "tests/*",
    "scripts/*",
    "docs/*",
    ".venv/*",
    "venv/*",
    "__pycache__/*",
}

# File extensions and patterns that are never Python source modules
NON_SOURCE_PATTERNS = {".html", ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".cfg"}


def is_stub_only(path: Path) -> bool:
    """Check if a Python file contains only stubs (no real logic).

    A file is considered stub-only if every function/method body contains
    only: pass, ellipsis (...), raise NotImplementedError, or docstrings.
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, FileNotFoundError):
        return True  # Can't parse → treat as stub

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body

            # Filter out docstrings
            real_stmts = []
            for stmt in body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, (ast.Constant, ast.Str)):
                    continue  # docstring
                real_stmts.append(stmt)

            # Check if remaining statements are all stubs
            for stmt in real_stmts:
                if isinstance(stmt, ast.Pass):
                    continue
                if (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and stmt.value.value is ...
                ):
                    continue
                if isinstance(stmt, ast.Raise):
                    # Check if it's raising NotImplementedError
                    if isinstance(stmt.exc, ast.Call):
                        func = stmt.exc.func
                        if isinstance(func, ast.Name) and func.id == "NotImplementedError":
                            continue
                    elif isinstance(stmt.exc, ast.Name) and stmt.exc.id == "NotImplementedError":
                        continue
                # Found a real statement → not stub-only
                return False

    return True


def load_coverage_omit_list() -> list[str] | None:
    """Load the coverage omit list from pyproject.toml.

    Returns None if pyproject.toml doesn't exist or can't be parsed.
    """
    if tomllib is None:
        return None

    pyproject_path = REPO_ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    try:
        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)
    except Exception:
        return None

    omit: object = config.get("tool", {}).get("coverage", {}).get("run", {}).get("omit", [])
    if not isinstance(omit, list):
        return None
    return [str(entry) for entry in omit]


@dataclass
class CoverageOmitResult:
    """Result of coverage omit drift check."""

    drift_violations: list[str] = field(default_factory=list)
    omitted_modules: list[str] = field(default_factory=list)
    checked: bool = False

    @property
    def clean(self) -> bool:
        return len(self.drift_violations) == 0


def check_coverage_omit_drift() -> CoverageOmitResult:
    """Check for implemented modules that are still in the coverage omit list.

    An implemented module is one that:
    - Exists as a .py file
    - Contains real logic (not just stubs/NotImplementedError)
    - Is listed in the coverage omit section of pyproject.toml
    """
    result = CoverageOmitResult()
    omit_list = load_coverage_omit_list()

    if omit_list is None:
        return result  # No pyproject.toml or no omit list — nothing to check

    result.checked = True
    result.omitted_modules = list(omit_list)

    for omit_entry in omit_list:
        # Skip permanent infrastructure omits
        if omit_entry in PERMANENT_OMITS:
            continue

        # Skip non-Python files
        if any(omit_entry.endswith(ext) for ext in NON_SOURCE_PATTERNS):
            continue

        # Skip wildcard patterns that aren't specific files
        if omit_entry.endswith("/*") or omit_entry.endswith("/**"):
            continue

        # Resolve the path
        omit_path = REPO_ROOT / omit_entry

        # Handle glob-style entries (e.g., "auth/*.py")
        if "*" in omit_entry:
            # For now, skip complex globs — focus on exact file matches
            continue

        # Check if this is a specific Python file that exists and is implemented
        if omit_path.exists() and omit_path.suffix == ".py" and not is_stub_only(omit_path):
            result.drift_violations.append(
                f"Coverage omit drift: '{omit_entry}' is implemented but still in omit list\n"
                f"  File contains real logic (not stubs). Remove from [tool.coverage.run] omit.\n"
                f"  This module's coverage is not being measured."
            )

    return result


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────


def main() -> None:
    report_mode = "--report" in sys.argv

    print("🔍 Harness structural linter")
    print()

    # ── Pass 1: Module boundary check ──
    print("── Pass 1: Module boundaries ──")
    boundary_result = run_lint()
    print(f"   Files checked: {boundary_result.files_checked}")

    # Zero files is not a clean repo, it is a linter pointed at nothing. This
    # exact state -- ALLOWED_IMPORTS naming modules that do not exist -- shipped
    # here for months and reported "✅ No boundary violations found" on every
    # run, as a required status check. A check that cannot fail is a decoration.
    missing = sorted(m for m in INTERNAL_MODULES if not (REPO_ROOT / m).is_dir())
    if boundary_result.files_checked == 0:
        print("   ❌ Checked 0 files — the linter is not pointed at this repo.")
        if missing:
            print(f"      ALLOWED_IMPORTS names modules with no directory: {', '.join(missing)}")
        print("      Fix ALLOWED_IMPORTS (and AGENTS.md's boundary table) to name real modules.")
        sys.exit(1)
    if missing:
        print(f"   ⚠️  Declared but absent from disk: {', '.join(missing)}")

    if boundary_result.clean:
        print("   ✅ No boundary violations found.")
    else:
        print(f"   ❌ {len(boundary_result.violations)} boundary violation(s):\n")
        for v in boundary_result.violations:
            print(f"  {v.file}:{v.line}")
            for line in v.message.splitlines():
                print(f"    {line}")
            print()

    # ── Pass 1b: Import cycles ──
    # Declared-graph cycles, not observed ones: ALLOWED_IMPORTS is the contract,
    # and a cycle written into the contract is one nobody has to notice again.
    print()
    print("── Pass 1b: Import cycles ──")
    cycles = {
        frozenset({a, b})
        for a, deps in ALLOWED_IMPORTS.items()
        for b in deps
        if a in ALLOWED_IMPORTS.get(b, set())
    }
    new_cycles = sorted(tuple(sorted(c)) for c in cycles - KNOWN_CYCLES)
    stale = sorted(tuple(sorted(c)) for c in KNOWN_CYCLES - cycles)
    for c in sorted(tuple(sorted(c)) for c in cycles & KNOWN_CYCLES):
        print(f"   ⚠️  Known cycle, accepted: {c[0]} ↔ {c[1]}")
    if stale:
        # The baseline outlived the cycle. Say so -- a stale exception is how an
        # allowlist quietly grows into a blanket.
        for c in stale:
            print(f"   ⚠️  KNOWN_CYCLES lists {c[0]} ↔ {c[1]}, which no longer exists. Delete it.")
    if new_cycles:
        print(f"   ❌ {len(new_cycles)} new import cycle(s):\n")
        for c in new_cycles:
            print(f"      {c[0]} ↔ {c[1]}")
        print("\n      Add to KNOWN_CYCLES only with a written reason. Prefer breaking it.")
        sys.exit(1)
    if not cycles:
        print("   ✅ No cycles.")

    # ── Pass 2: Coverage omit drift ──
    print()
    print("── Pass 2: Coverage omit hygiene ──")
    coverage_result = check_coverage_omit_drift()

    if not coverage_result.checked:
        print("   ⏭️  Skipped (no pyproject.toml or tomllib unavailable)")
    elif coverage_result.clean:
        print(
            f"   ✅ No coverage omit drift ({len(coverage_result.omitted_modules)} entries checked)"
        )
    else:
        print(f"   ❌ {len(coverage_result.drift_violations)} omit drift violation(s):\n")
        for drift_msg in coverage_result.drift_violations:
            for line in drift_msg.splitlines():
                print(f"    {line}")
            print()

    # ── Final verdict ──
    print()
    all_clean = boundary_result.clean and coverage_result.clean
    if all_clean:
        print("   ✅ All checks passed.")
        sys.exit(0)
    else:
        total = len(boundary_result.violations) + len(coverage_result.drift_violations)
        print(f"   ❌ {total} total violation(s)")
        if not report_mode:
            print()
            print("─" * 60)
            print("CI FAILED — fix all violations before opening a PR.")
            print("Reference: AGENTS.md > Module Boundaries")
            sys.exit(1)


if __name__ == "__main__":
    main()

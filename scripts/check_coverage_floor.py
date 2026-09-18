#!/usr/bin/env python3
"""
Per-file coverage floor gate.

AGENTS.md > Conventions declares an 85% coverage floor. `--cov-fail-under=85` in
`.github/workflows/ci.yml` gates the TOTAL only, and `coverage report` rounds any
real value in [84.5%, 85.5%) to "85%" at its default integer precision -- so a
sub-floor file passes CI *and* reads as compliant in every log it appears in. That
is how `conformance/monday_arc_test.py` sat at 84.69% from PR #35 through the whole
#48-#52 coverage chain without one report saying so (issue #73).

This script is the missing mechanism for that declared guarantee (AGENTS.md >
Governing Principles, 2). It compares the RAW FLOAT from `coverage.json` against
the floor and prints every figure to two decimal places -- it never rounds to an
integer anywhere, because, per docs/learnings/pr-76.md, "a threshold compared
against a rounded reading is not a threshold at the boundary, which is the only
place it matters."

Deliberately stdlib-only: `scripts/` is excluded from ruff and from coverage
(`pyproject.toml`), so this file is checked by nothing automatically and must stay
cheap to read. It is NOT excluded from mypy, so it is fully annotated.

Usage:
    pytest tests/ --cov=.                       # produce .coverage
    coverage json -o coverage.json              # produce the input
    python scripts/check_coverage_floor.py
    python scripts/check_coverage_floor.py --input build/coverage.json

Exit codes:
    0  every measured file is at or above its floor
    1  at least one file is below its floor, or an EXCEPTIONS entry is malformed
    2  the coverage.json input is missing
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

# The floor AGENTS.md declares. A float, compared as a float -- see the module
# docstring on why an integer reading cannot enforce this.
FLOOR: float = 85.0

# Per-file exemptions from FLOOR. path -> (allowed_minimum, reason).
#
# Every reason MUST name a tracking issue (`#N`) and say when the entry expires;
# an entry whose reason names no issue is REJECTED rather than silently honoured,
# because an undated exemption with no owner is how a floor stops being a floor.
# Active entries are printed on EVERY run, passing runs included, so the list
# cannot go quiet.
#
# Deliberately empty: at the time this gate was wired in, no measured file was
# below 85.00% when this gate was introduced. Do not add an entry
# where a test would do, and never resolve a shortfall by editing the
# `[tool.coverage.run]` omit list -- that is the drift
# `scripts/validate_harness.py` Pass 2 exists to catch.
EXCEPTIONS: dict[str, tuple[float, str]] = {}

# A reason string must contain an issue reference to be honoured.
_ISSUE_REF = re.compile(r"#\d+")


def load_coverage(path: Path) -> dict[str, Any]:
    """Load and return the parsed `coverage json` report at *path*."""
    with path.open(encoding="utf-8") as handle:
        return cast(dict[str, Any], json.load(handle))


def file_percentages(data: dict[str, Any]) -> dict[str, float]:
    """Map each measured file to its `summary.percent_covered` as a raw float.

    The sibling `percent_covered_display` field is a pre-rounded STRING -- it is
    what `coverage report` prints and what hid #73 for seventeen PRs. It is never
    read here.
    """
    files = cast(dict[str, Any], data.get("files", {}))
    return {
        path: float(cast(dict[str, Any], entry["summary"])["percent_covered"])
        for path, entry in files.items()
    }


def _missing_statements(data: dict[str, Any]) -> dict[str, int]:
    """Map each measured file to its count of uncovered statements."""
    files = cast(dict[str, Any], data.get("files", {}))
    return {
        path: int(cast(dict[str, Any], entry["summary"]).get("missing_lines", 0))
        for path, entry in files.items()
    }


def _floor_for(path: str) -> float:
    """The floor that applies to *path* -- FLOOR, or its EXCEPTIONS minimum."""
    exception = EXCEPTIONS.get(path)
    return FLOOR if exception is None else exception[0]


def _print_exceptions() -> None:
    print("── Active exceptions ──")
    if not EXCEPTIONS:
        print(f"   (none — every file is held to {FLOOR:.2f}%)")
        return
    for path, (minimum, reason) in sorted(EXCEPTIONS.items()):
        print(f"   {path}: allowed minimum {minimum:.2f}% — {reason}")


def _print_table(rows: list[tuple[str, float, int]]) -> None:
    """Print path / percent (2dp) / missing statements, worst first."""
    width = max([len(path) for path, _, _ in rows] + [len("Path")])
    print(f"   {'Path':<{width}}  {'Percent':>9}  {'Missing':>7}")
    print(f"   {'─' * width}  {'─' * 9}  {'─' * 7}")
    for path, percent, missing in rows:
        print(f"   {path:<{width}}  {percent:>8.2f}%  {missing:>7}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when any single measured file is below the per-file coverage floor.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("coverage.json"),
        help="path to the `coverage json` report (default: coverage.json)",
    )
    args = parser.parse_args(argv)
    input_path: Path = args.input

    print(f"🔍 Per-file coverage floor — {FLOOR:.2f}%")
    print()

    # Static self-check before any I/O: an exemption with no tracking issue is a
    # configuration defect in this file, not a coverage result.
    unowned = sorted(
        path for path, (_, reason) in EXCEPTIONS.items() if not _ISSUE_REF.search(reason)
    )
    if unowned:
        print("   ❌ EXCEPTIONS entries with no tracking issue in their reason:")
        for path in unowned:
            print(f"      {path}")
        print()
        print("   Every exception must name an issue (`#N`) and say when it expires.")
        return 1

    if not input_path.exists():
        print(f"   ❌ {input_path} not found.")
        print("   Produce it with `coverage json -o coverage.json` after the test run.")
        return 2

    data = load_coverage(input_path)
    percentages = file_percentages(data)
    missing = _missing_statements(data)

    _print_exceptions()
    print()

    if not percentages:
        print("   ❌ No files in the coverage report — nothing was measured.")
        return 1

    rows = sorted(
        ((path, percent, missing.get(path, 0)) for path, percent in percentages.items()),
        key=lambda row: (row[1], row[0]),
    )

    print(f"── Per-file coverage ({len(rows)} files) ──")
    _print_table(rows)
    print()

    shortfalls = [row for row in rows if row[1] < _floor_for(row[0])]
    if not shortfalls:
        print(f"   ✅ All {len(rows)} files at or above their floor.")
        return 0

    print(f"   ❌ {len(shortfalls)} file(s) below the floor:")
    print()
    _print_table(shortfalls)
    print()
    for path, percent, _ in shortfalls:
        exception = EXCEPTIONS.get(path)
        if exception is None:
            print(f"   {path}: {percent:.2f}% < {FLOOR:.2f}% (FLOOR)")
        else:
            print(
                f"   {path}: {percent:.2f}% < {exception[0]:.2f}% "
                f"(EXCEPTIONS minimum) — {exception[1]}"
            )
    print()
    print("─" * 60)
    print("CI FAILED — raise the file's coverage with tests, or add a dated")
    print("EXCEPTIONS entry naming a tracking issue. Do not add it to the")
    print("[tool.coverage.run] omit list.")
    print("Reference: AGENTS.md > Conventions, issue #73")
    return 1


if __name__ == "__main__":
    sys.exit(main())

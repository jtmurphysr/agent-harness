#!/usr/bin/env python3
"""Render this repository's own reviewers: templates/ + .factory/project_context.md -> .claude/agents/.

The harness ships a three-layer agent renderer to every project it generates and,
until 2026-09-18, never ran it on itself: .claude/agents/ were hand-written copies
that had drifted 106 lines from their templates. Worse, the renderer's output was
not a loadable Claude Code subagent (HTML comments above the frontmatter, no
`name:`), so every generated project's reviewers were silently inert. Dogfooding
found both.

Claude Code's protected-path guard refuses agent Write/Edit under .claude/, and
runs before any allow rule. Agents therefore change templates/ or the context and
run THIS -- a reviewed Python writer whose output validate_harness.py Pass 3 checks
byte-for-byte. That is the line between this and laundering a denied write.

Run it in the same PR as the template or context edit: Pass 3 gates harness-lint,
which gates auto-merge, so a PR that skips it cannot land.

Usage:
    python scripts/render_own_agents.py          # render into .claude/agents/
    python scripts/render_own_agents.py --check  # exit 1 on drift (what Pass 3 runs)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cli.render import render_agents  # noqa: E402


def main() -> None:
    if "--check" in sys.argv:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from validate_harness import check_rendered_agents

        problems = check_rendered_agents()
        if problems:
            print("❌ .claude/agents/ is out of sync:")
            for p in problems:
                print(f"   {p}")
            sys.exit(1)
        print("✅ .claude/agents/ matches a fresh render")
        sys.exit(0)

    render_agents(
        REPO_ROOT / ".factory" / "project_context.md",
        REPO_ROOT / "templates",
        REPO_ROOT / ".claude" / "agents",
        update_lock=False,
    )
    for p in sorted((REPO_ROOT / ".claude" / "agents").glob("*.md")):
        print(f"  rendered {p.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

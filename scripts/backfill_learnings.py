#!/usr/bin/env python3
"""
Retroactive compound learning backfill — agent-harness.

Analyzes git history from a completed agent-built project and generates
structured learning documents compatible with the compound-learning workflow.

This script does NOT call the GitHub API. It works entirely from local git
history, issue specs, and source files. The output is a set of learning
documents in the compound-learning format, ready to be committed to
docs/learnings/ in the harness repo.

Usage:
    python scripts/backfill_learnings.py /path/to/project [--output docs/learnings]
    python scripts/backfill_learnings.py /path/to/project --dry-run
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ─────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────


@dataclass
class PRRecord:
    """Represents a merged pull request from git history."""

    pr_number: int
    merge_commit: str
    title: str
    branch: str
    issue_number: int | None = None
    feature_commits: list[str] = field(default_factory=list)
    fix_commits: list[str] = field(default_factory=list)
    harness_commits: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    required_iteration: bool = False


@dataclass
class LearningDocument:
    """Structured learning output."""

    pr_number: int
    issue_number: int | None
    module: str
    date: str
    tags: list[str]
    outcome: str  # clean | required-iteration | scope-deviation
    title: str
    what_was_specified: str
    what_was_delivered: str
    delta_analysis: str
    for_future_specs: str
    for_future_warnings: str
    for_agents_md: str
    reusable_patterns: str
    suggested_actions: list[str]


# ─────────────────────────────────────────────────────────────────
# Git operations
# ─────────────────────────────────────────────────────────────────


def git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def extract_merge_prs(cwd: Path) -> list[PRRecord]:
    """Extract all merge PRs from git log."""
    log = git(["log", "--oneline", "--all"], cwd)
    records: list[PRRecord] = []

    for line in log.splitlines():
        match = re.match(r"^([a-f0-9]+)\s+Merge pull request #(\d+)\s+from\s+\S+/(.+)$", line)
        if match:
            commit_hash, pr_num, branch = match.groups()
            records.append(PRRecord(
                pr_number=int(pr_num),
                merge_commit=commit_hash,
                title="",
                branch=branch,
            ))

    return records


def enrich_pr_record(record: PRRecord, cwd: Path) -> None:
    """Enrich a PR record with commit details and file changes."""
    # Extract issue number from branch name
    # Pattern: claude/issue-N-YYYYMMDD-HHMM
    issue_match = re.search(r"issue-(\d+)", record.branch)
    if issue_match:
        record.issue_number = int(issue_match.group(1))

    # Get commits between merge and its first parent
    try:
        # Get the commits that were part of this PR
        commits_raw = git(
            ["log", "--oneline", f"{record.merge_commit}^..{record.merge_commit}^2"],
            cwd,
        )
    except RuntimeError:
        # If we can't get the range, try getting the commit message
        commits_raw = ""

    for commit_line in commits_raw.splitlines():
        if not commit_line.strip():
            continue
        commit_hash, *msg_parts = commit_line.split(maxsplit=1)
        msg = msg_parts[0] if msg_parts else ""

        if msg.startswith("feat:"):
            record.feature_commits.append(msg)
            if not record.title:
                record.title = msg
        elif msg.startswith("fix:"):
            record.fix_commits.append(msg)
            record.required_iteration = True
        elif msg.startswith("harness:"):
            record.harness_commits.append(msg)

    # If no title extracted from commits, use the branch name
    if not record.title:
        record.title = record.branch.replace("-", " ").replace("/", " — ")

    # Get files changed in this merge
    try:
        diff_stat = git(
            ["diff", "--name-only", f"{record.merge_commit}^..{record.merge_commit}"],
            cwd,
        )
        record.files_changed = [f for f in diff_stat.splitlines() if f.strip()]
    except RuntimeError:
        record.files_changed = []


def get_all_commits(cwd: Path) -> list[tuple[str, str]]:
    """Get all commits as (hash, message) tuples."""
    log = git(["log", "--oneline", "--all"], cwd)
    commits = []
    for line in log.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            commits.append((parts[0], parts[1]))
    return commits


# ─────────────────────────────────────────────────────────────────
# Analysis
# ─────────────────────────────────────────────────────────────────

# Issue spec patterns — maps issue numbers to modules
ISSUE_MODULE_MAP: dict[int, str] = {}


def _infer_module_from_title(title: str) -> str:
    """Infer the primary module from an issue title.

    Uses generic heuristics — looks for file paths, directory names, and
    common issue types rather than hardcoded project-specific module names.
    """
    lower = title.lower()

    # Match common structural issue types first
    if "scaffold" in lower:
        return "scaffold"
    if "integration" in lower:
        return "integration"
    if "gc" in lower or "entropy" in lower:
        return "gc"
    if "convention" in lower or "docs" in lower:
        return "docs"

    # Try to extract a module name from file-like references in the title
    # e.g., "pipeline.py", "auth/apple_auth.py", "models"
    import re as _re

    # Match "directory/file.py" pattern
    file_match = _re.search(r"(\w+)/(\w+)\.py", title)
    if file_match:
        return file_match.group(1)  # Return the directory name

    # Match "file.py" pattern (top-level module)
    file_match = _re.search(r"(\w+)\.py", title)
    if file_match:
        return file_match.group(1)

    # Match module-like words that appear before common suffixes
    for suffix in ("_auth", "_client", "_resolver"):
        if suffix in lower:
            match = _re.search(rf"(\w+{suffix})", lower)
            if match:
                return match.group(1)

    # Fall back to common standalone module names
    for name in ("models", "pipeline", "reporter", "migrate"):
        if name in lower:
            return name

    return "unknown"


def load_issue_specs(project_dir: Path) -> dict[int, dict[str, str]]:
    """Load issue specs from docs/issues/ or root-level spec files."""
    specs: dict[int, dict[str, str]] = {}

    # Check common locations for issue specs
    spec_paths = [
        project_dir / "docs" / "issues",
        project_dir,
    ]

    for spec_dir in spec_paths:
        if not spec_dir.exists():
            continue
        for f in spec_dir.iterdir():
            if not f.suffix == ".md":
                continue
            content = f.read_text(encoding="utf-8")

            # Extract individual issue specs from combined files
            issue_blocks = re.split(r"^# Issue #(\d+):", content, flags=re.MULTILINE)

            # Process pairs: (issue_number, content)
            for i in range(1, len(issue_blocks), 2):
                issue_num = int(issue_blocks[i])
                block_content = issue_blocks[i + 1] if i + 1 < len(issue_blocks) else ""

                # Extract module name from title
                title_match = re.match(r"\s*(.+?)(?:\n|$)", block_content)
                title = title_match.group(1).strip() if title_match else "unknown"

                specs[issue_num] = {
                    "title": title,
                    "content": block_content[:2000],  # Truncate for analysis
                }

                # Determine primary module from title
                # Extracts module name by matching against common patterns:
                #   - File/directory names (e.g., "auth/foo.py", "pipeline.py")
                #   - Common issue types (scaffold, integration, gc/entropy, docs)
                module = _infer_module_from_title(title)

                ISSUE_MODULE_MAP[issue_num] = module

    return specs


def infer_module_from_files(files: list[str]) -> str:
    """Infer primary module from changed files."""
    module_scores: dict[str, int] = {}
    for f in files:
        if f.startswith("auth/"):
            module_scores["auth"] = module_scores.get("auth", 0) + 1
        elif f.startswith("clients/"):
            module_scores["clients"] = module_scores.get("clients", 0) + 1
        elif f.startswith("resolvers/"):
            module_scores["resolvers"] = module_scores.get("resolvers", 0) + 1
        elif f == "pipeline.py":
            module_scores["pipeline"] = module_scores.get("pipeline", 0) + 1
        elif f == "reporter.py":
            module_scores["reporter"] = module_scores.get("reporter", 0) + 1
        elif f == "models.py":
            module_scores["models"] = module_scores.get("models", 0) + 1
        elif f == "migrate.py":
            module_scores["migrate"] = module_scores.get("migrate", 0) + 1
        elif f.startswith("tests/"):
            module_scores["tests"] = module_scores.get("tests", 0) + 1
        elif f.startswith(".github/"):
            module_scores["harness"] = module_scores.get("harness", 0) + 1
        elif f.startswith("docs/"):
            module_scores["docs"] = module_scores.get("docs", 0) + 1

    if not module_scores:
        return "unknown"
    return max(module_scores, key=lambda k: module_scores[k])


def analyze_iteration_pattern(all_commits: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Identify fix commits that followed feat commits — iteration signal."""
    patterns: dict[str, list[str]] = {}
    prev_feat = None

    for _hash, msg in reversed(all_commits):
        if msg.startswith("feat:"):
            prev_feat = msg
        elif msg.startswith("fix:") and prev_feat:
            key = prev_feat
            if key not in patterns:
                patterns[key] = []
            patterns[key].append(msg)

    return patterns


def detect_harness_evolution(all_commits: list[tuple[str, str]]) -> list[str]:
    """Extract harness-prefixed commits — meta-learning signal."""
    return [msg for _, msg in all_commits if msg.startswith("harness:")]


# ─────────────────────────────────────────────────────────────────
# Learning generation
# ─────────────────────────────────────────────────────────────────


def generate_learning(
    record: PRRecord,
    specs: dict[int, dict[str, str]],
    iteration_patterns: dict[str, list[str]],
    harness_evolution: list[str],
) -> LearningDocument | None:
    """Generate a structured learning document from a PR record."""

    # Skip merge-only PRs with no meaningful content
    if not record.feature_commits and not record.fix_commits and not record.harness_commits:
        return None

    # Determine module
    module = "unknown"
    if record.issue_number and record.issue_number in ISSUE_MODULE_MAP:
        module = ISSUE_MODULE_MAP[record.issue_number]
    elif record.files_changed:
        module = infer_module_from_files(record.files_changed)

    # Determine outcome
    if record.required_iteration:
        outcome = "required-iteration"
    else:
        outcome = "clean"

    # Build tags
    tags = []
    if record.required_iteration:
        tags.append("required-iteration")
    if any("ruff" in c.lower() for c in record.fix_commits):
        tags.append("lint-fix")
    if any("coverage" in c.lower() or "omit" in c.lower() for c in record.fix_commits + record.harness_commits):
        tags.append("coverage-drift")
    if any("format" in c.lower() for c in record.fix_commits):
        tags.append("format-fix")
    if not record.fix_commits:
        tags.append("clean-pass")
    if record.harness_commits:
        tags.append("harness-evolution")

    # Get spec if available
    spec = specs.get(record.issue_number, {}) if record.issue_number else {}
    spec_title = spec.get("title", "No issue spec found")
    spec_content = spec.get("content", "")

    # Build what was specified
    what_specified = f"Issue #{record.issue_number}: {spec_title}" if record.issue_number else "No linked issue"
    if spec_content:
        # Extract acceptance criteria summary
        ac_match = re.search(r"## Acceptance Criteria\n(.*?)(?=\n##|\Z)", spec_content, re.DOTALL)
        if ac_match:
            what_specified += f"\n\nKey acceptance criteria from spec:\n{ac_match.group(1)[:500]}"

    # Build what was delivered
    delivered_parts = []
    if record.feature_commits:
        delivered_parts.append("Feature commits:\n" + "\n".join(f"  - {c}" for c in record.feature_commits))
    if record.fix_commits:
        delivered_parts.append("Fix commits (iterations):\n" + "\n".join(f"  - {c}" for c in record.fix_commits))
    if record.harness_commits:
        delivered_parts.append("Harness changes:\n" + "\n".join(f"  - {c}" for c in record.harness_commits))
    if record.files_changed:
        delivered_parts.append("Files changed:\n" + "\n".join(f"  - {f}" for f in record.files_changed[:20]))
    what_delivered = "\n\n".join(delivered_parts) if delivered_parts else "No details available"

    # Delta analysis
    delta_parts = []
    if record.fix_commits:
        delta_parts.append(
            f"Required {len(record.fix_commits)} fix commit(s) after initial implementation:\n"
            + "\n".join(f"  - {c}" for c in record.fix_commits)
        )
    if record.harness_commits:
        delta_parts.append(
            "Harness infrastructure changes were needed alongside the feature:\n"
            + "\n".join(f"  - {c}" for c in record.harness_commits)
        )
    if not delta_parts:
        delta_parts.append("Clean delivery — no iterations required.")
    delta = "\n\n".join(delta_parts)

    # For future specs
    future_specs_parts = []
    if any("ruff" in c.lower() for c in record.fix_commits):
        future_specs_parts.append(
            "- Add explicit pre-PR checklist: `ruff check --fix . && ruff format . && ruff check .` "
            "as a named step in the issue spec, not just in AGENTS.md"
        )
    if any("import" in c.lower() for c in record.fix_commits):
        future_specs_parts.append(
            "- Import ordering issues: specify `ruff check --fix .` before format to auto-fix import order"
        )
    if any("coverage" in c.lower() or "omit" in c.lower() for c in record.fix_commits + record.harness_commits):
        future_specs_parts.append(
            "- Coverage omit drift: each issue spec should include explicit coverage omit delta section"
        )
    if not future_specs_parts:
        future_specs_parts.append("- Spec was sufficient for clean delivery. No changes needed.")
    future_specs = "\n".join(future_specs_parts)

    # For future warnings
    future_warnings = "- No new domain warnings discovered." if not record.fix_commits else (
        "- Agent required iteration on this module. Review fix commits for patterns that should become warnings."
    )

    # For AGENTS.md
    agents_md = "- No AGENTS.md updates suggested." if not record.harness_commits else (
        "- Harness infrastructure was modified during this PR. Review changes for constitutional updates:\n"
        + "\n".join(f"  - {c}" for c in record.harness_commits)
    )

    # Reusable patterns — infer from module type
    patterns_parts = []
    if "resolver" in module:
        patterns_parts.append("- Protocol-based dependency injection for testability (no concrete client imports in resolvers)")
    if "client" in module:
        patterns_parts.append("- Centralized retry with exponential backoff — single ownership of retry logic")
    if module == "pipeline":
        patterns_parts.append("- Multi-strategy resolution chain with explicit unresolved tracking")
    if not patterns_parts:
        patterns_parts.append("- No new reusable patterns identified.")
    reusable_patterns = "\n".join(patterns_parts)

    # Suggested actions
    actions = []
    if record.fix_commits:
        actions.append(f"Review fix patterns from PR #{record.pr_number} for preventable failures")
    if record.harness_commits:
        actions.append(f"Evaluate harness changes from PR #{record.pr_number} for template inclusion")
    if "coverage-drift" in tags:
        actions.append("Add coverage omit validation to structural linter")
    if not actions:
        actions.append(f"PR #{record.pr_number} was clean — confirms current spec quality for {module}")

    return LearningDocument(
        pr_number=record.pr_number,
        issue_number=record.issue_number,
        module=module,
        date=datetime.now().strftime("%Y-%m-%d"),
        tags=tags,
        outcome=outcome,
        title=record.title,
        what_was_specified=what_specified,
        what_was_delivered=what_delivered,
        delta_analysis=delta,
        for_future_specs=future_specs,
        for_future_warnings=future_warnings,
        for_agents_md=agents_md,
        reusable_patterns=reusable_patterns,
        suggested_actions=actions,
    )


def render_learning(doc: LearningDocument) -> str:
    """Render a learning document to markdown."""
    tags_str = ", ".join(doc.tags)
    actions_str = "\n".join(f"- [ ] {a}" for a in doc.suggested_actions)

    return f"""---
pr: {doc.pr_number}
issue: {doc.issue_number or "none"}
module: {doc.module}
date: {doc.date}
tags: [{tags_str}]
outcome: {doc.outcome}
---

# Learning: PR #{doc.pr_number} — {doc.title}

## What Was Specified
{doc.what_was_specified}

## What Was Delivered
{doc.what_was_delivered}

## Delta Analysis
{doc.delta_analysis}

## Learnings

### For Future Issue Specs
{doc.for_future_specs}

### For Future Domain Warnings
{doc.for_future_warnings}

### For AGENTS.md
{doc.for_agents_md}

### Reusable Patterns
{doc.reusable_patterns}

## Suggested Actions
{actions_str}
"""


# ─────────────────────────────────────────────────────────────────
# Harness evolution summary
# ─────────────────────────────────────────────────────────────────


def render_harness_evolution(harness_commits: list[str], iteration_patterns: dict[str, list[str]]) -> str:
    """Render a summary document of harness evolution across the project."""
    commits_str = "\n".join(f"- {c}" for c in harness_commits)
    patterns_str = ""
    if iteration_patterns:
        for feat, fixes in iteration_patterns.items():
            patterns_str += f"\n### {feat}\n"
            patterns_str += "\n".join(f"- {f}" for f in fixes) + "\n"
    else:
        patterns_str = "No iteration patterns detected — all features landed cleanly."

    return f"""---
type: harness-evolution-summary
date: {datetime.now().strftime("%Y-%m-%d")}
tags: [meta, harness, infrastructure]
---

# Harness Evolution Summary

## Infrastructure Commits (chronological)
{commits_str}

## Iteration Patterns
Features that required fix commits after initial implementation:
{patterns_str}

## Key Takeaways
These harness changes represent the delta between "what we thought the agent needed"
and "what the agent actually needed." Each commit is a learning about agent behavior
that should inform the harness template for future projects.
"""


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill compound learnings from completed agent-built project"
    )
    parser.add_argument("project_dir", type=Path, help="Path to the project repo")
    parser.add_argument(
        "--output", type=Path, default=Path("docs/learnings"),
        help="Output directory for learning documents (default: docs/learnings)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print learnings to stdout without writing files"
    )
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    if not (project_dir / ".git").exists():
        print(f"Error: {project_dir} is not a git repository", file=sys.stderr)
        sys.exit(1)

    print(f"📚 Backfill learnings from: {project_dir}")
    print()

    # Step 1: Load issue specs
    specs = load_issue_specs(project_dir)
    print(f"   Issue specs loaded: {len(specs)}")

    # Step 2: Extract merge PRs
    pr_records = extract_merge_prs(project_dir)
    print(f"   Merge PRs found: {len(pr_records)}")

    # Step 3: Enrich records
    for record in pr_records:
        enrich_pr_record(record, project_dir)

    # Step 4: Get all commits for pattern analysis
    all_commits = get_all_commits(project_dir)
    iteration_patterns = analyze_iteration_pattern(all_commits)
    harness_evolution = detect_harness_evolution(all_commits)
    print(f"   Iteration patterns: {len(iteration_patterns)}")
    print(f"   Harness evolution commits: {len(harness_evolution)}")
    print()

    # Step 5: Generate learnings
    learnings: list[LearningDocument] = []
    for record in sorted(pr_records, key=lambda r: r.pr_number):
        doc = generate_learning(record, specs, iteration_patterns, harness_evolution)
        if doc:
            learnings.append(doc)

    print(f"   Learnings generated: {len(learnings)}")

    # Summary stats
    clean = sum(1 for l in learnings if l.outcome == "clean")
    iterated = sum(1 for l in learnings if l.outcome == "required-iteration")
    print(f"   Clean passes: {clean}")
    print(f"   Required iteration: {iterated}")
    print()

    if args.dry_run:
        print("─" * 60)
        print("DRY RUN — would write the following files:")
        print("─" * 60)
        for doc in learnings:
            filename = f"pr-{doc.pr_number}.md"
            print(f"\n{'═' * 60}")
            print(f"  {filename}")
            print(f"{'═' * 60}")
            print(render_learning(doc))

        # Harness evolution summary
        print(f"\n{'═' * 60}")
        print("  harness-evolution.md")
        print(f"{'═' * 60}")
        print(render_harness_evolution(harness_evolution, iteration_patterns))

        print(f"\nDRY RUN COMPLETE — {len(learnings)} learnings + 1 summary would be created")
    else:
        output_dir = args.output.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        written = 0
        for doc in learnings:
            filename = f"pr-{doc.pr_number}.md"
            filepath = output_dir / filename
            filepath.write_text(render_learning(doc), encoding="utf-8")
            print(f"   ✅ {filepath}")
            written += 1

        # Write harness evolution summary
        summary_path = output_dir / "harness-evolution.md"
        summary_path.write_text(
            render_harness_evolution(harness_evolution, iteration_patterns),
            encoding="utf-8",
        )
        print(f"   ✅ {summary_path}")

        print()
        print(f"   📚 {written} learnings + 1 summary written to {output_dir}")

    # Final report
    print()
    print("─" * 60)
    print("BACKFILL SUMMARY")
    print(f"   Project: {project_dir.name}")
    print(f"   PRs analyzed: {len(pr_records)}")
    print(f"   Learnings: {len(learnings)} ({clean} clean, {iterated} iterated)")
    print(f"   Harness commits: {len(harness_evolution)}")
    print(f"   Modules covered: {', '.join(sorted(set(l.module for l in learnings)))}")


if __name__ == "__main__":
    main()

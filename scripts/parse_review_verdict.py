#!/usr/bin/env python3
"""Turn one reviewer's final output into a CI exit code and a PR comment.

This is the whole verify step of the `review-engineer` / `review-architect` /
`review-sre` jobs in `.github/workflows/ci.yml`. The job pipes the reviewer's
final message in on stdin; this script decides whether the job passes, and
writes the comment the job posts. Nothing else parses a verdict in CI, and
nothing else should -- `reviewers.verdicts.VerdictParser` is the single
implementation and this is a thin shell around it (AGENTS.md LESSON 11).

WHY A SCRIPT AND NOT AN `if:` EXPRESSION: the verdict contract (#28) has three
failure modes that all have to mean "did not review" -- no verdict block, a
BLOCK with no citation, and a citation naming an invariant the project never
declared. A grep for the word BLOCK gets all three wrong, and gets them wrong
in the direction that merges.

Exit codes -- the contract the CI job is written against:

    0   PASS or WARN. The job succeeds. WARN still prints a comment body.
    1   BLOCK. The job fails. BLOCK is a HARD MERGE-FAIL, not a label: a
        BLOCKed PR does not auto-merge, and the only ways past are a push that
        re-reviews clean or a human merging by hand.
    2   Parse error, or the project's invariant ids could not be read. The job
        fails. FAIL CLOSED: a reviewer that did not produce a verdict did not
        review, and a reviewer whose declared-invariant list could not be
        loaded cannot have its citations checked
        (invariant: gate_fails_closed).

Stdout is two parts, so one invocation serves both jobs the step has:

    line 1   PASS | WARN | BLOCK | ERROR      -- the machine-read severity
    line 2   (blank)
    line 3+  the Markdown comment body, empty on PASS

The body opens with an HTML marker comment (`<!-- review-<role> -->`) so the
job can edit its own previous comment instead of stacking a new one on every
push -- one comment per role, the way the workflow-change guard and the
spec-conformance gate each keep exactly one.

Usage:
    parse_review_verdict.py --reviewer engineer < reviewer-output.txt
    parse_review_verdict.py --reviewer sre --context .factory/project_context.md
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from renderer.validators import ProjectContextError, validate_project_context  # noqa: E402
from reviewers.verdicts import (  # noqa: E402
    Finding,
    ParsedVerdict,
    VerdictParseError,
    VerdictParser,
)

__all__ = [
    "EXIT_BLOCK",
    "EXIT_OK",
    "EXIT_PARSE_ERROR",
    "build_comment",
    "load_project_invariants",
    "main",
]

#: PASS or WARN -- the reviewer reviewed and did not block.
EXIT_OK = 0
#: BLOCK -- a hard merge-fail.
EXIT_BLOCK = 1
#: The verdict could not be read at all. Also a merge-fail, for a different reason.
EXIT_PARSE_ERROR = 2

#: Where this repository's declared invariant ids live.
DEFAULT_CONTEXT = REPO_ROOT / ".factory" / "project_context.md"

#: The three reviewers. Kept as a choice list so a typo in ci.yml fails the job
#: rather than silently labelling a comment after a reviewer that does not exist.
REVIEWER_ROLES = ("engineer", "architect", "sre")

_RETRY_NOTE = (
    "A retry must read every `review-*` comment on this PR before touching "
    "anything, and address each BLOCKING line or say why it is wrong. "
    "Disputing a finding does not clear it: the reviewer, not the implementing "
    "agent, decides whether the dispute holds, and the PR still has to "
    "re-review clean."
)


def load_project_invariants(context_path: Path) -> list[str]:
    """Return the invariant ids this project has declared, in file order.

    The parser rejects an `(invariant: <id>)` citation naming an id that is not
    in this list, which is what stops a reviewer manufacturing a citation to
    earn a BLOCK. Reading the list is therefore part of the gate, not setup:
    a failure here raises rather than degrading to an empty list, because the
    caller must fail the job rather than review against nothing.

    The shape of the list is `renderer.validators`' job, not this function's --
    `validate_project_context` already rejects a non-list `invariants:`, a
    non-mapping entry, and an entry missing `id`. Re-checking it here would be
    a second implementation of one rule (AGENTS.md LESSON 11).

    Args:
        context_path: Path to the project's `.factory/project_context.md`

    Returns:
        The `id` of every entry under `invariants:`, in file order. Empty is
        legal: a project may declare none and have its reviewers cite `spec:`
        and `scope:` instead.

    Raises:
        ProjectContextError: If the file is missing or fails schema validation
    """
    data = validate_project_context(context_path)
    return [str(entry["id"]) for entry in data["invariants"]]


def _bullets(findings: list[Finding], bucket: str) -> list[str]:
    """Render the findings in one bucket as Markdown list items."""
    return [f"- {finding.text}" for finding in findings if finding.bucket == bucket]


def build_comment(verdict: ParsedVerdict) -> str:
    """Render the PR comment body for a successfully parsed verdict.

    Args:
        verdict: The parsed verdict, whose `reviewer` names the role

    Returns:
        Markdown beginning with the per-role marker comment, or the empty
        string for PASS -- a silent pass posts nothing
    """
    if verdict.severity == "PASS":
        return ""

    blocking = _bullets(verdict.findings, "bad")
    warnings = _bullets(verdict.findings, "ugly")

    lines = [
        marker(verdict.reviewer),
        "",
        f"### Reviewer verdict — `{verdict.reviewer}`: **{verdict.severity}**",
        "",
    ]

    if verdict.severity == "BLOCK":
        lines += [
            "A BLOCK is a hard merge-fail. This PR does not auto-merge. The ways "
            "past it are a push that re-reviews clean, or a human merging it by hand.",
            "",
            "**BLOCKING**",
            "",
            *blocking,
            "",
        ]

    if warnings:
        lines += ["**WARNINGS**", "", *warnings, ""]

    lines += [_RETRY_NOTE, ""]
    return "\n".join(lines)


def build_error_comment(reviewer: str, message: str) -> str:
    """Render the PR comment body for a review that produced no usable verdict.

    Args:
        reviewer: The role whose job is failing
        message: The specific contract violation, from VerdictParseError

    Returns:
        Markdown beginning with the per-role marker comment
    """
    return "\n".join(
        [
            marker(reviewer),
            "",
            f"### Reviewer verdict — `{reviewer}`: **parse error**",
            "",
            f"The `review-{reviewer}` job could not read a verdict from this "
            "reviewer's output, so the job fails and this PR does not auto-merge. "
            "A reviewer that did not produce a verdict did not review; this is "
            "never treated as a PASS.",
            "",
            "```",
            message,
            "```",
            "",
            "The required block is specified in `templates/_shared/verdict_block.partial.md`.",
            "",
        ]
    )


def marker(reviewer: str) -> str:
    """The HTML marker that makes this role's comment findable and editable."""
    return f"<!-- review-{reviewer} -->"


def _parse(raw: str, reviewer: str, invariants: list[str]) -> ParsedVerdict:
    """Parse *raw*, keeping everything the parser prints off stdout.

    structlog's default logger factory writes to STDOUT, and `VerdictParser`
    logs on every parse. Without this the first line of stdout is a log record
    rather than the severity, and the CI step reads a log line as a verdict.
    The records are wanted -- they are the run's evidence -- just not on the
    channel that carries the contract, so they are replayed to stderr.

    Captured and replayed rather than fixed with `structlog.configure()`:
    configuration is global and binds a file object, so a caller that runs
    inside pytest's capture would hand every later test in the session a closed
    stream. The buffer is local and the `finally` replays it on the error path
    too, where the log line says which contract the review violated.

    Args:
        raw: The reviewer's final output
        reviewer: The role that produced it
        invariants: The project's declared invariant ids

    Returns:
        The parsed verdict

    Raises:
        VerdictParseError: On any violation of the verdict contract
    """
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            return VerdictParser(invariants).parse_verdict(raw, reviewer)
    finally:
        sys.stderr.write(buffer.getvalue())


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Parse a reviewer's final output on stdin. Exit 0 on PASS/WARN, "
            "1 on BLOCK, 2 on a parse error."
        ),
    )
    parser.add_argument(
        "--reviewer",
        required=True,
        choices=REVIEWER_ROLES,
        help="which reviewer produced this output",
    )
    parser.add_argument(
        "--context",
        type=Path,
        default=DEFAULT_CONTEXT,
        help="path to project_context.md, whose invariant ids citations are checked against",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Read a review on stdin, print severity + comment, return the exit code.

    Args:
        argv: Command-line arguments, defaulting to `sys.argv[1:]`

    Returns:
        EXIT_OK, EXIT_BLOCK or EXIT_PARSE_ERROR
    """
    args = _build_parser().parse_args(argv)
    reviewer: str = args.reviewer

    try:
        invariants = load_project_invariants(args.context)
    except ProjectContextError as error:
        # Not the reviewer's fault, but it fails the same way and for the same
        # reason: nothing has established that this change was reviewed.
        message = f"could not read declared invariant ids: {error}"
        print("ERROR")
        print()
        print(build_error_comment(reviewer, message), end="")
        print(f"parse_review_verdict: {message}", file=sys.stderr)
        return EXIT_PARSE_ERROR

    raw = sys.stdin.read()

    try:
        verdict = _parse(raw, reviewer, invariants)
    except VerdictParseError as error:
        print("ERROR")
        print()
        print(build_error_comment(reviewer, str(error)), end="")
        print(f"parse_review_verdict: {error}", file=sys.stderr)
        return EXIT_PARSE_ERROR

    print(verdict.severity)
    print()
    print(build_comment(verdict), end="")

    return EXIT_BLOCK if verdict.severity == "BLOCK" else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

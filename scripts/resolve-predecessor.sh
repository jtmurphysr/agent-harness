#!/usr/bin/env bash
# resolve-predecessor.sh — turn an issue body's DEPENDS ON line into a verdict.
#
# WHY THIS IS A SCRIPT: the sequential gate lived inline in agent-dispatch.yml at
# two sites (dispatch and retry) with no tests, and it failed OPEN — any
# predecessor it could not resolve by canonical title was "assumed satisfied".
# Every GC-filed issue, every coverage issue, and every hand-written
# `DEPENDS ON: #N` with a plain GitHub number was therefore never gated at all.
# The sequential model held only for prd-to-issues output, and only by accident
# of that output's title format. See issue #11.
#
# The CI job that tests the hook library carries this note: "seven fail-open
# bugs shipped before this job existed. Reading them did not catch any." This
# gate was the eighth. It is now one implementation, called from both sites,
# with tests in test-resolve-predecessor.sh.
#
# Usage:
#   resolve-predecessor.sh <repo> < issue_body
#
# Reads the issue body on stdin. Prints exactly one line to stdout:
#   proceed                          no DEPENDS ON line, or predecessor is CLOSED
#   blocked <gh_number> <state>      predecessor exists and is not CLOSED
#   unresolved <ref>                 DEPENDS ON names something that cannot be found
#
# Exit code is 0 for all three verdicts -- the CALLER decides what each means.
# A non-zero exit is reserved for the script itself failing (bad args, gh error
# on a call that must succeed), so the caller can tell "gate said no" apart
# from "gate is broken". A broken gate must never look like a passed one.
#
# Resolution order:
#   1. The FIRST #N on the first DEPENDS ON line, treated as a GitHub issue number
#      and looked up directly. This is what humans and the GC agent write.
#   2. If that issue does not exist, the same N as a CANONICAL harness number,
#      resolved by title "Issue #0*N:". This is what old prd-to-issues bodies
#      relied on, where the line read "#78 — Issue #018: ..." and the greedy
#      extractor happened to land on 018.
#   3. Neither -> unresolved. Never "assumed satisfied".
#
# Override for tests: GH_ISSUE_LOOKUP names a function or command that takes
# (repo, number) and prints the issue's state, or nothing if it does not exist;
# GH_TITLE_LOOKUP takes (repo, canonical) and prints the GitHub number, or nothing.

set -uo pipefail

repo="${1:?usage: resolve-predecessor.sh <repo> < issue_body}"

# Default lookups hit GitHub. Tests replace these.
default_issue_lookup() {
    # $1 repo, $2 number -> state on stdout, empty if the issue does not exist.
    gh issue view "$2" --repo "$1" --json state -q '.state' 2>/dev/null || true
}
default_title_lookup() {
    # $1 repo, $2 canonical -> GitHub number on stdout, empty if none.
    gh issue list --repo "$1" --state all --limit 200 --json number,title \
        -q ".[] | select(.title | test(\"^Issue #0*${2}[^0-9]\")) | .number" 2>/dev/null \
        | head -1
}
issue_lookup="${GH_ISSUE_LOOKUP:-default_issue_lookup}"
title_lookup="${GH_TITLE_LOOKUP:-default_title_lookup}"

body=$(cat)

# First DEPENDS ON line, first #N on it. `head -1` twice on purpose: one line,
# one ref. A body with two DEPENDS ON lines is malformed and we take the first
# rather than guess.
line=$(printf '%s\n' "$body" | grep -m1 'DEPENDS ON:' || true)
if [ -z "$line" ]; then
    echo "proceed"
    exit 0
fi
ref=$(printf '%s\n' "$line" | grep -oE '#[0-9]+' | head -1 | tr -d '#' || true)
if [ -z "$ref" ]; then
    # A DEPENDS ON line with no #N at all. That is a typo, not "no dependency".
    echo "unresolved ${line}"
    exit 0
fi
# Strip leading zeros so "#018" and "#18" are the same issue.
ref=$((10#$ref))

# 1. Direct GitHub lookup.
state=$("$issue_lookup" "$repo" "$ref")
if [ -n "$state" ]; then
    if [ "$state" = "CLOSED" ]; then echo "proceed"; else echo "blocked $ref $state"; fi
    exit 0
fi

# 2. Canonical-title fallback.
gh_num=$("$title_lookup" "$repo" "$ref")
if [ -n "$gh_num" ]; then
    state=$("$issue_lookup" "$repo" "$gh_num")
    if [ "$state" = "CLOSED" ]; then echo "proceed"; else echo "blocked $gh_num ${state:-UNKNOWN}"; fi
    exit 0
fi

# 3. Fail closed.
echo "unresolved #${ref}"
exit 0

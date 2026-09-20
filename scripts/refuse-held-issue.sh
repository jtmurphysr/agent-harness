#!/usr/bin/env bash
# refuse-held-issue.sh — is this issue held for a human, or clear to dispatch?
#
# WHY THIS IS A SCRIPT: agent-dispatch.yml checked `human-review` and
# `harness-gap` only in the `issues` branch of its job-level `if:`. The
# `workflow_dispatch` branch — which is how close-issue-on-merge.yml advances
# the chain to N+1 after every merge — had no label check at all, because a
# workflow_dispatch payload carries no issue for an `if:` to read. The caller
# said "dispatch unconditionally, the dispatcher gates"; the dispatcher gated
# only the path the caller did not use. On 2026-09-20 that put an agent on
# a `human-review` + `harness-gap` issue seconds after its predecessor merged.
# See issue #26.
#
# This is the ninth fail-open gate this repo has found by being bitten. Like
# resolve-predecessor.sh it is one implementation, called from one job that
# both dispatch paths depend on, with tests in test-refuse-held-issue.sh.
#
# Usage:
#   refuse-held-issue.sh <repo> <issue_number>
#
# Prints exactly one line to stdout:
#   clear              no holding label present
#   held <label>       the first holding label found, in the order below
#
# Exit code is 0 for both verdicts -- the CALLER decides what each means.
# A non-zero exit means the script itself failed (bad args, the label read
# did not succeed). The caller MUST treat that as held: a gate that cannot
# read its input has not passed.
#
# Holding labels, in precedence order:
#   human-review   a human has not decided yet
#   harness-gap    the pipeline itself is missing something; belongs upstream
#
# Override for tests: GH_LABEL_LOOKUP names a function or command that takes
# (repo, number) and prints the issue's label names one per line, exiting
# non-zero if the lookup failed.

set -uo pipefail

repo="${1:?usage: refuse-held-issue.sh <repo> <issue_number>}"
number="${2:?usage: refuse-held-issue.sh <repo> <issue_number>}"

case "$number" in
    ''|*[!0-9]*) echo "refuse-held-issue.sh: issue number must be digits, got '$number'" >&2; exit 2 ;;
esac

# REST, not `gh issue view --json labels`: that goes through GraphQL and needs
# read:org, which GH_PAT deliberately does not have (see workflow-guard).
default_label_lookup() {
    gh api "repos/$1/issues/$2/labels" -q '.[].name'
}

label_lookup="${GH_LABEL_LOOKUP:-default_label_lookup}"

# Capture output and status separately so a failed read cannot be mistaken
# for "no labels". `$(...)` alone would hand an empty string to the loop
# below, and empty means clear -- which is precisely the failure this
# script exists to prevent.
if ! labels=$("$label_lookup" "$repo" "$number"); then
    echo "refuse-held-issue.sh: could not read labels for $repo#$number" >&2
    exit 1
fi

for holding in human-review harness-gap; do
    if printf '%s\n' "$labels" | grep -qx "$holding"; then
        echo "held $holding"
        exit 0
    fi
done

echo "clear"

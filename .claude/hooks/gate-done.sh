#!/usr/bin/env bash
# Stop — gate "done" on evidence, not on the model's opinion.
#
# The model declaring completion is a claim. A green suite is a receipt.
# Mirrors what CI runs (.github/workflows), cheapest check first so a failing
# lint doesn't wait on a full pytest run.
#
# FAIL CLOSED. "The checks did not run" is not "the code is clean." Every path
# out of here that isn't a verified pass exits 2.
#
# Exit 2 on Stop prevents the agent from stopping and feeds stderr back as the
# reason to keep working. exit 1 would do nothing at all.

set -uo pipefail
HOOK_NAME="gate-done"

# Bootstrap guard. die_closed lives in the preamble, which lives behind this
# variable, so it does not exist yet -- and BOTH `set -u` on a bare $VAR and the
# ${VAR:?msg} form exit 1, which is NON-BLOCKING. A fail-closed gate that exits 1
# is a gate that silently is not there. Exit 2 by hand, before the source.
if [ -z "${CLAUDE_PROJECT_DIR:-}" ]; then
  echo "[$HOOK_NAME] BLOCKED — CLAUDE_PROJECT_DIR unset; cannot locate hook library" >&2
  exit 2
fi
source "$CLAUDE_PROJECT_DIR/.claude/hooks/lib/preamble.sh"

# git joins jq as a hard dependency: py_touched() decides whether an absent
# pytest is a gap in the evidence or simply nothing to check, and it needs git
# to answer. require() dies closed, which is the right posture -- a repo gate
# that cannot read the repo should block, not shrug.
require jq git

PAYLOAD=$(read_payload) || die_closed "empty stdin payload"

# Not optional: without this, our own exit 2 re-triggers Stop and loops forever.
[ "$(field_opt '.stop_hook_active' 'false')" = "true" ] && exit 0

cd "$CLAUDE_PROJECT_DIR" || die_closed "cannot cd to $CLAUDE_PROJECT_DIR"

PY="${HARNESS_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || die_closed "python interpreter not found: $PY"

fail() {
  # tail, not the whole log: past 10k chars this becomes a file path, which is
  # not feedback a model can act on.
  { echo "$1"; shift; printf '%s\n' "$@" | tail -40; } | clamp >&2
  exit 2
}

# Did this turn touch Python? Uncommitted work, staged work, untracked files,
# and anything committed locally that the upstream does not have yet -- an agent
# may edit and stop, or commit and stop, and both are "this turn."
#
# Returns TRUE when it cannot tell. A gate that answers "nothing changed"
# because git was unavailable would skip the suite exactly when it is least
# entitled to.
py_touched() {
  git rev-parse --git-dir >/dev/null 2>&1 || return 0
  {
    git diff --name-only HEAD 2>/dev/null
    git diff --name-only --cached 2>/dev/null
    git ls-files --others --exclude-standard 2>/dev/null
    local up
    if up=$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null); then
      git diff --name-only "$up...HEAD" 2>/dev/null
    fi
  } | grep -qE '\.py$'
}

# ---- 1. structural invariants (stdlib only, fast, no install needed) ---------
# validate_harness.py exits 1 on violations. Exit 1 blocks NOTHING in a hook, so
# the translation to 2 below is the whole point -- wire the script in directly
# and the gate silently passes on every violation it finds.
if ! harness_out=$("$PY" scripts/validate_harness.py 2>&1); then
  fail "Module boundary / coverage violations. You are not done." "$harness_out"
fi

# ---- 2. test suite ----------------------------------------------------------
# No set +e/-e dance here. errexit was never on (header is `set -uo pipefail`),
# so `set +e` would be a no-op and the matching `set -e` would ENABLE errexit
# for everything after it -- under which any stray non-zero exits 1, which is
# non-blocking, and this gate silently passes. Capturing rc directly needs no
# errexit change at all.
# Precondition check, not post-hoc rc analysis. `python -m <missing module>`
# exits 1 -- and so does pytest's own "tests ran and failed." Identical by rc,
# trivially different by output. The 2|3|4 branch below was written for exactly
# the unprovisioned-environment case and never saw it, because 1 is not in that
# list; an absent pytest fell through to *) and reported a failing suite on a
# machine that had no suite. Found live by the compound-learning agent on PR #4.
if ! "$PY" -c 'import pytest' >/dev/null 2>&1; then
  if py_touched; then
    fail "pytest is not importable and this turn changed Python files — the gate could not verify this work.
If this is a fresh checkout, the environment is not provisioned:
    pip install -e \".[dev]\"
Fail-closed by design: 'the tests did not run' is not 'the tests passed.'"
  fi
  # No pytest and no Python touched: there is no evidence to gather, so demanding
  # it is not rigour. compound-learning.yml runs in a job with no setup-python and
  # no pip install, and its only output is a Markdown file -- gating prose behind
  # a test runner that cannot exist there blocks every run of it forever.
  # Structural invariants above still ran, and still had to pass.
  echo "[$HOOK_NAME] no pytest, no Python changed this turn — suite skipped; validate_harness passed" >&2
  exit 0
fi

test_out=$("$PY" -m pytest tests/ -q -m "not slow" 2>&1)
rc=$?

case "$rc" in
  0) ;;
  5) fail "pytest collected no tests — the gate cannot verify anything." "$test_out" ;;
  2|3|4)
    # Interrupted / internal / usage error. Almost always an unprovisioned
    # environment rather than bad code, so say the fix out loud instead of
    # handing back a wall of ImportErrors.
    fail "Test suite could not run (pytest rc=$rc) — the gate could not verify this work.
If this is a fresh checkout, the environment is not provisioned:
    pip install -e \".[dev]\"
Fail-closed by design: 'the tests did not run' is not 'the tests passed.'" "$test_out"
    ;;
  *) fail "Test suite is failing. You are not done." "$test_out" ;;
esac

echo "[$HOOK_NAME] validate_harness + pytest green" >&2
exit 0

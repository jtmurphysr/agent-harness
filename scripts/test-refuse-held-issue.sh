#!/usr/bin/env bash
# Tests for scripts/refuse-held-issue.sh — the holding-label dispatch gate.
#
# WHY THIS EXISTS: the check lived in a job-level `if:` that only one of the
# two dispatch paths went through. The other path dispatched a human-review
# issue the moment its predecessor merged (issue #26). Each case below is a
# label set an issue in this repo or downstream has actually carried, plus the
# two ways the lookup itself can go wrong.
#
# Run:  scripts/test-refuse-held-issue.sh
# Exit: 0 all passed, 1 any failure. Wired into the hook-tests CI job.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

pass=0 fail=0
ok()  { pass=$((pass+1)); printf '  ok   %s\n' "$1"; }
no()  { fail=$((fail+1)); printf '  FAIL %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
is()  { [ "$2" = "$3" ] && ok "$1" || no "$1" "$2" "$3"; }

# A fake GitHub: issue number -> label list. 99 is the lookup failing.
fake_labels() {
    case "$2" in
        1) printf 'agent-task\n' ;;
        2) printf 'agent-task\nhuman-review\n' ;;
        3) printf 'harness-gap\n' ;;
        4) printf 'human-review\nharness-gap\n' ;;
        5) printf 'gc\nagent-task\n' ;;
        6) ;;                                   # no labels at all
        7) printf 'human-review-later\nreviewed\n' ;;   # near-miss names
        99) return 1 ;;                         # API error
    esac
}
export GH_LABEL_LOOKUP=fake_labels
export -f fake_labels

run() { bash scripts/refuse-held-issue.sh org/repo "$1"; }

echo "clear to dispatch"
v=$(run 1); is "agent-task only -> clear"            "clear" "$v"
v=$(run 5); is "gc + agent-task -> clear"            "clear" "$v"
v=$(run 6); is "no labels -> clear"                  "clear" "$v"
v=$(run 7); is "near-miss label names -> clear"      "clear" "$v"

echo
echo "held for a human"
v=$(run 2); is "agent-task + human-review -> held"   "held human-review" "$v"
v=$(run 3); is "harness-gap alone -> held"           "held harness-gap"  "$v"
v=$(run 4); is "both -> human-review wins"           "held human-review" "$v"

echo
echo "the gate itself failing -- must not read as clear"
out=$(run 99 2>/dev/null); rc=$?
is "lookup error -> non-zero exit"                   "1" "$rc"
is "lookup error -> no verdict on stdout"            "" "$out"
out=$(bash scripts/refuse-held-issue.sh org/repo abc 2>/dev/null); rc=$?
is "non-numeric issue -> non-zero exit"              "2" "$rc"
out=$(bash scripts/refuse-held-issue.sh org/repo 2>/dev/null); rc=$?
is "missing issue arg -> non-zero exit"              "1" "$rc"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]

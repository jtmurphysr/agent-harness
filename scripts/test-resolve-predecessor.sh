#!/usr/bin/env bash
# Tests for scripts/resolve-predecessor.sh — the sequential dispatch gate.
#
# WHY THIS EXISTS: the gate lived inline in a workflow, untested, and failed open
# for every predecessor it could not resolve by canonical title. Nobody noticed
# because a gate that opens looks exactly like a gate that passed. Each case
# below is a real shape from a real DEPENDS ON line, or the boundary next to one.
#
# Run:  scripts/test-resolve-predecessor.sh
# Exit: 0 all passed, 1 any failure. Wired into the hook-tests CI job.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

pass=0 fail=0
ok()  { pass=$((pass+1)); printf '  ok   %s\n' "$1"; }
no()  { fail=$((fail+1)); printf '  FAIL %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
is()  { [ "$2" = "$3" ] && ok "$1" || no "$1" "$2" "$3"; }

# A fake GitHub. Issues that exist, with their state; canonical titles that
# resolve to a GitHub number. Nothing else exists.
fake_issue() {
    case "$2" in
        74) echo "CLOSED" ;;
        78) echo "CLOSED" ;;
        79) echo "OPEN" ;;
        18) echo "CLOSED" ;;   # exists, but is NOT the predecessor anyone means
        12) echo "OPEN" ;;
        *)  ;;                 # does not exist -> empty
    esac
}
fake_title() {
    # canonical -> GitHub number. Only #018 and #019 are prd-to-issues chain issues.
    case "$2" in
        18) echo "78" ;;
        19) echo "79" ;;
        *)  ;;
    esac
}
export GH_ISSUE_LOOKUP=fake_issue GH_TITLE_LOOKUP=fake_title
export -f fake_issue fake_title

run() { printf '%s\n' "$1" | bash scripts/resolve-predecessor.sh org/repo; }

echo "no dependency"
v=$(run 'CONTEXT: just a body');                       is "no DEPENDS ON line -> proceed" "proceed" "$v"
v=$(run '');                                            is "empty body -> proceed"         "proceed" "$v"

echo
echo "plain GitHub refs -- what humans and the GC agent write (was: gate OPEN)"
v=$(run 'DEPENDS ON: #74');                             is "closed predecessor -> proceed"   "proceed" "$v"
v=$(run 'DEPENDS ON: #79');                             is "open predecessor -> blocked"     "blocked 79 OPEN" "$v"
v=$(run 'DEPENDS ON: #74 — Coverage: conformance/monday_arc_test.py 84.69% → ≥85%')
                                                        is "GC-filed predecessor, closed -> proceed" "proceed" "$v"

echo
echo "generated chain lines -- first #N wins, canonical in the title is ignored"
v=$(run 'DEPENDS ON: #78 — Issue #018: models/ledger_entry.py — Spec §5.1')
                                                        is "#78 closed; title's #018 not consulted" "proceed" "$v"
v=$(run 'DEPENDS ON: #79 — Issue #019: models/stance.py — canonical CounterPosition')
                                                        is "#79 open -> blocked on 79, not 19" "blocked 79 OPEN" "$v"
v=$(run 'DEPENDS ON: #78 — Issue #018: fix regression from #12')
                                                        is "trailing #12 in title is NOT the predecessor" "proceed" "$v"

echo
echo "canonical fallback -- old bodies where only the canonical number resolves"
v=$(run 'DEPENDS ON: #018');                            is "#018 -> no GH #18? exists&CLOSED -> proceed" "proceed" "$v"
v=$(run 'DEPENDS ON: #019');                            is "#019 -> GH #19 absent -> canonical 19 -> #79 OPEN" "blocked 79 OPEN" "$v"
v=$(run 'DEPENDS ON: #18');                             is "leading zeros stripped: #18 == #018" "proceed" "$v"

echo
echo "fail CLOSED -- the bug this file exists for"
v=$(run 'DEPENDS ON: #999');                            is "nonexistent issue -> unresolved, NOT proceed" "unresolved #999" "$v"
v=$(run 'DEPENDS ON: see above');                       is "DEPENDS ON with no #N -> unresolved" "unresolved DEPENDS ON: see above" "$v"
v=$(run 'DEPENDS ON: #999 — Issue #018: old body');     is "bad GH ref, title has canonical -> still keyed on FIRST ref" "unresolved #999" "$v"

echo
echo "malformed bodies"
v=$(printf 'DEPENDS ON: #79\nDEPENDS ON: #74\n' | bash scripts/resolve-predecessor.sh org/repo)
                                                        is "two DEPENDS ON lines -> first wins" "blocked 79 OPEN" "$v"
v=$(run 'depends on: #79');                             is "lowercase is not the marker -> proceed" "proceed" "$v"

echo
echo "script failure is distinguishable from a verdict"
bash scripts/resolve-predecessor.sh </dev/null >/dev/null 2>&1; rc=$?
[ "$rc" -ne 0 ] && ok "missing repo arg -> non-zero exit, no verdict" || no "missing repo arg exits non-zero" "non-zero" "$rc"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]

#!/usr/bin/env bash
# Tests for the hook preamble and the hooks that use it.
#
# WHY THIS EXISTS: seven fail-open bugs were found in this hook library and its
# documentation by people reading it. Every one was invisible -- no exception, no
# non-zero exit, just a guard quietly allowing what it was written to block. A
# guide arguing that receipts beat opinions cannot ship guardrails that were only
# ever eyeballed.
#
# Each case below is a bug that actually shipped, or the boundary next to one.
#
# Run:  .claude/hooks/test-hooks.sh
# Exit: 0 all passed, 1 any failure. Wire into CI.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 1
export CLAUDE_PROJECT_DIR="$PWD"

pass=0 fail=0
ok()  { pass=$((pass+1)); printf '  ok   %s\n' "$1"; }
no()  { fail=$((fail+1)); printf '  FAIL %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
is()  { [ "$2" = "$3" ] && ok "$1" || no "$1" "$2" "$3"; }

# shellcheck source=.claude/hooks/lib/preamble.sh
source .claude/hooks/lib/preamble.sh

echo "field() — absent vs legitimately-false"
PAYLOAD='{"flag":false,"name":"abc","nil":null,"str_null":"null"}'
v=$(field '.flag');       is "false field returns the value"     "false" "$v"
field '.flag' >/dev/null 2>&1; is "false field exits 0"          "0" "$?"
v=$(field '.name');       is "string field returns the value"    "abc" "$v"
field '.absent' >/dev/null 2>&1; is "absent field exits non-zero" "1" "$?"
field '.nil' >/dev/null 2>&1;    is "JSON null exits non-zero"    "1" "$?"
# Known limitation, documented on field(): a JSON *string* "null" is
# indistinguishable from absent through jq -r's text channel.
field '.str_null' >/dev/null 2>&1; is "string \"null\" reads as absent (known)" "1" "$?"

echo
echo "field_opt() — the jq -e concatenation bug"
v=$(field_opt '.flag' 'false');   is "false field is NOT concatenated"  "false" "$v"
v=$(field_opt '.absent' 'dflt');  is "absent field yields the default"  "dflt"  "$v"
v=$(field_opt '.nil' 'dflt');     is "JSON null yields the default"     "dflt"  "$v"
v=$(field_opt '.name' 'dflt');    is "present field beats the default"  "abc"   "$v"

echo
echo "require() — multi-arg (single-arg version silently skipped extras)"
( require jq ) >/dev/null 2>&1;                     is "present dep passes"        "0" "$?"
( require jq __nope__ ) >/dev/null 2>&1;            is "missing 2nd dep exits 2"   "2" "$?"
out=$( ( require jq __nope__ ) 2>&1 >/dev/null )
case "$out" in *__nope__*) ok "names the missing dep" ;; *) no "names the missing dep" "__nope__" "$out" ;; esac

echo
echo "exit codes — 2 blocks, 1 does not"
( die_closed "x" ) >/dev/null 2>&1; is "die_closed exits 2" "2" "$?"
( warn_open  "x" ) >/dev/null 2>&1; is "warn_open exits 1"  "1" "$?"

echo
echo "clamp() — 10k output cap"
v=$(head -c 20000 /dev/zero | tr '\0' 'x' | clamp | wc -c | tr -d ' ')
[ "$v" -le 9100 ] && ok "long output clamped ($v bytes)" || no "long output clamped" "<=9100" "$v"
v=$(printf 'short' | clamp); is "short output passes through" "short" "$v"

echo
echo "bootstrap guard — the preamble cannot guard its own location"
env -u CLAUDE_PROJECT_DIR bash .claude/hooks/gate-done.sh </dev/null >/dev/null 2>&1
is "gate-done exits 2 without CLAUDE_PROJECT_DIR (fail closed)" "2" "$?"
env -u CLAUDE_PROJECT_DIR bash .claude/hooks/inject-context.sh </dev/null >/dev/null 2>&1
is "inject-context exits 1 without it (fail open, by design)"   "1" "$?"

echo
echo "gate-done — loop guard and payload handling"
echo '{"session_id":"t","stop_hook_active":true}' | bash .claude/hooks/gate-done.sh >/dev/null 2>&1
is "stop_hook_active=true short-circuits to 0" "0" "$?"
printf '' | bash .claude/hooks/gate-done.sh >/dev/null 2>&1
is "empty payload blocks" "2" "$?"
echo '{"session_id":"t","stop_hook_active":false}' | HARNESS_PYTHON=/nonexistent bash .claude/hooks/gate-done.sh >/dev/null 2>&1
is "missing interpreter blocks" "2" "$?"

echo
echo "gate-done — absent pytest is not a failing suite"
# The bug: `python -m <missing module>` exits 1, and so does pytest's own
# "tests ran and failed." Indistinguishable by rc, so an absent pytest fell
# through to the *) branch and reported failing tests on a machine with none.
# The 2|3|4 branch existed for exactly this and never saw it. Found live by the
# compound-learning agent on PR #4 -- not by anyone reading the file.
_stub=$(mktemp); trap 'rm -f "$_stub"' EXIT
cat > "$_stub" <<'STUB'
#!/usr/bin/env bash
[ "$1" = "-c" ] && [ "$2" = "import pytest" ] && exit 1
[ "$1" = "-m" ] && [ "$2" = "pytest" ] && { echo "No module named pytest" >&2; exit 1; }
exec python3 "$@"
STUB
chmod +x "$_stub"

_payload='{"session_id":"t","stop_hook_active":false}'

# These run in a scratch repo, not this one. The first version asserted against
# the ambient working tree and passed only while that tree happened to have no
# Python changes -- it broke the moment this very commit edited a .py. A test
# whose result depends on what else is dirty is not a test. The scratch repo
# also means the template case stops mutating real files under templates/.
_scratch=$(mktemp -d); trap 'rm -f "$_stub"; rm -rf "$_scratch"' EXIT
mkdir -p "$_scratch/.claude/hooks/lib" "$_scratch/scripts"
cp .claude/hooks/gate-done.sh      "$_scratch/.claude/hooks/"
cp .claude/hooks/lib/preamble.sh   "$_scratch/.claude/hooks/lib/"
: > "$_scratch/scripts/validate_harness.py"   # stub: parses, exits 0
git -C "$_scratch" init -q
git -C "$_scratch" add -A
git -C "$_scratch" -c user.email=t@t -c user.name=t commit -qm init

_gate() {  # $1 = label, $2 = expected rc; runs gate-done in the scratch repo
  echo "$_payload" | CLAUDE_PROJECT_DIR="$_scratch" HARNESS_PYTHON="$_stub" \
    bash "$_scratch/.claude/hooks/gate-done.sh" >/dev/null 2>&1
  is "$1" "$2" "$?"
}

# Clean tree: nothing for pytest to verify, so its absence is not a gap. This is
# the doc-only turn -- compound-learning.yml has no setup-python and no pip
# install, so gating a Markdown write on a test runner that cannot exist there
# would block every run of it.
_gate "absent pytest + nothing touched exits 0 (skip)" "0"

# Python touched: the gate cannot verify the change, so it must block. This
# assertion is what keeps the skip above from being a hole.
: > "$_scratch/mod.py"
_gate "absent pytest + Python touched blocks (2)" "2"
rm -f "$_scratch/mod.py"

# py_touched matched \.py$ only in its first version. tests/test_templates.py and
# tests/test_shared_partials.py assert on templates/*.md, so a template edit read
# as "nothing to verify" and skipped the very tests covering it. Found by the
# compound-learning agent one cycle after the skip path shipped, and reproduced
# before it was believed.
mkdir -p "$_scratch/templates"; : > "$_scratch/templates/x.md"
_gate "absent pytest + template touched blocks (2)" "2"
rm -rf "$_scratch/templates"

# pyproject moves the coverage floor and dependency pins, which decide whether a
# green suite means anything.
: > "$_scratch/pyproject.toml"
_gate "absent pytest + pyproject touched blocks (2)" "2"
rm -f "$_scratch/pyproject.toml"

echo
echo "inject-context — output shape and the 10k cap"
out=$(echo '{"session_id":"t","source":"startup"}' | bash .claude/hooks/inject-context.sh 2>/dev/null)
n=$(printf '%s' "$out" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"]))' 2>/dev/null || echo -1)
[ "$n" -gt 0 ] && [ "$n" -lt 10000 ] && ok "context is valid JSON and under cap ($n chars)" \
  || no "context is valid JSON and under cap" "0 < n < 10000" "$n"

echo
echo "static checks — the greps that CI runs"
# POSIX classes, not \s/\b: those are GNU extensions and match NOTHING on BSD
# grep, so the check silently passes on macOS. find, not .claude/hooks/*.sh:
# the glob does not recurse and would skip lib/preamble.sh -- the file that
# defines every helper these greps police.
# strip_comments: the first run of this suite failed on a `# Call: x=$(field ...)`
# usage comment. A check that fails a correct repo gets switched off, so it has
# to ignore comment lines to be worth having.
files=$(find .claude/hooks -name '*.sh' ! -name 'test-hooks.sh')
strip_comments() { grep -vE '^[^:]*:[0-9]+:[[:space:]]*#'; }

hits=$(echo "$files" | xargs grep -nE '\$\((field|field_opt|read_payload)[^)]*\)[[:space:]]*$' 2>/dev/null | strip_comments)
[ -z "$hits" ] && ok "no unguarded returning-helper capture" \
                || no "no unguarded returning-helper capture" "none" "$hits"

hits=$(echo "$files" | xargs grep -nE '\$\((die_closed|warn_open|require|decide|fail)[^)]*\)' 2>/dev/null | strip_comments)
[ -z "$hits" ] && ok "no exiting helper inside \$( )" \
                || no "no exiting helper inside \$( )" "none" "$hits"

# The checks must actually fire. A static check nobody has seen fail is a
# static check that may be matching nothing at all -- see the BSD grep note.
tmp=$(mktemp -d); printf 'x=$(field .a)\ny=$(die_closed "z")\n' > "$tmp/probe.sh"
n=$(grep -nE '\$\((field|field_opt|read_payload)[^)]*\)[[:space:]]*$' "$tmp/probe.sh" | strip_comments | wc -l | tr -d ' ')
is "unguarded-capture grep fires on a known-bad file" "1" "$n"
n=$(grep -nE '\$\((die_closed|warn_open|require|decide|fail)[^)]*\)' "$tmp/probe.sh" | strip_comments | wc -l | tr -d ' ')
is "exiting-helper grep fires on a known-bad file" "1" "$n"
rm -rf "$tmp"

echo
printf '%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]

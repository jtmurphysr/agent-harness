#!/usr/bin/env bash
# Tests for scripts/check-spec-conformance.sh — the spec-conformance gate.
#
# WHY THIS EXISTS: every case below is a real shape from a real PR or issue in
# this harness or downstream, or the boundary next to one. PR #103 carried a
# closing keyword for #56 and delivered half of #56's acceptance criteria and
# auto-merged; the issue left the dispatch queue permanently. Agents extended
# past FILES TO MODIFY with nothing to stop them. A PR body claimed three
# AGENTS.md edits its own diff did not contain and the claim was believed
# (LESSON 6). All three have deterministic answers, so all three are tested here
# rather than asked of a model.
#
# Run:  scripts/test-check-spec-conformance.sh
# Exit: 0 all passed, 1 any failure. Wired into the hook-tests CI job.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

pass=0 fail=0
ok()  { pass=$((pass+1)); printf '  ok   %s\n' "$1"; }
no()  { fail=$((fail+1)); printf '  FAIL %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
is()  { [ "$2" = "$3" ] && ok "$1" || no "$1" "$2" "$3"; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/empty-tree"

# ------------------------------------------------------------- fixtures ---

# Issue #56, in the shape prd-to-issues writes: an Identity table, a fenced
# Files to Modify block split read-only / modify, and a named test table.
cat > "$work/issue-56.md" <<'BODY'
# Issue #056: reviewers/verdicts.py — literal verdict parsing

## Identity

| Field | Value |
|---|---|
| **Issue Number** | `#056` |
| **Depends On** | `#055 — templates` |
| **Files to Create** | (list below) |
| **Files to Modify** | (list below) |

### Files to Create
```
reviewers/verdicts.py
tests/test_verdicts.py
```

### Files to Modify
```
# Read for context only:
AGENTS.md
docs/architecture.md

# Modify:
reviewers/__init__.py
pyproject.toml  <- coverage omit delta (see below)
```

### Out of Scope
- Do NOT change `reviewers/dispatch.py` — that is the input side.

---

## Acceptance Criteria

### Required Test Cases

| Test Function | Scenario | Expected Outcome |
|---|---|---|
| `test_missing_verdict_line_is_parse_error` | No VERDICT line | Raises |
| `test_block_without_citation_is_parse_error` | Uncited BLOCK | Raises |
| `test_unknown_invariant_is_parse_error` | Fabricated id | Raises |
| `test_<method>_<scenario>` | template placeholder | ignored by the gate |

### Coverage Requirements
- `reviewers/verdicts.py`: **100%**

---

## Definition of Done
- [ ] PR opened
BODY

# A GC-filed issue. Real, and common: prose, a coverage number, no FILES section.
cat > "$work/issue-90.md" <<'BODY'
# Coverage: reviewers/verdicts.py 84.69% -> >=85%

`reviewers/verdicts.py` sits below the per-file floor. Raise it.

## Acceptance Criteria
- Coverage at or above 85.00%
BODY

# An issue whose Files to Modify is a bullet list, not a fence.
cat > "$work/issue-70.md" <<'BODY'
# Issue #070: docs

### Files to Modify
- `docs/architecture.md`
- `docs/conventions.md`

## Acceptance Criteria
- no named tests
BODY

pr_body()   { cat "$work/pr-$2-body.md"; }
pr_branch() { cat "$work/pr-$2-branch.txt"; }
pr_files()  { cat "$work/pr-$2-files.txt"; }
pr_diff()   { cat "$work/pr-$2-diff.txt" 2>/dev/null || true; }
issue_body(){ cat "$work/issue-$2.md" 2>/dev/null || true; }
export GH_PR_BODY_LOOKUP=pr_body GH_PR_BRANCH_LOOKUP=pr_branch
export GH_PR_FILES_LOOKUP=pr_files GH_PR_DIFF_LOOKUP=pr_diff
export GH_ISSUE_BODY_LOOKUP=issue_body
export SPEC_TREE_ROOT="$work/empty-tree"
export -f pr_body pr_branch pr_files pr_diff issue_body
export work

# make_pr <n> <branch> <body-file-or-heredoc> ... via explicit writes below.
run() { bash scripts/check-spec-conformance.sh org/repo "$1"; }

# A diff that defines every test #56 names, so the default PR conforms.
full_diff() {
    cat <<'DIFF'
diff --git a/reviewers/verdicts.py b/reviewers/verdicts.py
--- a/reviewers/verdicts.py
+++ b/reviewers/verdicts.py
+def parse(self): ...
diff --git a/tests/test_verdicts.py b/tests/test_verdicts.py
--- /dev/null
+++ b/tests/test_verdicts.py
+def test_missing_verdict_line_is_parse_error(): ...
+def test_block_without_citation_is_parse_error(): ...
+def test_unknown_invariant_is_parse_error(): ...
DIFF
}

# ------------------------------------------------- the conforming baseline ---

printf 'claude/issue-56-20260920-1434\n' > "$work/pr-1-branch.txt"
cat > "$work/pr-1-body.md" <<'BODY'
Closes #56

Rewrites the parser in `reviewers/verdicts.py` and adds `tests/test_verdicts.py`.
BODY
printf 'reviewers/verdicts.py\ntests/test_verdicts.py\n' > "$work/pr-1-files.txt"
full_diff > "$work/pr-1-diff.txt"

echo "the conforming PR"
v=$(run 1); is "in scope, tests present, claims true -> pass" "pass" "$v"

# ------------------------------------------------- 1. the closing keyword ---

echo
echo "the closing keyword -- LESSON 5, invariant closing_keyword_is_executable"

cp "$work/pr-1-branch.txt" "$work/pr-2-branch.txt"
cp "$work/pr-1-files.txt"  "$work/pr-2-files.txt"
cp "$work/pr-1-diff.txt"   "$work/pr-2-diff.txt"
printf 'Rewrites the parser. Refs #56.\n' > "$work/pr-2-body.md"
v=$(run 2); is "no closing keyword -> fail" "fail no-closing-keyword" "$v"

cp "$work/pr-1-branch.txt" "$work/pr-3-branch.txt"
cp "$work/pr-1-files.txt"  "$work/pr-3-files.txt"
cp "$work/pr-1-diff.txt"   "$work/pr-3-diff.txt"
printf 'Closes #12\n\nSee `reviewers/verdicts.py`.\n' > "$work/pr-3-body.md"
v=$(run 3); is "closes an issue it was not dispatched on -> fail" "fail closes-mismatch #12 #56" "$v"

# The bug close-issue-on-merge.yml has: only the FIRST keyword is executed.
cp "$work/pr-1-branch.txt" "$work/pr-4-branch.txt"
cp "$work/pr-1-files.txt"  "$work/pr-4-files.txt"
cp "$work/pr-1-diff.txt"   "$work/pr-4-diff.txt"
printf 'Closes #12\n\nAlso Closes #56.\n' > "$work/pr-4-body.md"
v=$(run 4); is "first keyword is the one checked, not the matching one" "fail closes-mismatch #12 #56" "$v"

cp "$work/pr-1-files.txt" "$work/pr-5-files.txt"
cp "$work/pr-1-diff.txt"  "$work/pr-5-diff.txt"
cp "$work/pr-1-body.md"   "$work/pr-5-body.md"
printf 'fix/56-parser\n' > "$work/pr-5-branch.txt"
v=$(run 5); is "human branch name -> unresolved, not pass" "unresolved branch-not-dispatched fix/56-parser" "$v"

cp "$work/pr-1-branch.txt" "$work/pr-6-branch.txt"
cp "$work/pr-1-files.txt"  "$work/pr-6-files.txt"
cp "$work/pr-1-diff.txt"   "$work/pr-6-diff.txt"
printf 'closes #56\n\nSee `reviewers/verdicts.py`, `tests/test_verdicts.py`.\n' > "$work/pr-6-body.md"
v=$(run 6); is "keyword match is case-insensitive" "pass" "$v"

# ------------------------------------------------------------ 2. the spec ---

echo
echo "an issue that is not a spec -- fail CLOSED"

printf 'claude/issue-90-20260920-1434\n' > "$work/pr-7-branch.txt"
printf 'Closes #90\n' > "$work/pr-7-body.md"
printf 'reviewers/verdicts.py\n' > "$work/pr-7-files.txt"
: > "$work/pr-7-diff.txt"
v=$(run 7); is "GC-filed issue, no FILES section -> unresolved" "unresolved no-files-section #90" "$v"

printf 'claude/issue-999-20260920-1434\n' > "$work/pr-8-branch.txt"
printf 'Closes #999\n' > "$work/pr-8-body.md"
printf 'reviewers/verdicts.py\n' > "$work/pr-8-files.txt"
: > "$work/pr-8-diff.txt"
v=$(run 8); is "issue body unreadable -> unresolved" "unresolved no-issue-body #999" "$v"

# ----------------------------------------------------------- 3. the scope ---

echo
echo "scope -- files outside the FILES sections"

cp "$work/pr-1-branch.txt" "$work/pr-9-branch.txt"
cp "$work/pr-1-body.md"    "$work/pr-9-body.md"
cp "$work/pr-1-diff.txt"   "$work/pr-9-diff.txt"
printf 'reviewers/verdicts.py\nreviewers/dispatch.py\n' > "$work/pr-9-files.txt"
v=$(run 9); is "file the issue never listed -> fail scope, path named" "fail scope reviewers/dispatch.py" "$v"

# The read-only half of Files to Modify is NOT permission to modify. This is
# the distinction the whole "read for context" convention exists to draw.
cp "$work/pr-1-branch.txt" "$work/pr-10-branch.txt"
cp "$work/pr-1-body.md"    "$work/pr-10-body.md"
cp "$work/pr-1-diff.txt"   "$work/pr-10-diff.txt"
printf 'reviewers/verdicts.py\ndocs/architecture.md\n' > "$work/pr-10-files.txt"
v=$(run 10); is "read-only half of FILES TO MODIFY -> fail scope" "fail scope docs/architecture.md" "$v"

cp "$work/pr-1-branch.txt" "$work/pr-11-branch.txt"
cp "$work/pr-1-body.md"    "$work/pr-11-body.md"
cp "$work/pr-1-diff.txt"   "$work/pr-11-diff.txt"
printf 'reviewers/verdicts.py\ntests/test_verdicts.py\nreviewers/__init__.py\n' > "$work/pr-11-files.txt"
v=$(run 11); is "modify half of FILES TO MODIFY -> in scope" "pass" "$v"

cp "$work/pr-1-branch.txt" "$work/pr-12-branch.txt"
cp "$work/pr-1-body.md"    "$work/pr-12-body.md"
cp "$work/pr-1-diff.txt"   "$work/pr-12-diff.txt"
printf 'reviewers/verdicts.py\ntests/test_verdicts.py\ndocs/learnings/pr-103.md\nAGENTS.md\n' > "$work/pr-12-files.txt"
v=$(run 12); is "always-allowed set (learnings, AGENTS.md) -> pass" "pass" "$v"

# A bullet-list FILES TO MODIFY, the other shape issues are written in.
printf 'claude/issue-70-20260920-1434\n' > "$work/pr-13-branch.txt"
printf 'Closes #70\n' > "$work/pr-13-body.md"
printf 'docs/architecture.md\ndocs/conventions.md\n' > "$work/pr-13-files.txt"
: > "$work/pr-13-diff.txt"
v=$(run 13); is "bullet-list FILES TO MODIFY parses -> pass" "pass" "$v"

cp "$work/pr-13-branch.txt" "$work/pr-14-branch.txt"
cp "$work/pr-13-body.md"    "$work/pr-14-body.md"
: > "$work/pr-14-diff.txt"
printf 'docs/architecture.md\nREADME.md\n' > "$work/pr-14-files.txt"
v=$(run 14); is "bullet-list spec still bounds scope" "fail scope README.md" "$v"

# pyproject.toml is always-allowed for the coverage omit delta and nothing else.
cp "$work/pr-1-branch.txt" "$work/pr-16-branch.txt"
cp "$work/pr-1-body.md"    "$work/pr-16-body.md"
printf 'reviewers/verdicts.py\ntests/test_verdicts.py\npyproject.toml\n' > "$work/pr-16-files.txt"
{ full_diff; cat <<'DIFF'
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
-    "reviewers/verdicts.py",
DIFF
} > "$work/pr-16-diff.txt"
v=$(run 16); is "pyproject.toml, omit-list line only -> pass" "pass" "$v"

printf 'claude/issue-70-20260920-1434\n' > "$work/pr-17-branch.txt"
printf 'Closes #70\n' > "$work/pr-17-body.md"
printf 'docs/architecture.md\npyproject.toml\n' > "$work/pr-17-files.txt"
cat > "$work/pr-17-diff.txt" <<'DIFF'
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
-requires-python = ">=3.11"
+requires-python = ">=3.12"
DIFF
v=$(run 17); is "pyproject.toml, a real edit -> fail scope" "fail scope pyproject.toml" "$v"

# ------------------------------------------------------- 4. the test names ---

echo
echo "acceptance criteria -- PR #103 against issue #56"

# THIS IS PR #103. The keyword is right, the scope is right, and two of the
# three named tests are simply absent. It auto-merged.
cp "$work/pr-1-branch.txt" "$work/pr-103-branch.txt"
cat > "$work/pr-103-body.md" <<'BODY'
Closes #56

Implements the literal verdict parser in `reviewers/verdicts.py`.

Remaining work will follow in a second PR.
BODY
printf 'reviewers/verdicts.py\ntests/test_verdicts.py\n' > "$work/pr-103-files.txt"
cat > "$work/pr-103-diff.txt" <<'DIFF'
diff --git a/reviewers/verdicts.py b/reviewers/verdicts.py
--- a/reviewers/verdicts.py
+++ b/reviewers/verdicts.py
+def parse(self): ...
diff --git a/tests/test_verdicts.py b/tests/test_verdicts.py
--- /dev/null
+++ b/tests/test_verdicts.py
+def test_missing_verdict_line_is_parse_error(): ...
DIFF
v=$(run 103); is "half the acceptance criteria -> fail, naming the test" \
    "fail missing-test test_block_without_citation_is_parse_error" "$v"

# A named test that already exists in the tree is delivered, not missing.
mkdir -p "$work/tree-with-tests"
cat > "$work/tree-with-tests/test_verdicts.py" <<'PY'
def test_block_without_citation_is_parse_error(): ...
def test_unknown_invariant_is_parse_error(): ...
PY
cp "$work/pr-103-branch.txt" "$work/pr-18-branch.txt"
cp "$work/pr-103-body.md"    "$work/pr-18-body.md"
cp "$work/pr-103-files.txt"  "$work/pr-18-files.txt"
cp "$work/pr-103-diff.txt"   "$work/pr-18-diff.txt"
v=$(SPEC_TREE_ROOT="$work/tree-with-tests" run 18)
is "named test already in the tree counts as delivered" "pass" "$v"

# `test_<method>_<scenario>` in the issue template is a placeholder, not a
# requirement. A gate that demanded it would fail every PR.
cp "$work/pr-1-branch.txt" "$work/pr-19-branch.txt"
cp "$work/pr-1-body.md"    "$work/pr-19-body.md"
cp "$work/pr-1-files.txt"  "$work/pr-19-files.txt"
cp "$work/pr-1-diff.txt"   "$work/pr-19-diff.txt"
v=$(run 19); is "angle-bracket placeholder test names are ignored" "pass" "$v"

# --------------------------------------------------- 5. the claimed paths ---

echo
echo "claimed-not-changed -- LESSON 6 as a check"

cp "$work/pr-1-branch.txt" "$work/pr-20-branch.txt"
cp "$work/pr-1-files.txt"  "$work/pr-20-files.txt"
cp "$work/pr-1-diff.txt"   "$work/pr-20-diff.txt"
cat > "$work/pr-20-body.md" <<'BODY'
Closes #56

Rewrites `reviewers/verdicts.py`, adds `tests/test_verdicts.py`, and records the
three new lessons in `AGENTS.md`.
BODY
v=$(run 20); is "PR body claims an edit its diff does not contain -> fail" \
    "fail claimed-not-changed AGENTS.md" "$v"

# Fenced illustration is not a claim about this diff.
cp "$work/pr-1-branch.txt" "$work/pr-21-branch.txt"
cp "$work/pr-1-files.txt"  "$work/pr-21-files.txt"
cp "$work/pr-1-diff.txt"   "$work/pr-21-diff.txt"
cat > "$work/pr-21-body.md" <<'BODY'
Closes #56

Rewrites `reviewers/verdicts.py` and `tests/test_verdicts.py`.

Run it with:

```
pytest tests/test_verdicts.py -q
python scripts/validate_harness.py
```
BODY
v=$(run 21); is "paths inside a fence are illustration, not a claim" "pass" "$v"

# Prose in backticks is not a path.
cp "$work/pr-1-branch.txt" "$work/pr-22-branch.txt"
cp "$work/pr-1-files.txt"  "$work/pr-22-files.txt"
cp "$work/pr-1-diff.txt"   "$work/pr-22-diff.txt"
cat > "$work/pr-22-body.md" <<'BODY'
Closes #56

`VerdictParser` now reads the `VERDICT:` line of `reviewers/verdicts.py`
literally. `_determine_severity` is gone. See `tests/test_verdicts.py`.
BODY
v=$(run 22); is "backticked symbols are not paths" "pass" "$v"

# ------------------------------------------ the script itself failing ---

echo
echo "script failure is distinguishable from a verdict"
out=$(bash scripts/check-spec-conformance.sh org/repo abc 2>/dev/null); rc=$?
is "non-numeric PR -> non-zero exit" "2" "$rc"
is "non-numeric PR -> no verdict on stdout" "" "$out"
out=$(bash scripts/check-spec-conformance.sh org/repo 2>/dev/null); rc=$?
is "missing PR arg -> non-zero exit" "1" "$rc"
out=$(bash scripts/check-spec-conformance.sh 2>/dev/null); rc=$?
is "missing repo arg -> non-zero exit" "1" "$rc"

broken() { return 1; }
export -f broken
out=$(GH_PR_BODY_LOOKUP=broken run 1 2>/dev/null); rc=$?
is "PR body read error -> non-zero exit" "1" "$rc"
is "PR body read error -> no verdict on stdout" "" "$out"

echo
printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]

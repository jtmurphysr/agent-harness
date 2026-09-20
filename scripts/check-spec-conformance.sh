#!/usr/bin/env bash
# check-spec-conformance.sh — does this PR deliver the issue it was dispatched on?
#
# WHY THIS IS A SCRIPT AND NOT A REVIEWER: three failures in the harness lessons
# list were charged to "no reviewer" and every one of them has a deterministic
# answer. PR #103 wrote a closing keyword for #56 and delivered half of it. Agents
# extended past FILES TO MODIFY. A PR body claimed three AGENTS.md edits its own
# diff did not contain (LESSON 6). A model reading a diff is the wrong tool for a
# question a script can answer, and it is worse than a script, because it will
# sometimes say yes. Nothing here needs a model call.
#
# Usage:
#   check-spec-conformance.sh <repo> <pr_number>
#
# Prints exactly one line to stdout:
#   pass
#   fail <reason> [detail]        the PR does not conform; detail names the thing
#   unresolved <reason> [detail]  the question cannot be answered from the inputs
#
# Exit code is 0 for all three verdicts -- the CALLER decides what each means.
# A non-zero exit is reserved for the script itself failing (bad args, a gh call
# that must succeed erroring), so "gate said no" stays distinguishable from
# "gate is broken". The caller must fail CLOSED on `unresolved` as well as on
# `fail`: an issue this script cannot read as a spec is not a spec, and a PR
# whose scope cannot be bounded has not been shown to be in scope
# (invariant: gate_fails_closed).
#
# Reasons, in the order they are checked:
#   fail no-closing-keyword            PR body has no closing keyword at all
#   fail closes-mismatch <a> <b>       it closes #a; the branch was dispatched for #b
#                                      (invariant: closing_keyword_is_executable)
#   unresolved branch-not-dispatched   head branch is not claude/issue-<N>-...
#   unresolved no-issue-body <n>       the issue body could not be read
#   unresolved no-files-section <n>    the issue declares no files; it is not a spec
#   fail scope <path>                  a changed file is outside the FILES sections
#   fail missing-test <name>           an ACCEPTANCE CRITERIA test is nowhere
#   fail claimed-not-changed <path>    PR body backticks a path its diff does not touch
#
# Override for tests, same pattern as resolve-predecessor.sh and
# refuse-held-issue.sh -- each names a function or command:
#   GH_PR_BODY_LOOKUP    (repo, pr) -> PR body
#   GH_PR_BRANCH_LOOKUP  (repo, pr) -> head branch name
#   GH_PR_FILES_LOOKUP   (repo, pr) -> changed paths, one per line
#   GH_PR_DIFF_LOOKUP    (repo, pr) -> unified diff
#   GH_ISSUE_BODY_LOOKUP (repo, n)  -> issue body
#   SPEC_TREE_ROOT                  -> where to look for pre-existing tests (default .)

set -uo pipefail

repo="${1:?usage: check-spec-conformance.sh <repo> <pr_number>}"
pr="${2:?usage: check-spec-conformance.sh <repo> <pr_number>}"

case "$pr" in
    ''|*[!0-9]*) echo "check-spec-conformance.sh: PR number must be digits, got '$pr'" >&2; exit 2 ;;
esac

# REST throughout, never `gh pr view --json`: that goes through GraphQL and needs
# read:org, which GH_PAT deliberately does not have. The workflow-change guard
# learned this on its own first run.
default_pr_body()   { gh api "repos/$1/pulls/$2" -q '.body'; }
default_pr_branch() { gh api "repos/$1/pulls/$2" -q '.head.ref'; }
default_pr_files()  { gh api "repos/$1/pulls/$2/files" --paginate -q '.[].filename'; }
default_pr_diff()   { gh api "repos/$1/pulls/$2" -H 'Accept: application/vnd.github.v3.diff'; }
default_issue_body(){ gh api "repos/$1/issues/$2" -q '.body'; }

pr_body_lookup="${GH_PR_BODY_LOOKUP:-default_pr_body}"
pr_branch_lookup="${GH_PR_BRANCH_LOOKUP:-default_pr_branch}"
pr_files_lookup="${GH_PR_FILES_LOOKUP:-default_pr_files}"
pr_diff_lookup="${GH_PR_DIFF_LOOKUP:-default_pr_diff}"
issue_body_lookup="${GH_ISSUE_BODY_LOOKUP:-default_issue_body}"
tree_root="${SPEC_TREE_ROOT:-.}"

# ---------------------------------------------------------------- helpers ---

# Does a token look like a repository path? Deliberately narrow: a bare word is
# prose, and treating prose as a path turns step 5 into noise. A path has a
# slash or an extension, and nothing but path characters.
is_path() {
    case "$1" in
        *[!A-Za-z0-9_./-]*|''|-*|.) return 1 ;;
    esac
    case "$1" in
        */*) return 0 ;;
        *.py|*.sh|*.md|*.yml|*.yaml|*.toml|*.json|*.cfg|*.ini|*.txt|*.lock) return 0 ;;
        *) return 1 ;;
    esac
}

# Is <path> covered by <pattern>? A pattern ending in / covers everything under it.
covers() {
    local pattern="$1" path="$2"
    case "$pattern" in
        */) case "$path" in "$pattern"*) return 0 ;; esac ;;
        *)  [ "$pattern" = "$path" ] && return 0 ;;
    esac
    return 1
}

# Pull the FILES / ACCEPTANCE CRITERIA declarations out of an issue body.
#
# Emits one `<kind> <value>` per line, kind in create|modify|readonly|test.
# Issue bodies in this harness write the file lists three ways -- an Identity
# table row, a fenced block under `### Files to Modify`, and a bullet list --
# and the fenced form splits itself into a read-for-context half and a modify
# half with `#` comments. Only the modify half grants permission to change a
# file, which is the whole point of listing the other half.
extract_spec() {
    awk '
    function emit(kind, tok) {
        gsub(/^[`"]+|[`"]+$/, "", tok)
        if (tok != "" && tolower(tok) != "none") print kind " " tok
    }
    function backticks(line, kind,   rest, tok, p) {
        rest = line
        while (match(rest, /`[^`]+`/)) {
            tok = substr(rest, RSTART + 1, RLENGTH - 2)
            rest = substr(rest, RSTART + RLENGTH)
            emit(kind, tok)
        }
    }
    BEGIN { sec = ""; level = 0; ro = 0; fence = 0 }
    {
        line = $0
        low = tolower(line)

        if (line ~ /^[ \t]*(```|~~~)/) { fence = !fence; next }

        if (!fence && line ~ /^#+[ \t]/) {
            h = line; sub(/[^#].*$/, "", h); n = length(h)
            if (low ~ /^#+[ \t]*files to create[ \t]*:?[ \t]*$/)      { sec = "create"; level = n; ro = 0; next }
            if (low ~ /^#+[ \t]*files to modify[ \t]*:?[ \t]*$/)      { sec = "modify"; level = n; ro = 0; next }
            if (low ~ /^#+[ \t]*acceptance criteria[ \t]*:?[ \t]*$/)  { sec = "accept"; level = n; ro = 0; next }
            if (sec != "" && n <= level) { sec = "" }
            next
        }
        if (!fence && line ~ /^[ \t]*(---|===)[ \t]*$/) { sec = ""; next }

        # Identity table rows carry the same lists in one line each.
        if (low ~ /^\|[ \t]*\*\*files to create\*\*[ \t]*\|/) { backticks(line, "create"); next }
        if (low ~ /^\|[ \t]*\*\*files to modify\*\*[ \t]*\|/) { backticks(line, "modify"); next }

        if (sec == "") next

        if (sec == "accept") {
            rest = line
            while (match(rest, /`[^`]+`/)) {
                tok = substr(rest, RSTART + 1, RLENGTH - 2)
                rest = substr(rest, RSTART + RLENGTH)
                if (tok ~ /^test_[a-z0-9_]+$/) print "test " tok
            }
            next
        }

        # Read-only / modify split inside the FILES TO MODIFY block.
        if (low ~ /read[ -]?(only|for context)/ || low ~ /context[ \t]*only/) { ro = 1; next }
        if (low ~ /^[ \t]*[#*]*[ \t]*(modify|edit|change)[ \t]*:?[ \t]*\**[ \t]*$/) { ro = 0; next }

        kind = (sec == "modify" && ro) ? "readonly" : sec

        if (fence) {
            # A fenced FILES block is one bare path per line. `pyproject.toml
            # <- coverage omit delta (see below)` is the shape that makes the
            # first field, not the whole line, the path.
            t = line
            sub(/[ \t]*#.*$/, "", t)
            gsub(/^[ \t]+|[ \t]+$/, "", t)
            sub(/[ \t].*$/, "", t)
            emit(kind, t)
            next
        }

        backticks(line, kind)
    }
    '
}

# The `+` side of the diff, for "was this test actually written".
added_lines() { grep -E '^\+' 2>/dev/null | grep -Ev '^\+\+\+' 2>/dev/null || true; }

# Is the pyproject.toml change confined to the coverage omit list? The issue
# template's Coverage Omit Delta asks every agent to edit that list, so the file
# is always-allowed for that edit and for no other.
pyproject_is_omit_only() {
    local diff="$1" hunk
    hunk=$(printf '%s\n' "$diff" | awk '
        /^diff --git / { inf = ($0 ~ /[ \/]pyproject\.toml$/) }
        inf { print }
    ')
    [ -n "$hunk" ] || return 1
    local changed
    changed=$(printf '%s\n' "$hunk" | grep -E '^[+-]' | grep -Ev '^(\+\+\+|---)' || true)
    [ -n "$changed" ] || return 1
    # Every changed line must be a quoted list entry, the omit key, or a bracket.
    if printf '%s\n' "$changed" \
        | grep -qEv '^[+-][[:space:]]*("[^"]*",?|#.*|omit[[:space:]]*=.*|\][[:space:]]*,?|\[)?[[:space:]]*$'; then
        return 1
    fi
    return 0
}

# ------------------------------------------------------------- step 1 & 2 ---

if ! body=$("$pr_body_lookup" "$repo" "$pr"); then
    echo "check-spec-conformance.sh: could not read PR body for $repo#$pr" >&2
    exit 1
fi

# The FIRST closing keyword, and the same regex close-issue-on-merge.yml acts on.
# Anything later in the body is not what GitHub will execute.
closes=$(printf '%s\n' "$body" | grep -ioE 'closes[[:space:]]+#[0-9]+' | head -1 | grep -oE '[0-9]+' || true)
if [ -z "$closes" ]; then
    echo "fail no-closing-keyword"
    exit 0
fi

if ! branch=$("$pr_branch_lookup" "$repo" "$pr"); then
    echo "check-spec-conformance.sh: could not read head branch for $repo#$pr" >&2
    exit 1
fi
dispatched=$(printf '%s\n' "$branch" | sed -nE 's#^claude/issue-([0-9]+)([-/].*)?$#\1#p' | head -1)
if [ -z "$dispatched" ]; then
    echo "unresolved branch-not-dispatched ${branch:-<empty>}"
    exit 0
fi

if [ "$((10#$closes))" -ne "$((10#$dispatched))" ]; then
    echo "fail closes-mismatch #$closes #$dispatched"
    exit 0
fi

# ------------------------------------------------------------- inputs ---

if ! issue_body=$("$issue_body_lookup" "$repo" "$dispatched"); then
    echo "check-spec-conformance.sh: could not read issue body for $repo#$dispatched" >&2
    exit 1
fi
if [ -z "${issue_body//[[:space:]]/}" ]; then
    echo "unresolved no-issue-body #$dispatched"
    exit 0
fi

if ! changed=$("$pr_files_lookup" "$repo" "$pr"); then
    echo "check-spec-conformance.sh: could not read changed files for $repo#$pr" >&2
    exit 1
fi
diff=$("$pr_diff_lookup" "$repo" "$pr" || true)

spec=$(printf '%s\n' "$issue_body" | extract_spec)
allowed=$(printf '%s\n' "$spec" | sed -nE 's/^(create|modify) //p' | sort -u)

# --------------------------------------------------------------- step 3 ---

if [ -z "${allowed//[[:space:]]/}" ]; then
    # No FILES section at all -- a GC-filed or hand-written issue. There is no
    # spec to conform to, so there is nothing this gate can certify. Fail closed.
    echo "unresolved no-files-section #$dispatched"
    exit 0
fi

# `.claude/agents/` is rendered output, allowed only alongside a source change
# under `docs/agents/`, so a hand-edit of a generated file still fails scope.
agents_docs_changed=false
if printf '%s\n' "$changed" | grep -q '^docs/agents/'; then agents_docs_changed=true; fi

while IFS= read -r path; do
    [ -n "$path" ] || continue

    ok=false
    while IFS= read -r pattern; do
        [ -n "$pattern" ] || continue
        if covers "$pattern" "$path"; then ok=true; break; fi
    done <<< "$allowed"
    $ok && continue

    # Always-allowed set: the things every agent PR may touch regardless of spec.
    case "$path" in
        docs/learnings/*) continue ;;
        AGENTS.md) continue ;;
        .claude/agents/*) $agents_docs_changed && continue ;;
        pyproject.toml) pyproject_is_omit_only "$diff" && continue ;;
    esac

    echo "fail scope $path"
    exit 0
done <<< "$changed"

# --------------------------------------------------------------- step 4 ---

added=$(printf '%s\n' "$diff" | added_lines)
while IFS= read -r name; do
    [ -n "$name" ] || continue
    if printf '%s\n' "$added" | grep -qE "^\+[[:space:]]*(async[[:space:]]+)?def[[:space:]]+${name}[[:space:]]*\("; then
        continue
    fi
    # Already in the tree counts: a spec may name a test that exists and must
    # keep existing. LESSON 6 -- the tests are executable, the prose is not.
    if grep -rqE "def[[:space:]]+${name}[[:space:]]*\(" --include='*.py' "$tree_root" 2>/dev/null; then
        continue
    fi
    echo "fail missing-test $name"
    exit 0
done <<< "$(printf '%s\n' "$spec" | sed -nE 's/^test //p' | sort -u)"

# --------------------------------------------------------------- step 5 ---

# LESSON 6 as a check. Fenced blocks are excluded: a shell snippet or a quoted
# diff in a PR body is illustration, not a claim about this diff. An inline
# backticked path is a claim.
claimed=$(printf '%s\n' "$body" | awk '
    function backticks(line,   rest, tok) {
        rest = line
        while (match(rest, /`[^`]+`/)) {
            tok = substr(rest, RSTART + 1, RLENGTH - 2)
            rest = substr(rest, RSTART + RLENGTH)
            print tok
        }
    }
    /^[ \t]*(```|~~~)/ { fence = !fence; next }
    !fence { backticks($0) }
' | sort -u)

while IFS= read -r token; do
    [ -n "$token" ] || continue
    is_path "$token" || continue
    found=false
    while IFS= read -r path; do
        [ -n "$path" ] || continue
        if covers "$token" "$path" || [ "$token" = "$path" ]; then found=true; break; fi
    done <<< "$changed"
    $found && continue
    echo "fail claimed-not-changed $token"
    exit 0
done <<< "$claimed"

echo "pass"

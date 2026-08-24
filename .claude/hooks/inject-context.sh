#!/usr/bin/env bash
# SessionStart — inject the operating constitution into context.
#
# AGENTS.md says "read it in full before taking any action," which is a request,
# not a guarantee. This makes the load-bearing half of it unconditional.
#
# FAIL OPEN, deliberately. This is an observe/inject hook, not a guardrail: a
# session that starts without the preamble is degraded, not unsafe. SessionStart
# also cannot block -- exit 2 is ignored there -- so failing closed would be
# theater. Guardrails in this repo live on PreToolUse and Stop.

set -uo pipefail
HOOK_NAME="inject-context"

# Bootstrap guard. Exit 1 here is CORRECT for this hook -- it is fail-open by
# design (see header) -- but make that a decision rather than an accident of
# how `set -u` happens to behave. A fail-CLOSED hook needs exit 2 here instead;
# see gate-done.sh.
if [ -z "${CLAUDE_PROJECT_DIR:-}" ]; then
  echo "[$HOOK_NAME] warning: CLAUDE_PROJECT_DIR unset; skipping context injection" >&2
  exit 1
fi
source "$CLAUDE_PROJECT_DIR/.claude/hooks/lib/preamble.sh"

command -v jq >/dev/null 2>&1 || warn_open "jq not on PATH; skipping context injection"

AGENTS="$CLAUDE_PROJECT_DIR/AGENTS.md"
[ -r "$AGENTS" ] || warn_open "AGENTS.md not readable at $AGENTS"

# AGENTS.md is ~10.3k chars and the hook-output cap is 10k, so injecting it whole
# would be written to a file and replaced with a preview -- worse than useless as
# context. Select by heading name rather than byte offset so this survives edits
# to the document; anything not selected is still one Read away.
WANTED='Repository Identity|Module Boundaries|Critical Agent Warnings|Harness Lessons|Definition of Done'

excerpt=$(
  awk -v want="$WANTED" '
    /^## / {
      title = substr($0, 4)
      sub(/[ \t]+$/, "", title)
      keep = 0
      n = split(want, w, "|")
      for (i = 1; i <= n; i++) if (index(title, w[i]) == 1) keep = 1
    }
    keep { print }
  ' "$AGENTS"
)

[ -n "$excerpt" ] || warn_open "no matching sections in AGENTS.md (headings renamed?)"

context=$(
  {
    echo "# AGENTS.md — operating constitution (excerpt, injected at session start)"
    echo
    echo "$excerpt"
    echo
    echo "---"
    echo "Excerpt only. Read \`AGENTS.md\` in full before structural work."
    echo "Boundaries are enforced by \`scripts/validate_harness.py\`; the Stop hook runs it."
  } | clamp
)

jq -nc --arg c "$context" \
  '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
exit 0

#!/usr/bin/env bash
# Shared hook preamble for agent-harness-public. Source, don't exec.
#
# CONTRACT: helpers that can fail RETURN non-zero; they never exit.
#
# Exiting from inside a command substitution -- x=$(field ...) -- only kills the
# subshell. The hook then sails on to its own `exit 0` and ALLOWS the call, after
# printing "BLOCKED" to stderr. Every fallible call site must end in `|| die_closed`.
#
# Exit codes (Claude Code): 0 = proceed, 2 = block, anything else = non-blocking
# error. `exit 1` blocks nothing -- it is a logger, not a guard.

set -uo pipefail

HOOK_NAME="${HOOK_NAME:-$(basename "${BASH_SOURCE[1]:-hook}")}"

# Terminal. Top-level only -- never from inside $( ).
die_closed() {
  echo "[$HOOK_NAME] BLOCKED — guard could not evaluate: $*" >&2
  exit 2
}

# Advisory hooks only. Deliberate choice, never a fallback.
warn_open() {
  echo "[$HOOK_NAME] warning: $*" >&2
  exit 1
}

# Top-level only, so exiting here is safe.
require() {
  local missing=()
  local dep
  for dep in "$@"; do
    command -v "$dep" >/dev/null 2>&1 || missing+=("$dep")
  done
  [ ${#missing[@]} -eq 0 ] || die_closed "missing dependencies: ${missing[*]}"
}

# Returns 1 on empty payload.  Call: PAYLOAD=$(read_payload) || die_closed "..."
read_payload() {
  local p
  p=$(cat)
  [ -n "$p" ] || return 1
  printf '%s' "$p"
}

# Missing field -> non-zero. A field that is legitimately `false` -> "false", 0.
#
# Do NOT use `jq -e` here. -e sets exit 1 when the last output is false OR null,
# AND STILL PRINTS IT. So `jq -er` on a real `false` printed "false" and exited
# 1: field() treated a healthy payload as schema drift and die_closed blocked,
# while field_opt() appended its default and returned "false\nfalse". Branch on
# the output instead of the status.
#
# Call: file=$(field '.a.b') || die_closed "..."
field() {
  local out
  out=$(jq -r "$1" <<<"$PAYLOAD" 2>/dev/null) || return 1
  [ "$out" = "null" ] && return 1
  printf '%s' "$out"
}

# Same, but the field is legitimately optional rather than schema drift.
# Call: flag=$(field_opt '.stop_hook_active' 'false')
field_opt() {
  local out
  out=$(jq -r "$1" <<<"$PAYLOAD" 2>/dev/null) || { printf '%s' "${2-}"; return 0; }
  case "$out" in
    ""|null) printf '%s' "${2-}" ;;
    *)       printf '%s' "$out" ;;
  esac
}

# Claude Code truncates hook output past 10k chars to a file + preview, which is
# useless as model feedback. Keep every emitted string under the cap.
HOOK_OUTPUT_CAP=9000
clamp() {
  local s
  s=$(cat)
  if [ "${#s}" -le "$HOOK_OUTPUT_CAP" ]; then
    printf '%s' "$s"
  else
    printf '%s\n\n[truncated at %s chars — see full output by running the command yourself]' \
      "${s:0:$HOOK_OUTPUT_CAP}" "$HOOK_OUTPUT_CAP"
  fi
}

#!/bin/bash
# PreToolUse, matcher: Bash
# Blocks `git push --force` (and variants: -f, +refspec) on main/master/release/* branches.
# Contract: JSON input on stdin, exit 2 = block (stderr is shown to Claude as the reason).
set -euo pipefail

input=$(cat)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')

if [[ -z "$command" ]]; then
  exit 0
fi

# We only care about `git push`
if ! printf '%s' "$command" | grep -qE '(^|[;&|]\s*)git\s+push\b'; then
  exit 0
fi

is_force=false
if printf '%s' "$command" | grep -qE -- '--force(-with-lease)?\b|\s-f\b'; then
  is_force=true
fi
# `git push origin +main` is also a force push (refspec with a leading plus)
if printf '%s' "$command" | grep -qE '\+[A-Za-z0-9._/-]*(main|master|release/)'; then
  is_force=true
fi

targets_protected=false
if printf '%s' "$command" | grep -qE '\b(main|master)\b|release/'; then
  targets_protected=true
fi

if $is_force && $targets_protected; then
  echo "Blocked: this force push looks like it targets a protected branch (main/master/release/*)." >&2
  echo "Command: $command" >&2
  echo "If this is really intentional, run it by hand in a terminal, outside Claude Code." >&2
  exit 2
fi

exit 0

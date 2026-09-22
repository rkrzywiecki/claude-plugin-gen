#!/bin/bash
# PostToolUse, matcher: Write|Edit
# After editing docker-compose*.yml, runs `docker compose config -q` to catch
# syntax/reference errors before anyone actually brings the stack up.
# If docker isn't available in this environment (e.g. a sandbox without
# docker-in-docker), silently do nothing - that's not a reason to block Claude's work.
set -euo pipefail

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')

if [[ -z "$file_path" ]]; then
  exit 0
fi

case "$(basename "$file_path")" in
  docker-compose*.yml|docker-compose*.yaml|compose.yml|compose.yaml) ;;
  *) exit 0 ;;
esac

if [[ ! -f "$file_path" ]]; then
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  exit 0
fi

if ! output=$(docker compose -f "$file_path" config -q 2>&1); then
  echo "Warning: docker compose config fails for $file_path:" >&2
  echo "$output" >&2
  exit 2
fi

exit 0

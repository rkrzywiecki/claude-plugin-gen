#!/bin/bash
# PostToolUse, matcher: Write|Edit
# After editing a .gitlab-ci.yml file (anywhere in the repo), checks that it's
# still valid YAML. The file has already been written (PostToolUse), so this
# doesn't block the action - but exit 2 feeds stderr back to Claude as context,
# so it can fix the error right away instead of waiting for a red pipeline.
set -euo pipefail

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')

if [[ -z "$file_path" ]]; then
  exit 0
fi

case "$(basename "$file_path")" in
  .gitlab-ci.yml|*.gitlab-ci.yml) ;;
  *)
    # also check typical includes under .gitlab/ci/*.yml
    case "$file_path" in
      *.gitlab/ci/*.yml|*.gitlab-ci/*.yml) ;;
      *) exit 0 ;;
    esac
    ;;
esac

if [[ ! -f "$file_path" ]]; then
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  exit 0  # no python3 in this environment - don't block, just skip the check
fi

error=$(python3 - "$file_path" <<'PY' 2>&1 || true
import sys
try:
    import yaml
except ImportError:
    sys.exit(0)
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        yaml.safe_load(f)
except yaml.YAMLError as e:
    print(str(e))
    sys.exit(1)
PY
)

if [[ -n "$error" ]]; then
  echo "Warning: $file_path has a YAML syntax error after this edit:" >&2
  echo "$error" >&2
  exit 2
fi

exit 0

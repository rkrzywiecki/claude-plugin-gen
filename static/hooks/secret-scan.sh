#!/bin/bash
# PreToolUse, matcher: Write|Edit
# A simple scan of content Claude is about to write, looking for secret-like patterns.
# This is a safety net, not a substitute for a real secret scanner (e.g. gitleaks) in CI.
set -euo pipefail

input=$(cat)

# Write has .tool_input.content, Edit has .tool_input.new_string
content=$(printf '%s' "$input" | jq -r '.tool_input.content // .tool_input.new_string // empty')
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')

if [[ -z "$content" ]]; then
  exit 0
fi

patterns=(
  'AKIA[0-9A-Z]{16}'                                   # AWS access key id
  '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'    # private key
  '(api[_-]?key|secret|token)["'"'"']?\s*[:=]\s*["'"'"'][A-Za-z0-9/+_-]{20,}["'"'"']'
  'sk_live_[A-Za-z0-9]{16,}'                            # payment gateway key (live/production)
)

for pattern in "${patterns[@]}"; do
  if printf '%s' "$content" | grep -qEi -- "$pattern"; then
    echo "Blocked write to ${file_path:-<file>}: the content looks like it contains a secret (pattern: $pattern)." >&2
    echo "Move the value to an environment variable / vault and use a placeholder, e.g. \${DB_PASSWORD}." >&2
    echo "If this is a false positive (e.g. an example/fake key in test code), ask for the write with different content, or do it by hand." >&2
    exit 2
  fi
done

exit 0

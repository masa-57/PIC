#!/bin/bash
# PostToolUse hook: warn when TODO/FIXME is added to a .py file without an issue reference
# Valid format: TODO(#42) or FIXME(#42) — any line with TODO/FIXME must contain #<number>

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only check Python files
if [[ "$FILE" != *.py ]]; then
  exit 0
fi

# For Edit tool: check new_string for new TODOs
# For Write tool: check content
NEW_TEXT=$(echo "$INPUT" | jq -r '.tool_input.new_string // .tool_input.content // empty')

if [ -z "$NEW_TEXT" ]; then
  exit 0
fi

# Find TODO/FIXME lines without issue references (#<number>)
# Matches: TODO, FIXME (case insensitive)
# Valid refs: #123, (#123), (# 123)
VIOLATIONS=$(echo "$NEW_TEXT" | grep -inE '\b(TODO|FIXME)\b' | grep -vE '#[0-9]+')

if [ -n "$VIOLATIONS" ]; then
  echo "WARNING: TODO/FIXME without issue reference detected in $FILE:"
  echo "$VIOLATIONS" | head -5
  echo ""
  echo "Add an issue reference like TODO(#42) or create an issue with /create-issue"
fi

exit 0

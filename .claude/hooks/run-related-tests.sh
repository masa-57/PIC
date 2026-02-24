#!/bin/bash
# PostToolUse hook: run related unit tests when a Python source file is edited

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only run for Python files under src/nic/
if [ -z "$FILE" ]; then
  exit 0
fi

# Normalize to project-relative path (Edit/Write can pass relative or absolute paths)
if [[ "$FILE" == "$CLAUDE_PROJECT_DIR/"* ]]; then
  FILE="${FILE#"$CLAUDE_PROJECT_DIR"/}"
fi

if [[ ! "$FILE" == src/nic/*.py ]]; then
  exit 0
fi

# Skip __init__.py and conftest.py
BASENAME=$(basename "$FILE" .py)
if [[ "$BASENAME" == "__init__" || "$BASENAME" == "conftest" ]]; then
  exit 0
fi

# Search for test files matching the module name
TESTS_DIR="$CLAUDE_PROJECT_DIR/tests/unit"
MATCHES=$(find "$TESTS_DIR" -name "test_*${BASENAME}*.py" -type f 2>/dev/null)

if [ -z "$MATCHES" ]; then
  exit 0
fi

# Run matched tests (quick, fail-fast)
cd "$CLAUDE_PROJECT_DIR"
echo "Running related tests for $BASENAME..."
uv run pytest $MATCHES -x --tb=short -q 2>&1 | tail -15

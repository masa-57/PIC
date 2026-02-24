#!/bin/bash
# Block commands that should only run via CI/CD or that violate branch conventions

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Block local CDK deployments
if echo "$COMMAND" | grep -qE '\bcdk deploy\b'; then
  echo "BLOCKED: CDK deployments must go through CI/CD. Push infra/ changes to GitHub." >&2
  exit 2
fi

# Block local Docker image builds and pushes
if echo "$COMMAND" | grep -qE '\bdocker (build|push)\b'; then
  echo "BLOCKED: Docker builds/pushes must go through CI/CD. Push src/ changes to GitHub." >&2
  exit 2
fi

# Block direct commits to main (enforce feature branches)
if echo "$COMMAND" | grep -qE 'git\s+commit'; then
  BRANCH=$(git -C "$CLAUDE_PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null)
  if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
    echo "BLOCKED: Direct commits to $BRANCH are not allowed. Create a feature branch first." >&2
    exit 2
  fi
fi

# Block force pushes and pushes directly to main
if echo "$COMMAND" | grep -qE 'git\s+push.*(--force|main|master|origin\s+main|origin\s+master)'; then
  echo "BLOCKED: Direct pushes to main/master are not allowed. Use a pull request." >&2
  exit 2
fi

exit 0

#!/usr/bin/env bash
# Block DDL schema changes via Postgres MCP — must use Alembic migrations instead
QUERY=$(echo "$CLAUDE_TOOL_INPUT" | jq -r '.query // .sql // empty' | tr '[:upper:]' '[:lower:]')
if echo "$QUERY" | grep -qE '\b(alter|drop|create|truncate)\b'; then
  echo 'BLOCKED: Schema changes must go through Alembic migrations, not raw SQL. Use /db-migrate skill.' >&2
  exit 2
fi

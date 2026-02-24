# Agent Rules Source of Truth

Last updated: 2026-02-16

## Purpose

Prevent drift between project rules and agent/skill instructions.

## Canonical Source

`AGENTS.md` is the primary source of truth for:

- architecture conventions
- database gotchas
- CI/CD and deployment constraints
- quality gates
- task-tracking rules

`CLAUDE.md` is a concise secondary reference. If `AGENTS.md` and `CLAUDE.md` conflict, follow `AGENTS.md`.

## Enforcement Rules

1. Agents and skills in `.claude/agents/` and `.claude/skills/` must reference canonical rules instead of duplicating fragile details.
2. When duplication is necessary, copy exact wording from `AGENTS.md`.
3. Any PR touching enum behavior, auth, or migration safety must run a docs consistency check:
   - `rg -n "UPPERCASE|has_embedding|advisory lock|migrations" AGENTS.md CLAUDE.md .claude/agents .claude/skills`
4. Drift fixes should be included in the same PR that introduces rule changes.

## High-Risk Rules That Must Stay Consistent

- DB enum literals in raw SQL are UPPERCASE.
- `has_embedding` is integer `0/1`, not boolean.
- Schema changes must go through Alembic migrations.
- No direct deploy shortcuts bypassing CI/CD.

## Review Checklist

Before merging automation/docs changes:

1. Confirm `AGENTS.md` and `CLAUDE.md` are aligned.
2. Confirm agent/skill docs do not contradict canonical rules.
3. Confirm hooks and MCP profiles enforce least privilege by default.

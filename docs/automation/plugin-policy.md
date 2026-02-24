# Claude Plugin Policy (Curated Set)

Last updated: 2026-02-16

## Goal

Reduce plugin noise and keep only tools with measurable value for NIC delivery quality.

## Curated Plugins

Keep these as active defaults:

1. `audit-project`
2. `pr-review`
3. `test-writer-fixer`
4. `ship`

## Usage Rules

1. Prefer native repo hooks, skills, and CI checks first.
2. Use plugins only when they provide unique capability not covered locally.
3. New plugin adoption requires:
   - documented use case
   - owner
   - rollback/removal plan
   - quality or speed metric

## Review Cadence

- Monthly plugin audit:
  - remove unused plugins
  - verify compatibility with current workflow
  - update this policy document

## Security Notes

- Avoid plugins that require broad, unnecessary token scopes.
- Never bypass branch protections or CI gates via plugin shortcuts.

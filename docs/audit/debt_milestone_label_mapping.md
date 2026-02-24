# Debt Milestone and Label Mapping (148-Issue Plan)

Last updated: 2026-02-16

## Goal

Map all 148 audit findings to an executable milestone and label scheme, including findings that do not yet have dedicated GitHub issues.

## Milestones

1. `Debt-P0-Critical`
   - Scope: `C1`-`C9` (9 critical findings)
   - Target: immediate stabilization
2. `Debt-P1-QuickWins`
   - Scope: high quick wins (`H-DO1`, `H-P2`, `H-API3`, `H-API1-2`, `H-API5`, `H-D3`, `H-P5`, `H-CQ2`)
   - Target: fastest risk/efficiency improvements
3. `Debt-P1-HighBundles`
   - Scope: remaining high findings (`H-*`)
   - Target: production resilience and scale
4. `Debt-P2-Medium`
   - Scope: all `M-*` findings (65)
   - Target: maintainability + reliability hardening
5. `Debt-P3-Low`
   - Scope: all `L-*` findings (33 normalized to severity matrix)
   - Target: cleanup and long-tail quality
6. `Debt-RFC`
   - Scope: strategic decisions (e.g., `#23`)
   - Target: platform direction decisions

## Label Taxonomy

## Priority labels

- `priority:critical`
- `priority:high`
- `priority:medium`
- `priority:low`

## Area labels

- `area:performance`
- `area:security`
- `area:api-design`
- `area:database`
- `area:devops`
- `area:testing`
- `area:architecture`
- `area:code-quality`

## Workflow labels

- `quick-win`
- `bundle-parent`
- `bundle-child`
- `needs-split`
- `verified-fixed`
- `deferred`

## Mapping Rules

1. Every register row in `docs/audit/debt_register_148.csv` must have:
   - exactly one `priority:*` label
   - at least one `area:*` label
2. Bundle issue links:
   - High domain bundles map to `#53`-`#59`
   - Critical test bundle maps to `#52`
3. Findings without dedicated GitHub issues:
   - keep `github_issue` empty in register
   - create child issues when entering active sprint

## Backlog Split Procedure

1. For each milestone planning cycle:
   - select next 10-20 rows from register by priority + dependency
   - create missing GitHub child issues
   - label as `bundle-child` if parent bundle exists
2. Child issue title format:
   - `debt(<audit_id>): <short finding title>`
3. Child issue body must include:
   - source row (`audit_id`)
   - acceptance criteria
   - test requirements

## Integrity Checks

Run before each sprint:

1. Register row count is 148.
2. Severity counts match matrix:
   - critical: 9
   - high: 41
   - medium: 65
   - low: 33
3. Every row has milestone + labels populated.
4. Every closed GitHub issue has corresponding register status update.

## Notes on Source Inconsistencies

The source audit document has counting inconsistencies in a few sections:

1. High test-gap bundle text references 11 gaps while severity matrix allocates 41 high issues total.
2. Low architecture subsection lists `L-A1`-`L-A8` while severity matrix allocates 33 low issues.

To preserve the official 148-item severity matrix, normalization in the register uses:

1. High testing bundle normalized to `H-T1`-`H-T9`.
2. Low architecture normalized to `L-A1`-`L-A5`.

These normalization assumptions are documented in the `notes` column of the register.

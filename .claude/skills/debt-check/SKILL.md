---
name: debt-check
description: Quick incremental scan for top technical debt patterns. Run weekly or before PRs to catch regressions.
disable-model-invocation: true
---

# Debt Check (Incremental Scan)

Fast automated scan for the most common and impactful debt patterns in the NIC codebase. Complements the full debt register (`docs/audit/debt_register_148.csv`).

## When to Use

- Before submitting a PR (catch regressions)
- Weekly maintenance scan
- After large refactors

## Procedure

Run all checks below and produce a summary report.

### 1. God Functions (ref: H-A2, H-A3, M-CQ4-CQ6, M-CQ8)

```bash
uv run ruff check --select C901 --config 'lint.mccabe.max-complexity = 10' src/ scripts/
```

Flag any function exceeding complexity 10.

### 2. Broad Exceptions (ref: H-CQ1, M-CQ7)

```bash
grep -rnE 'except\s+Exception(\s+as\s+\w+)?\s*:' src/nic/ --include='*.py' | grep -v '# noqa' | wc -l
```

Count total occurrences. Flag if count increases from baseline.

### 3. Duplicate Constants (ref: M-CQ1, M-CQ2)

```bash
echo "=== IMAGE_EXTENSIONS ==="
grep -rn '_IMAGE_EXTENSIONS' src/nic/ --include='*.py' | cut -d: -f1 | sort -u
echo "=== Advisory Lock ID ==="
grep -rn '0x4E494301' src/nic/ --include='*.py' | cut -d: -f1 | sort -u
echo "=== S3 Prefixes ==="
grep -rn '"images/"\|"processed/"\|"rejected/"\|"thumbnails/"' src/nic/ --include='*.py' | cut -d: -f1 | sort | uniq -c | sort -rn | head -10
```

Each constant should appear in exactly 1 shared location. Flag if found in multiple files.

### 4. Serial I/O Patterns (ref: H-P6, H-P7)

```bash
grep -rnE 'for\s+\w+\s+in\s+' src/nic/ --include='*.py' -A3 | grep -E 'await\s+(download|upload|generate_presigned|move)'
```

Flag loops with serial `await` calls that could be parallelized.

### 5. Missing Location Headers (ref: H-API1/2)

```bash
grep -rnE 'status_code\s*=\s*(201|202)' src/nic/api/ --include='*.py'
```

Each 201/202 response should have a corresponding `Location` header. Manually verify.

### 6. N+1 Candidates (ref: C1)

```bash
grep -rnE 'selectinload.*selectinload' src/nic/ --include='*.py'
```

Flag nested eager loads that could cause N+1 on large datasets.

### 7. Exposed Endpoints (ref: H-S2)

```bash
grep -rnE '@router\.(get|post|put|patch|delete)' src/nic/api/*.py -A5 | grep -B1 'async def' | grep -v 'require_api_key' | grep -v 'health'
```

Flag API endpoints missing auth dependency.

## Report Format

```
## Debt Check Report (YYYY-MM-DD)

| Category | Count | Trend | Action |
|----------|-------|-------|--------|
| God functions (>10 complexity) | N | up/down/same | fix/ok |
| Broad exceptions | N | up/down/same | fix/ok |
| Duplicate constants | N files | up/down/same | fix/ok |
| Serial I/O loops | N | up/down/same | fix/ok |
| Missing Location headers | N | up/down/same | fix/ok |
| N+1 candidates | N | up/down/same | fix/ok |
| Unprotected endpoints | N | up/down/same | fix/ok |

### New Issues
[list regressions]

### Recommendations
[top 3 items to fix next]
```

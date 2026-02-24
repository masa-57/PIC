---
name: perf-review
description: Run a NIC-specific performance review checklist against changed or specified files. Checks for N+1 queries, serial I/O, download-before-check, full table loads, and memory patterns.
---

# Performance Review

Review code for NIC-specific performance anti-patterns. Use before PRs touching workers, services, or API endpoints.

## Arguments

Optional: file paths or PR diff to review. If none provided, review all files changed vs main.

## Checklist

### 1. N+1 Query Detection (ref: C1)

Search for nested `selectinload`/`joinedload` chains that eagerly load large relationship trees:

```bash
grep -rn 'selectinload\|joinedload\|subqueryload' src/nic/api/*.py src/nic/worker/*.py
```

- Flag any endpoint that loads ALL images for ALL groups (especially cluster hierarchy).
- Verify `limit` is applied BEFORE relationship loading, not after.
- Check that `load_only(...)` is used when only a few columns are needed.

### 2. Download-Before-Check (ref: C2)

Flag code that downloads files from S3/R2 before checking DB for duplicates:

```bash
grep -rn -B5 'download_file\|get_object\|download_from_s3' src/nic/worker/*.py
```

Correct pattern: query `content_hash` / `s3_key` existence first, then download only new items.

### 3. Serial I/O in Loops (ref: H-P6, H-P7)

Flag sequential `await` calls inside loops that could use `asyncio.gather` or `TaskGroup`:

```bash
grep -rn -A3 'for.*in.*:' src/nic/ --include='*.py' | grep -E 'await\s+(download|upload|generate_presigned|move)'
```

Common hotspots: presigned URL generation, file downloads, S3 move operations.

### 4. Full Table Loads (ref: H-D3, C1)

Flag queries missing column projection on large tables:

```bash
grep -rn 'select(Image)\|select(L1Group)\|select(L2Cluster)' src/nic/ --include='*.py'
```

- Ensure `load_only(...)` is used when only IDs, counts, or metadata are needed.
- Flag missing `LIMIT` on queries that could return unbounded results.

### 5. Memory Patterns (ref: H-P5, H-P4)

```bash
grep -rn 'float64\|np\.array' src/nic/ --include='*.py'
grep -rn '\.all()' src/nic/ --include='*.py'
```

- Flag `np.float64` arrays for embeddings (should be `float32` — halves memory).
- Flag missing `torch.no_grad()` or `gc.collect()` after GPU batch operations.
- Flag `.all()` calls on queries that could return >1000 rows.

### 6. Connection Pool Sizing (ref: H-P3, M-D4)

```bash
grep -rn 'pool_size\|max_overflow' src/nic/ --include='*.py'
```

Check pool size vs concurrent access patterns. Each Modal worker creates its own pool.

### 7. Missing Indexes (ref: H-P2, M-P2)

Cross-reference `WHERE`/`ORDER BY` columns in hot-path queries against Alembic migrations:

```bash
grep -rn 'order_by\|where(' src/nic/api/*.py src/nic/worker/*.py --include='*.py' | grep -v test
```

Flag combinations without composite indexes (e.g., `status + created_at`).

## Output Format

For each finding:
1. **Severity**: Critical / High / Medium
2. **Pattern**: Which anti-pattern (N+1, serial I/O, etc.)
3. **File:Line**: Location
4. **Impact**: Estimated performance effect
5. **Fix**: Concrete code change
6. **Debt ID**: Matching debt register entry if applicable

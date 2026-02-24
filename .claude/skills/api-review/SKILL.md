---
name: api-review
description: Review NIC API endpoints for REST design compliance, response headers, pagination, error format, and request validation.
---

# API Design Review

Review API endpoints for REST best practices and NIC-specific conventions. Use before PRs touching `src/nic/api/` files.

## Arguments

Optional: file paths or endpoint names to review. If none provided, review all API files.

## Checklist

### 1. Response Headers (ref: H-API1/2, H-API3, M-API1)

```bash
grep -rn 'status_code=201\|status_code=202' src/nic/api/*.py
```

- **201 Created**: MUST include `Location` header pointing to the created resource.
- **202 Accepted**: MUST include `Location` header pointing to the job status URL.
- **429 Too Many Requests**: MUST include `Retry-After` header.
- GET endpoints for stable data SHOULD include `Cache-Control` headers.

### 2. HTTP Method Semantics (ref: H-API4)

- GET for safe, idempotent reads (search SHOULD be GET with query params, not POST).
- POST for creating resources or triggering side effects.
- PUT/PATCH for updates.
- DELETE for removal.

```bash
grep -rn '@router.post' src/nic/api/*.py | grep -i 'search\|find\|query\|list'
```

Flag any POST endpoint that is semantically a read operation.

### 3. Pagination (ref: M-API3, M-API4, H-API6, M-API13)

```bash
grep -rn 'offset\|limit\|total' src/nic/api/*.py src/nic/models/schemas.py
```

- All list endpoints MUST return pagination metadata (`total`, `offset`, `limit`).
- Cluster hierarchy must paginate L2 clusters and unclustered groups independently.
- Consider cursor-based pagination for endpoints that may have high offsets.

### 4. Error Format (ref: M-API7, M-API11)

```bash
grep -rn 'HTTPException\|exception_handler' src/nic/main.py src/nic/api/*.py
```

- All error responses SHOULD use consistent JSON structure: `{"detail": "message"}`.
- Pydantic 422 validation errors should match the custom error format.
- Consider RFC 7807 Problem Details for structured errors.

### 5. Request Validation (ref: H-API7)

- Request body size limits MUST be enforced at API layer.
- UUID parameters MUST be validated before DB queries.
- All inputs validated via Pydantic schemas.

```bash
grep -rn 'Body(\|Path(\|Query(' src/nic/api/*.py | grep -v 'Depends'
```

### 6. Rate Limiting (ref: M-API5)

```bash
grep -rn 'limiter\|rate_limit\|RateLimit' src/nic/ --include='*.py'
```

- Rate-limited endpoints SHOULD include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers.

### 7. Authentication (ref: H-S2)

```bash
grep -rn '@router\.' src/nic/api/*.py -A5 | grep -v 'require_api_key' | grep -v 'health'
```

- All `/api/v1/*` routes MUST use `require_api_key` dependency unless explicitly public.
- Flag any endpoint missing auth that isn't a health check.

## Output Format

For each finding:
1. **Severity**: Critical / High / Medium / Low
2. **Category**: Headers / Methods / Pagination / Errors / Validation / Rate Limiting / Auth
3. **Endpoint**: Method + path
4. **File:Line**: Location
5. **Issue**: What's wrong
6. **Fix**: Concrete change needed
7. **Debt ID**: Matching debt register entry if applicable

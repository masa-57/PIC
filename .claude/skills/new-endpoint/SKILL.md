---
name: new-endpoint
description: Create a new API endpoint following project conventions. Use when adding routes to the FastAPI application.
---

# New Endpoint Checklist

When creating a new endpoint:

1. Add the route in `src/nic/api/` following existing patterns
2. Use async def for all handlers
3. Add proper Pydantic request/response schemas in `src/nic/models/schemas.py`
4. Add the router to `src/nic/api/router.py`
5. Include error handling with appropriate HTTP status codes
6. Add unit tests in `tests/` with the `@pytest.mark.unit` marker
7. Add integration tests if the endpoint touches the database
8. Ensure the endpoint is behind API key auth (all /api/v1/* routes)
9. Run /quality-check before committing

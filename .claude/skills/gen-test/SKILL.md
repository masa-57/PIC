---
name: gen-test
description: Generate unit test stubs for a source module following NIC project conventions. Pass the module path as argument (e.g., /gen-test src/nic/services/clustering.py).
---

# Generate Unit Tests

Generate comprehensive unit test stubs for the given source module, following NIC project conventions exactly.

## Arguments

The user provides a source file path (e.g., `src/nic/services/clustering.py`).

## Procedure

1. **Read the source file** to identify all public functions, classes, and methods (skip `_private` internals unless they're complex enough to warrant testing)

2. **Read an existing test file** from `tests/unit/` for reference — match the style exactly

3. **Generate the test file** at `tests/unit/test_<module_name>.py` following these conventions:

### Conventions (MUST follow)

- **Marker**: Every test class MUST have `@pytest.mark.unit`
- **Imports**: Import from the `nic.*` package path (e.g., `from nic.services.clustering import ...`)
- **Async**: If the source function is `async def`, the test MUST use `@pytest.mark.asyncio` and `async def`
- **Classes**: Group tests into classes by function/feature: `class TestFunctionName:`
- **Naming**: Test methods follow `test_<scenario>` (e.g., `test_empty_input`, `test_returns_error_on_invalid_id`)
- **Mocking**:
  - Mock database sessions with `AsyncMock` for the `AsyncSession` — never hit a real DB
  - Mock R2/S3 calls with `MagicMock` or `patch`
  - Mock Modal dispatches with `patch("nic.services.modal_dispatch.*")`
  - Mock `settings` with `patch("nic.config.settings")`
- **Coverage targets**: Include tests for:
  - Happy path
  - Empty/None inputs
  - Error cases (expected exceptions)
  - Edge cases (boundary values)
- **No hardcoded env values**: Use `settings.*` or mock values, never `.env` content
- **DB columns**: Remember `has_embedding` is integer 0/1, and raw SQL enum values are UPPERCASE strings

### Test structure template

```python
"""Unit tests for <module>."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nic.<package>.<module> import <functions>


@pytest.mark.unit
class TestFunctionName:
    def test_happy_path(self):
        ...

    def test_empty_input(self):
        ...

    def test_error_case(self):
        with pytest.raises(ExpectedException):
            ...
```

4. **If the test file already exists**, read it first and only add missing test cases — do not overwrite existing tests

5. **Run the new tests** to verify they pass:
```bash
uv run pytest tests/unit/test_<module_name>.py -x --tb=short -q
```

6. Report what was generated: number of test classes, test methods, and any tests that need manual completion (marked with `# TODO: complete this test`)

#!/usr/bin/env python3
"""Post-deploy smoke tests for the PIC API.

Runs basic HTTP checks against a deployed PIC instance to verify
core endpoints are responsive.

Usage:
    python scripts/smoke_test.py [BASE_URL]

Arguments:
    BASE_URL  API base URL (default: http://localhost:8000)

Exit codes:
    0 - all tests passed
    1 - one or more tests failed
"""

from __future__ import annotations

import sys

import httpx

# Endpoints to test and their acceptable status codes.
# 401 is acceptable because auth may be enabled in production.
SMOKE_TESTS: list[tuple[str, str, set[int]]] = [
    ("GET", "/health", {200}),
    ("GET", "/api/v1/clusters", {200, 401}),
    ("GET", "/api/v1/products", {200, 401}),
]

DEFAULT_BASE_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 15.0


def run_smoke_tests(base_url: str) -> bool:
    """Execute smoke tests and return True if all pass."""
    all_passed = True

    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        for method, path, expected_codes in SMOKE_TESTS:
            url = f"{base_url.rstrip('/')}{path}"
            try:
                response = client.request(method, url)
                if response.status_code in expected_codes:
                    print(f"  PASS  {method} {path} -> {response.status_code}")
                else:
                    print(
                        f"  FAIL  {method} {path} -> {response.status_code} (expected one of {sorted(expected_codes)})"
                    )
                    all_passed = False
            except httpx.RequestError as exc:
                print(f"  FAIL  {method} {path} -> connection error: {exc}")
                all_passed = False

    return all_passed


def main() -> int:
    """Parse arguments and run smoke tests."""
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL

    print(f"Running smoke tests against {base_url}\n")
    passed = run_smoke_tests(base_url)

    if passed:
        print("\nAll smoke tests passed.")
        return 0

    print("\nSome smoke tests failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

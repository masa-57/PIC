#!/usr/bin/env python3
"""Test Alembic migration roundtrip: downgrade -1 then upgrade head.

Verifies that the most recent migration is reversible by running
``alembic downgrade -1`` followed by ``alembic upgrade head``.

Exit codes:
    0 - roundtrip succeeded
    1 - roundtrip failed
"""

from __future__ import annotations

import subprocess
import sys


def run_alembic(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run an Alembic command and return the result."""
    full_cmd = ["uv", "run", "alembic", *command]
    return subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        check=False,
    )


def get_current_revision() -> str | None:
    """Return the current Alembic revision or None if at base."""
    result = run_alembic(["current"])
    if result.returncode != 0:
        return None
    # Alembic current outputs lines like "abc123 (head)"
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line:
            return line.split()[0]
    return None


def main() -> int:
    """Execute the downgrade/upgrade roundtrip check."""
    print("Checking current Alembic revision...")
    before = get_current_revision()
    if not before:
        print("ERROR: Could not determine current Alembic revision.")
        print("Make sure NIC_DATABASE_URL is set and the database is reachable.")
        return 1
    print(f"  Current revision: {before}")

    # Step 1: downgrade -1
    print("\nRunning alembic downgrade -1 ...")
    result = run_alembic(["downgrade", "-1"])
    if result.returncode != 0:
        print(f"ERROR: downgrade failed (exit code {result.returncode})")
        print(f"  stdout: {result.stdout}")
        print(f"  stderr: {result.stderr}")
        return 1

    after_downgrade = get_current_revision()
    print(f"  Revision after downgrade: {after_downgrade or '(base)'}")

    # Step 2: upgrade head
    print("\nRunning alembic upgrade head ...")
    result = run_alembic(["upgrade", "head"])
    if result.returncode != 0:
        print(f"ERROR: upgrade failed (exit code {result.returncode})")
        print(f"  stdout: {result.stdout}")
        print(f"  stderr: {result.stderr}")
        return 1

    after_upgrade = get_current_revision()
    print(f"  Revision after upgrade: {after_upgrade}")

    # Verify we returned to the original revision
    if after_upgrade != before:
        print(f"\nERROR: Revision mismatch. Expected {before}, got {after_upgrade}")
        return 1

    print("\nRoundtrip check PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

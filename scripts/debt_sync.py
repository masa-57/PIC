#!/usr/bin/env python3
"""Debt register integrity and automation utility.

Supports three workflows:

1. validate: Integrity checks for docs/audit/debt_register_148.csv
2. report: Generate summary artifacts (CSV + Markdown)
3. create-issues: Create missing GitHub issues from selected debt rows
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

EXPECTED_ROW_COUNT = 148
EXPECTED_SEVERITY_COUNTS = {
    "critical": 9,
    "high": 41,
    "medium": 65,
    "low": 33,
}

REQUIRED_COLUMNS = {
    "audit_id",
    "severity",
    "domain",
    "title",
    "source",
    "github_issue",
    "status",
    "milestone",
    "labels",
    "notes",
}

REQUIRED_NON_EMPTY_FIELDS = [
    "audit_id",
    "severity",
    "domain",
    "title",
    "status",
    "milestone",
    "labels",
]

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
STATUS_ALLOWED = {"open", "closed", "deferred"}
PRIORITY_LABEL_RE = re.compile(r"^priority:")
AREA_LABEL_RE = re.compile(r"^area:")
ISSUE_URL_RE = re.compile(r"/issues/(\d+)$")


def _read_rows(register_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not register_path.exists():
        raise FileNotFoundError(f"Debt register not found: {register_path}")

    with register_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("Debt register is missing a CSV header")
        missing_columns = sorted(REQUIRED_COLUMNS - set(reader.fieldnames))
        if missing_columns:
            raise ValueError(f"Debt register is missing required columns: {', '.join(missing_columns)}")
        rows = [dict(row) for row in reader]
        return list(reader.fieldnames), rows


def _write_rows(register_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with register_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _split_labels(label_str: str) -> list[str]:
    return [part.strip() for part in label_str.split(",") if part.strip()]


def _check_issue_sync(
    row_ref: str,
    status: str,
    issue_str: str,
    github_status: dict[int, str] | None,
    warned_missing: set[int],
) -> tuple[list[str], list[str]]:
    """Check GitHub issue sync for a single row, returning (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not issue_str.isdigit():
        errors.append(f"{row_ref}: github_issue must be numeric when present")
    elif github_status is not None:
        issue_num = int(issue_str)
        remote_state = github_status.get(issue_num)
        if remote_state is None:
            if issue_num not in warned_missing:
                warnings.append(f"could not fetch GitHub status for issue #{issue_num}")
                warned_missing.add(issue_num)
        elif status == "open" and remote_state == "closed":
            errors.append(f"{row_ref}: register says open, but GitHub issue #{issue_num} is closed")
        elif status == "closed" and remote_state == "open":
            errors.append(f"{row_ref}: register says closed, but GitHub issue #{issue_num} is open")
    return errors, warnings


def _validate_single_row(
    row: dict[str, str],
    row_ref: str,
    github_status: dict[int, str] | None,
    warned_missing: set[int],
) -> tuple[list[str], list[str]]:
    """Validate a single register row, returning (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    for column in REQUIRED_NON_EMPTY_FIELDS:
        if not (row.get(column) or "").strip():
            errors.append(f"{row_ref}: missing required value '{column}'")

    labels = _split_labels(row.get("labels", ""))
    priority_labels = [label for label in labels if PRIORITY_LABEL_RE.match(label)]
    area_labels = [label for label in labels if AREA_LABEL_RE.match(label)]
    if len(priority_labels) != 1:
        errors.append(f"{row_ref}: expected exactly one priority:* label, found {len(priority_labels)}")
    if not area_labels:
        errors.append(f"{row_ref}: expected at least one area:* label")

    status = (row.get("status") or "").strip().lower()
    if status not in STATUS_ALLOWED:
        errors.append(f"{row_ref}: invalid status '{status}'")

    severity = (row.get("severity") or "").strip().lower()
    if severity not in SEVERITY_ORDER:
        errors.append(f"{row_ref}: invalid severity '{severity}'")

    issue_str = (row.get("github_issue") or "").strip()
    if issue_str:
        issue_errors, issue_warnings = _check_issue_sync(row_ref, status, issue_str, github_status, warned_missing)
        errors.extend(issue_errors)
        warnings.extend(issue_warnings)

    return errors, warnings


def _validate_rows(
    rows: list[dict[str, str]],
    strict: bool,
    github_status: dict[int, str] | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    warned_missing_issue_status: set[int] = set()

    if len(rows) != EXPECTED_ROW_COUNT:
        errors.append(f"row count mismatch: expected {EXPECTED_ROW_COUNT}, found {len(rows)}")

    severity_counts = Counter((row.get("severity") or "").strip().lower() for row in rows)
    for severity, expected in EXPECTED_SEVERITY_COUNTS.items():
        actual = severity_counts.get(severity, 0)
        if actual != expected:
            errors.append(f"severity count mismatch for '{severity}': expected {expected}, found {actual}")

    for index, row in enumerate(rows, start=2):
        row_ref = f"row {index} ({row.get('audit_id', '<missing-audit-id>')})"
        row_errors, row_warnings = _validate_single_row(row, row_ref, github_status, warned_missing_issue_status)
        errors.extend(row_errors)
        warnings.extend(row_warnings)

    if strict:
        non_network_warnings = [
            warning for warning in warnings if not warning.startswith("could not fetch GitHub status")
        ]
        errors.extend([f"strict mode warning: {warning}" for warning in non_network_warnings])

    return errors, warnings


def _github_issue_status(
    owner: str,
    repo: str,
    issue_number: int,
    token: str | None,
) -> str | None:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            payload = json.load(resp)
            state = str(payload.get("state", "")).lower()
            if state in {"open", "closed"}:
                return state
            return None
    except urllib.error.HTTPError:
        return None
    except urllib.error.URLError:
        return None


def _fetch_issue_statuses(
    rows: list[dict[str, str]],
    owner: str,
    repo: str,
) -> dict[int, str]:
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    issue_numbers = sorted(
        {int(row.get("github_issue") or "0") for row in rows if (row.get("github_issue") or "").strip().isdigit()}
    )

    status_map: dict[int, str] = {}
    for number in issue_numbers:
        state = _github_issue_status(owner, repo, number, token)
        if state is not None:
            status_map[number] = state
    return status_map


def _print_validation_result(errors: list[str], warnings: list[str]) -> None:
    if errors:
        print("Validation failed:")
        for item in errors:
            print(f"- {item}")
    else:
        print("Validation passed")

    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"- {item}")


def _generate_report(rows: list[dict[str, str]], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    severity_counts = Counter((row.get("severity") or "").strip().lower() for row in rows)
    domain_counts = Counter((row.get("domain") or "").strip().lower() for row in rows)
    status_counts = Counter((row.get("status") or "").strip().lower() for row in rows)
    missing_issue_counts = Counter(
        (row.get("domain") or "").strip().lower() for row in rows if not (row.get("github_issue") or "").strip()
    )

    csv_path = out_dir / "debt_summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["metric", "dimension", "value"])
        writer.writerow(["rows", "total", len(rows)])
        for severity in ["critical", "high", "medium", "low"]:
            writer.writerow(["severity", severity, severity_counts.get(severity, 0)])
        for domain, value in sorted(domain_counts.items()):
            writer.writerow(["domain", domain, value])
        for status, value in sorted(status_counts.items()):
            writer.writerow(["status", status, value])
        for domain, value in sorted(missing_issue_counts.items()):
            writer.writerow(["missing_issue", domain, value])

    md_path = out_dir / "debt_summary.md"
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Debt Register Summary",
        "",
        f"Generated: {now}",
        "",
        f"- Total rows: {len(rows)}",
        f"- Rows with GitHub issue: {sum(1 for row in rows if (row.get('github_issue') or '').strip())}",
        f"- Rows missing GitHub issue: {sum(1 for row in rows if not (row.get('github_issue') or '').strip())}",
        "",
        "## Severity",
        "",
        "| Severity | Count |",
        "|---|---:|",
    ]
    for severity in ["critical", "high", "medium", "low"]:
        lines.append(f"| {severity} | {severity_counts.get(severity, 0)} |")

    lines.extend(["", "## Domain", "", "| Domain | Count |", "|---|---:|"])
    for domain, value in sorted(domain_counts.items()):
        lines.append(f"| {domain} | {value} |")

    lines.extend(["", "## Status", "", "| Status | Count |", "|---|---:|"])
    for status, value in sorted(status_counts.items()):
        lines.append(f"| {status} | {value} |")

    lines.extend(
        [
            "",
            "## Missing GitHub Issue by Domain",
            "",
            "| Domain | Missing Issue Rows |",
            "|---|---:|",
        ]
    )
    for domain, value in sorted(missing_issue_counts.items()):
        lines.append(f"| {domain} | {value} |")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


def _row_sort_key(row: dict[str, str]) -> tuple[int, str]:
    severity = (row.get("severity") or "").strip().lower()
    return (SEVERITY_ORDER.get(severity, 99), (row.get("audit_id") or "").strip())


def _build_issue_body(row: dict[str, str]) -> str:
    audit_id = (row.get("audit_id") or "").strip()
    source = (row.get("source") or "").strip()
    title = (row.get("title") or "").strip()
    domain = (row.get("domain") or "").strip()
    severity = (row.get("severity") or "").strip()

    return "\n".join(
        [
            "## Source",
            f"- audit_id: `{audit_id}`",
            f"- source: `{source}`",
            "",
            "## Problem",
            title,
            "",
            "## Acceptance Criteria",
            "- [ ] Implement fix in the relevant module(s)",
            "- [ ] Add or update tests that fail before and pass after fix",
            "- [ ] Update `docs/audit/debt_register_148.csv` notes/status linkage",
            "",
            "## Metadata",
            f"- Domain: `{domain}`",
            f"- Severity: `{severity}`",
        ]
    )


def _create_issue_with_gh(
    owner: str,
    repo: str,
    title: str,
    body: str,
    labels: list[str],
) -> tuple[int, str]:
    cmd = [
        "gh",
        "issue",
        "create",
        "--repo",
        f"{owner}/{repo}",
        "--title",
        title,
        "--body",
        body,
    ]
    for label in labels:
        cmd.extend(["--label", label])

    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    url = result.stdout.strip().splitlines()[-1]
    match = ISSUE_URL_RE.search(url)
    if not match:
        raise RuntimeError(f"Could not parse issue URL from gh output: {url}")
    return int(match.group(1)), url


def _handle_create_issues(args: argparse.Namespace) -> int:
    register_path = Path(args.register)
    fieldnames, rows = _read_rows(register_path)

    selected = [
        row
        for row in rows
        if not (row.get("github_issue") or "").strip() and (row.get("status") or "").strip().lower() == "open"
    ]

    if args.severity:
        selected = [row for row in selected if (row.get("severity") or "").strip().lower() == args.severity.lower()]
    if args.domain:
        selected = [row for row in selected if (row.get("domain") or "").strip().lower() == args.domain.lower()]
    if args.milestone:
        selected = [row for row in selected if (row.get("milestone") or "").strip() == args.milestone]

    selected = sorted(selected, key=_row_sort_key)
    if args.limit:
        selected = selected[: args.limit]

    if not selected:
        print("No matching debt rows found for issue creation")
        return 0

    created = 0
    today = dt.date.today().isoformat()

    for row in selected:
        audit_id = (row.get("audit_id") or "").strip()
        issue_title = f"debt({audit_id}): {(row.get('title') or '').strip()}"
        labels = _split_labels(row.get("labels", ""))
        if "bundle-child" not in labels:
            labels.append("bundle-child")
        issue_body = _build_issue_body(row)

        if not args.apply:
            print(f"DRY RUN: would create issue for {audit_id}")
            print(f"  title: {issue_title}")
            print(f"  labels: {', '.join(labels)}")
            continue

        number, url = _create_issue_with_gh(args.owner, args.repo, issue_title, issue_body, labels)
        row["github_issue"] = str(number)
        existing_notes = (row.get("notes") or "").strip()
        marker = f"Issue auto-created {today}: {url}"
        row["notes"] = f"{existing_notes} | {marker}" if existing_notes else marker
        created += 1
        print(f"Created issue #{number} for {audit_id}: {url}")

    if args.apply and created > 0 and not args.no_update_register:
        _write_rows(register_path, fieldnames, rows)
        print(f"Updated register with {created} created issue link(s): {register_path}")

    return 0


def _handle_validate(args: argparse.Namespace) -> int:
    register_path = Path(args.register)
    _, rows = _read_rows(register_path)

    github_status: dict[int, str] | None = None
    if args.check_github:
        github_status = _fetch_issue_statuses(rows, args.owner, args.repo)

    errors, warnings = _validate_rows(rows, strict=args.strict, github_status=github_status)
    _print_validation_result(errors, warnings)
    return 1 if errors else 0


def _handle_report(args: argparse.Namespace) -> int:
    register_path = Path(args.register)
    _, rows = _read_rows(register_path)
    out_dir = Path(args.out_dir)
    csv_path, md_path = _generate_report(rows, out_dir)
    print(f"Wrote report files:\n- {csv_path}\n- {md_path}")
    return 0


def _add_common_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--register", default="docs/audit/debt_register_148.csv")


def main() -> int:
    parser = argparse.ArgumentParser(description="Debt register tooling")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate debt register integrity")
    _add_common_filters(validate_parser)
    validate_parser.add_argument("--strict", action="store_true")
    validate_parser.add_argument("--check-github", action="store_true")
    validate_parser.add_argument("--owner", default="masa-57")
    validate_parser.add_argument("--repo", default="NIC")

    report_parser = subparsers.add_parser("report", help="Generate debt summary report files")
    _add_common_filters(report_parser)
    report_parser.add_argument("--out-dir", default="docs/audit/reports")

    create_parser = subparsers.add_parser(
        "create-issues",
        help="Create missing GitHub issues from debt rows",
    )
    _add_common_filters(create_parser)
    create_parser.add_argument("--owner", default="masa-57")
    create_parser.add_argument("--repo", default="NIC")
    create_parser.add_argument("--severity")
    create_parser.add_argument("--domain")
    create_parser.add_argument("--milestone")
    create_parser.add_argument("--limit", type=int, default=20)
    create_parser.add_argument("--apply", action="store_true")
    create_parser.add_argument("--no-update-register", action="store_true")

    args = parser.parse_args()

    if args.command == "validate":
        return _handle_validate(args)
    if args.command == "report":
        return _handle_report(args)
    if args.command == "create-issues":
        return _handle_create_issues(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

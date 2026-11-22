#!/usr/bin/env python3
"""Inspect an existing SQLite Alembic 0038/0039 schema without migrating it.

Both ReefVision 1.1 and 1.6 used the same revision IDs for different DDL.
A version number by itself is not evidence of which migration ran. This
diagnostic reads named table/column signatures and the QC event CHECK text;
it never resolves a migration or authorizes an automatic upgrade.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

TABLE_COLUMNS = {
    "scientific_records": {"id", "project_id", "variable", "content_sha256"},
    "environmental_cache_entries": {"id", "project_id", "cache_key", "source_url"},
    "computed_metric_definitions": {"id", "project_id", "expression", "definition_sha256"},
    "computed_metric_results": {"id", "project_id", "definition_id", "content_sha256"},
    "review_queue_item_events": {
        "id",
        "project_id",
        "review_queue_item_id",
        "client_request_id",
        "event_type",
        "actor",
    },
}
SCIENTIFIC_38 = ("scientific_records", "environmental_cache_entries")
SCIENTIFIC_39 = ("computed_metric_definitions", "computed_metric_results")
REVIEW_TABLE = "review_queue_item_events"


def inspect_database(path: Path) -> dict[str, object]:
    """Read the schema only; never write, repair, or import Alembic migrations."""
    database = path.resolve(strict=True)
    if not database.is_file():
        raise ValueError("Database path is not a regular file")
    with database.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise ValueError("Not a SQLite database")

    # mode=ro prevents database creation or writes; query_only is an extra
    # guard. Avoid immutable=1 because it can ignore a live WAL journal.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        version_rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        tables = {
            name: ddl or ""
            for name, ddl in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table'"
            )
        }
        signatures: dict[str, bool] = {}
        incomplete: list[str] = []
        for table, required in TABLE_COLUMNS.items():
            if table not in tables:
                signatures[table] = False
                continue
            # Table names are fixed constants above, not user-supplied SQL.
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            signatures[table] = required <= columns
            if not signatures[table]:
                incomplete.append(table)

    versions = [row[0] for row in version_rows]
    groups = {
        "scientific_0038": all(signatures[t] for t in SCIENTIFIC_38),
        "scientific_0039": all(signatures[t] for t in SCIENTIFIC_39),
        "review_0038": signatures[REVIEW_TABLE],
    }
    # Match the actual event_type CHECK, not coincidental words elsewhere in
    # CREATE TABLE SQL (for example, a comment or an unrelated constraint).
    match = re.search(
        r"""CHECK\s*\(\s*"?event_type"?\s+IN\s*\(([^)]*)\)\s*\)""",
        tables.get(REVIEW_TABLE, ""),
        flags=re.IGNORECASE,
    )
    allowed: set[str] = set()
    if match:
        tokens = [token.strip() for token in match.group(1).split(",")]
        if all(len(token) >= 2 and token[0] == token[-1] == "'" for token in tokens):
            allowed = {token[1:-1] for token in tokens}
    coordination = {"comment", "assign", "unassign"}
    triage = {"triage_start", "triage_skip", "triage_return"}
    if allowed == coordination | triage:
        review_check = "triage"
    elif allowed == coordination:
        review_check = "coordination"
    else:
        review_check = "unknown"
    issues = []
    if incomplete:
        issues.append("Incomplete expected table signatures: " + ", ".join(incomplete))
    if len(versions) != 1 or versions[0] not in ("0038", "0039"):
        issues.append("Alembic revision is not exactly one of 0038 or 0039")
    if any(signatures[t] for t in SCIENTIFIC_39) and not groups["scientific_0039"]:
        issues.append("Partial scientific 0039 schema")
    if any(signatures[t] for t in SCIENTIFIC_38) and not groups["scientific_0038"]:
        issues.append("Partial scientific 0038 schema")
    if groups["review_0038"] and review_check == "unknown":
        issues.append("QC event CHECK constraint cannot be identified")
    if REVIEW_TABLE in tables and not groups["review_0038"]:
        issues.append("Incomplete QC review event schema")

    classification = "ambiguous"
    if not issues and len(versions) == 1:
        revision = versions[0]
        science = groups["scientific_0038"]
        metrics = groups["scientific_0039"]
        review = groups["review_0038"]
        if science and not review and (
            (revision == "0038" and not metrics)
            or (revision == "0039" and metrics)
        ):
            classification = f"1.1-scientific-{revision}"
        elif review and not science and not metrics and (
            (revision == "0038" and review_check == "coordination")
            or (revision == "0039" and review_check == "triage")
        ):
            classification = f"1.6-qc-{revision}"
    if classification == "ambiguous":
        issues.append("Cannot safely attribute the colliding revision to one applied lineage")
    return {
        "schema_version": "reefvision-sqlite-lineage-forensics-0001",
        "alembic_versions": versions,
        "table_signatures": signatures,
        "review_event_check": review_check if groups["review_0038"] else None,
        "classification": classification,
        "issues": issues,
        "manual_migration_reconciliation_required": True,
        "automatic_migration_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Existing local SQLite database")
    args = parser.parse_args()
    try:
        report = inspect_database(args.database)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report["classification"] == "ambiguous" else 0


if __name__ == "__main__":
    sys.exit(main())

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
from collections import Counter
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
        "review_queue_id",
        "review_queue_item_id",
        "client_request_id",
        "event_type",
        "actor",
    },
}
SCIENTIFIC_38 = ("scientific_records", "environmental_cache_entries")
SCIENTIFIC_39 = ("computed_metric_definitions", "computed_metric_results")
REVIEW_TABLE = "review_queue_item_events"


def _without_sql_comments(ddl: str) -> str:
    """Discard SQL comments without stripping quoted literals or identifiers."""
    tokens = re.compile(
        r"""('(?:''|[^'])*'|"(?:[^"]|"")*"|\x60(?:[^\x60]|\x60\x60)*\x60|\[[^]]*\])"""
        r"""|(--[^\r\n]*|/\*.*?\*/)""",
        flags=re.DOTALL,
    )
    return tokens.sub(lambda match: match.group(1) or " ", ddl)


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
        # A revision marker can survive corrupted cross-table relationships.
        # Check declared FKs even if the original writer disabled enforcement.
        # Aggregate offending child/parent table pairs without exposing row IDs
        # or private scientific values in a shareable migration audit report.
        violation_sources = Counter(
            (child, parent)
            for child, _row_id, parent, _fk_id in connection.execute("PRAGMA foreign_key_check")
        )
        foreign_key_violations = sum(violation_sources.values())
        foreign_key_violation_sources = [
            {"table": child, "parent_table": parent, "count": count}
            for (child, parent), count in sorted(violation_sources.items())
        ]
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

        qc_scope_violations: int | None = None
        qc_scope_error: str | None = None
        qc_request_key_unique: bool | None = None
        qc_required_columns_not_null: bool | None = None
        qc_event_foreign_keys_valid: bool | None = None
        qc_event_type_counts: list[tuple[object, int]] = []
        if signatures[REVIEW_TABLE]:
            # The applied 1.6/0038 schema requires complete attributed events.
            # SQLite UNIQUE indexes allow repeated NULL client request IDs,
            # so the presence of a unique index is not enough for idempotency.
            required_not_null = {
                "id",
                "review_queue_id",
                "review_queue_item_id",
                "project_id",
                "client_request_id",
                "event_type",
                "actor",
                "created_at",
            }
            not_null_columns = {
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{REVIEW_TABLE}")')
                if row[3]
            }
            qc_required_columns_not_null = required_not_null <= not_null_columns
            # 1.6/0038 guarantees idempotent append-only review requests by a
            # non-partial UNIQUE constraint on the item and client request ID.
            # A lookalike CHECK alone cannot establish this scientific history.
            qc_request_key_unique = False
            for index in connection.execute(f'PRAGMA index_list("{REVIEW_TABLE}")'):
                if not index[2] or index[4]:
                    continue
                index_name = index[1].replace('"', '""')
                key_columns = [
                    row[2]
                    for row in connection.execute(f'PRAGMA index_info("{index_name}")')
                ]
                if key_columns == ["review_queue_item_id", "client_request_id"]:
                    qc_request_key_unique = True
                    break
            # The actual 1.6/0038 migration declares three CASCADE foreign
            # keys. A lookalike table without those constraints can have valid
            # existing rows yet silently accept orphaned future QC events.
            required_foreign_keys = {
                ("review_queue_id", "review_queues", "id", "CASCADE"),
                ("review_queue_item_id", "review_queue_items", "id", "CASCADE"),
                ("project_id", "projects", "id", "CASCADE"),
            }
            foreign_keys = connection.execute(
                f'PRAGMA foreign_key_list("{REVIEW_TABLE}")'
            ).fetchall()
            qc_event_foreign_keys_valid = (
                len(foreign_keys) == len(required_foreign_keys)
                and {
                    (row[3], row[2], row[4], row[6].upper())
                    for row in foreign_keys
                    if row[1] == 0
                }
                == required_foreign_keys
            )
            qc_event_type_counts = connection.execute(
                f'SELECT event_type, COUNT(*) FROM "{REVIEW_TABLE}" GROUP BY event_type'
            ).fetchall()
        if signatures[REVIEW_TABLE]:
            # The real 1.6/0038 depends on these parent tables even when no
            # events have been appended. A lookalike empty QC event table
            # cannot certify the applied migration without its parent scope.
            # The 0039 upgrade additionally rejects orphaned/cross-project
            # historical events; inspect both invariants without writing.
            parent_columns = {
                "review_queues": {"id", "project_id"},
                "review_queue_items": {"id", "review_queue_id", "project_id"},
                "projects": {"id"},
            }
            missing = [
                name
                for name, required in parent_columns.items()
                if name not in tables
                or not required
                <= {row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')}
            ]
            if missing:
                qc_scope_error = "QC event parent tables missing required columns: " + ", ".join(
                    missing
                )
            else:
                # SQLite's != yields NULL for a missing parent scope, so
                # use NULL-safe IS NOT to catch corrupted legacy relationships.
                qc_scope_violations = connection.execute(
                    "SELECT COUNT(*) FROM review_queue_item_events AS event "
                    "LEFT JOIN review_queues AS queue ON queue.id = event.review_queue_id "
                    "LEFT JOIN review_queue_items AS item ON item.id = event.review_queue_item_id "
                    "LEFT JOIN projects AS project ON project.id = event.project_id "
                    "WHERE queue.id IS NULL OR item.id IS NULL OR project.id IS NULL "
                    "OR item.review_queue_id IS NOT event.review_queue_id "
                    "OR item.project_id IS NOT event.project_id "
                    "OR queue.project_id IS NOT event.project_id"
                ).fetchone()[0]

    versions = [row[0] for row in version_rows]
    groups = {
        "scientific_0038": all(signatures[t] for t in SCIENTIFIC_38),
        "scientific_0039": all(signatures[t] for t in SCIENTIFIC_39),
        "review_0038": signatures[REVIEW_TABLE],
    }
    # Match the actual event_type CHECK, not coincidental words elsewhere in
    # CREATE TABLE SQL (for example, a comment or an unrelated constraint).
    review_ddl = _without_sql_comments(tables.get(REVIEW_TABLE, ""))
    # A column name or DEFAULT string may itself contain a complete-looking
    # CHECK. Only count CHECK expressions starting outside SQL quoted tokens.
    quoted_spans = [
        (token.start(), token.end())
        for token in re.finditer(
            r"""'(?:''|[^'])*'|"(?:[^"]|"")*"|\x60(?:[^\x60]|\x60\x60)*\x60|\[[^]]*\]""",
            review_ddl,
        )
    ]
    matches = [
        candidate
        for candidate in re.finditer(
            r"""CHECK\s*\(\s*"?event_type"?\s+IN\s*\(([^)]*)\)\s*\)""",
            review_ddl,
            flags=re.IGNORECASE,
        )
        if not any(start <= candidate.start() < end for start, end in quoted_spans)
    ]
    # Multiple independent constraints may be narrower than either one.
    # Conservatively refuse lineage certification unless the CHECK is unique.
    match = matches[0] if len(matches) == 1 else None
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
    # SQLite CHECK expressions accept NULL, and an imported/older database
    # can contain historical values written with CHECK enforcement disabled.
    # Reconcile actual saved event values against the detected enforced set.
    qc_event_type_violations = sum(
        count for event_type, count in qc_event_type_counts if event_type not in allowed
    )
    issues = []
    if foreign_key_violations:
        issues.append(f"Database has {foreign_key_violations} foreign-key violations")
    if qc_event_type_violations:
        issues.append(
            f"QC review events contain {qc_event_type_violations} disallowed event types"
        )
    if incomplete:
        issues.append("Incomplete expected table signatures: " + ", ".join(incomplete))
    if qc_scope_error:
        issues.append(qc_scope_error)
    if qc_scope_violations:
        issues.append(
            f"QC review events contain {qc_scope_violations} orphaned or cross-project links"
        )
    if len(versions) != 1 or versions[0] not in ("0038", "0039"):
        issues.append("Alembic revision is not exactly one of 0038 or 0039")
    if any(signatures[t] for t in SCIENTIFIC_39) and not groups["scientific_0039"]:
        issues.append("Partial scientific 0039 schema")
    if any(signatures[t] for t in SCIENTIFIC_38) and not groups["scientific_0038"]:
        issues.append("Partial scientific 0038 schema")
    if groups["review_0038"] and review_check == "unknown":
        issues.append("QC event CHECK constraint cannot be identified")
    if groups["review_0038"] and not qc_request_key_unique:
        issues.append("QC event item/request uniqueness constraint is missing")
    if groups["review_0038"] and not qc_required_columns_not_null:
        issues.append("QC event required fields are missing or nullable")
    if groups["review_0038"] and not qc_event_foreign_keys_valid:
        issues.append("QC event required CASCADE foreign keys are missing or incorrect")
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
        "qc_event_scope_violations": qc_scope_violations,
        "qc_event_type_violations": qc_event_type_violations,
        "qc_request_key_unique": qc_request_key_unique,
        "qc_required_columns_not_null": qc_required_columns_not_null,
        "qc_event_foreign_keys_valid": qc_event_foreign_keys_valid,
        "foreign_key_violations": foreign_key_violations,
        "foreign_key_violation_sources": foreign_key_violation_sources,
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

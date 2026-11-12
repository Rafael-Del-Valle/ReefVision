#!/usr/bin/env python3
"""Read-only SQLite schema evidence for reviewed Alembic reconciliation.

Never infers applied migrations from alembic_version alone. Never changes a DB.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

TABLES = (
    "scientific_records", "environmental_cache_entries",
    "computed_metric_definitions", "computed_metric_results",
    "review_queue_item_events", "review_queue_bulk_requests",
)


def inspect(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    # mode=ro prevents writes; do not use immutable=1, which may hide WAL changes.
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        # Pin one read snapshot: concurrent WAL writers must not mix schema,
        # migration stamps, and FK evidence from different committed states.
        connection.execute("BEGIN")
        quick_check_details = [row[0] for row in connection.execute("PRAGMA quick_check")]
        integrity = "ok" if quick_check_details == ["ok"] else (quick_check_details[0] if quick_check_details else "no result")
        # Header fields are diagnostic evidence, not proof of Alembic lineage.
        sqlite_header = {
            "application_id": connection.execute("PRAGMA application_id").fetchone()[0],
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "schema_version": connection.execute("PRAGMA schema_version").fetchone()[0],
        }
        # A partially migrated schema can have an invalid FK parent key. SQLite
        # raises OperationalError instead of returning violations in that case.
        # Preserve the failure as evidence; never silently report zero violations.
        foreign_key_check_error = None
        try:
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        except sqlite3.DatabaseError as exc:
            foreign_keys = []
            foreign_key_check_error = str(exc)
        # Stable evidence ordering supports reproducible review reports across runs.
        foreign_keys.sort(key=lambda row: (str(row[0]), str(row[1]), str(row[2]), int(row[3])))
        # Fingerprint structural DDL, never biological records or user data.
        # Include views, indexes and triggers to distinguish colliding Alembic
        # stamps with different real schema topology. Exclude SQLite internals.
        # LIKE treats '_' as a wildcard and incorrectly drops user tables
        # named sqliteX...; only the reserved literal sqlite_ prefix is internal.
        schema_rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE substr(name, 1, 7) != 'sqlite_' "
            "ORDER BY type, name, tbl_name"
        ).fetchall()
        canonical_schema = json.dumps(schema_rows, ensure_ascii=False, separators=(",", ":"))
        schema_sha256 = hashlib.sha256(canonical_schema.encode("utf-8")).hexdigest()
        names = {row[1] for row in schema_rows if row[0] == "table"}
        stamps = []
        alembic_stamp_error = None
        alembic_stamp_validation_error = None
        if "alembic_version" in names:
            try:
                # Do not sort SQLite mixed-type values or serialize raw BLOBs:
                # malformed stamps must remain structured, JSON-safe evidence.
                raw_stamps = [row[0] for row in connection.execute(
                    "SELECT version_num FROM alembic_version"
                )]
                stamps = [value if isinstance(value, str) else None for value in raw_stamps]
                if len(raw_stamps) != 1:
                    alembic_stamp_validation_error = "expected_exactly_one_revision_row"
                elif not isinstance(raw_stamps[0], str) or (
                    not raw_stamps[0]
                    or raw_stamps[0] != raw_stamps[0].strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in raw_stamps[0])
                ):
                    alembic_stamp_validation_error = "invalid_revision_marker_type_or_value"
            except sqlite3.DatabaseError as exc:
                # Partial/corrupt lineage metadata must remain visible as
                # uncertain evidence, not abort an otherwise useful report.
                alembic_stamp_error = str(exc)
        tables = {}
        for name in TABLES:
            if name not in names:
                tables[name] = {"present": False}
                continue
            columns = [dict(zip(
                ("cid", "name", "type", "notnull", "default", "pk"), row
            )) for row in connection.execute(f'PRAGMA table_info("{name}")')]
            # table_info omits generated/hidden columns. Preserve its legacy
            # shape while exposing complete SQLite column topology separately.
            extended_columns = [dict(zip(
                ("cid", "name", "type", "notnull", "default", "pk", "hidden"), row
            )) for row in connection.execute(f'PRAGMA table_xinfo("{name}")')]
            fks = [dict(zip(
                ("id", "seq", "table", "from", "to", "on_update", "on_delete", "match"), row
            )) for row in connection.execute(f'PRAGMA foreign_key_list("{name}")')]
            indexes = [dict(zip(
                ("seq", "name", "unique", "origin", "partial"), row
            )) for row in connection.execute(f'PRAGMA index_list("{name}")')]
            tables[name] = {
                "present": True, "columns": columns,
                "extended_columns": extended_columns,
                "foreign_keys": fks, "indexes": indexes,
            }
        return {
            "database": str(path.resolve()), "read_only": True,
            "quick_check": integrity,
            "quick_check_details": quick_check_details,
            "schema_sha256": schema_sha256,
            "sqlite_header": sqlite_header,
            "foreign_key_violation_count": len(foreign_keys) if foreign_key_check_error is None else None,
            "foreign_key_check_error": foreign_key_check_error,
            "foreign_key_violations": [
                {"table": row[0], "rowid": row[1], "parent": row[2], "fkid": row[3]}
                for row in foreign_keys
            ],
            "alembic_stamps": stamps, "alembic_stamp_error": alembic_stamp_error,
            "alembic_stamp_validation_error": alembic_stamp_validation_error,
            "tables": tables,
            "classification": "requires_researcher_review",
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Existing SQLite database")
    parser.add_argument(
        "--fail-on-integrity-error",
        action="store_true",
        help="Exit 2 on SQLite integrity, FK, or Alembic metadata errors; "
        "still emit complete read-only JSON evidence",
    )
    args = parser.parse_args()
    evidence = inspect(args.database)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if args.fail_on_integrity_error and (
        evidence["quick_check_details"] != ["ok"]
        or evidence["foreign_key_check_error"] is not None
        or evidence["foreign_key_violation_count"] != 0
        or evidence["alembic_stamp_error"] is not None
        or evidence["alembic_stamp_validation_error"] is not None
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()

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
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        # Stable evidence ordering supports reproducible review reports across runs.
        foreign_keys.sort(key=lambda row: (str(row[0]), str(row[1]), str(row[2]), int(row[3])))
        # Fingerprint structural DDL, never biological records or user data.
        # Include views, indexes and triggers to distinguish colliding Alembic
        # stamps with different real schema topology. Exclude SQLite internals.
        schema_rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name, tbl_name"
        ).fetchall()
        canonical_schema = json.dumps(schema_rows, ensure_ascii=False, separators=(",", ":"))
        schema_sha256 = hashlib.sha256(canonical_schema.encode("utf-8")).hexdigest()
        names = {row[1] for row in schema_rows if row[0] == "table"}
        stamps = []
        if "alembic_version" in names:
            stamps = [row[0] for row in connection.execute(
                "SELECT version_num FROM alembic_version ORDER BY version_num"
            )]
        tables = {}
        for name in TABLES:
            if name not in names:
                tables[name] = {"present": False}
                continue
            columns = [dict(zip(
                ("cid", "name", "type", "notnull", "default", "pk"), row
            )) for row in connection.execute(f'PRAGMA table_info("{name}")')]
            fks = [dict(zip(
                ("id", "seq", "table", "from", "to", "on_update", "on_delete", "match"), row
            )) for row in connection.execute(f'PRAGMA foreign_key_list("{name}")')]
            indexes = [dict(zip(
                ("seq", "name", "unique", "origin", "partial"), row
            )) for row in connection.execute(f'PRAGMA index_list("{name}")')]
            tables[name] = {
                "present": True, "columns": columns,
                "foreign_keys": fks, "indexes": indexes,
            }
        return {
            "database": str(path.resolve()), "read_only": True,
            "quick_check": integrity,
            "schema_sha256": schema_sha256,
            "foreign_key_violation_count": len(foreign_keys),
            "foreign_key_violations": [
                {"table": row[0], "rowid": row[1], "parent": row[2], "fkid": row[3]}
                for row in foreign_keys
            ],
            "alembic_stamps": stamps, "tables": tables,
            "classification": "requires_researcher_review",
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Existing SQLite database")
    args = parser.parse_args()
    print(json.dumps(inspect(args.database), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

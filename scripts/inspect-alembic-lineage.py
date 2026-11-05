#!/usr/bin/env python3
"""Read-only SQLite Alembic lineage inventory; never infers a safe upgrade."""

import argparse
import json
import sqlite3
from pathlib import Path

FAMILIES = {
    "scientific": ("scientific_records", "environmental_cache_entries", "computed_metric_definitions", "computed_metric_results"),
    "qc": ("review_queue_item_events", "review_queue_bulk_requests"),
}


def inspect(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"Database file does not exist: {path}")
    # SQLite URI read-only mode prevents accidental creation of missing databases.
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        objects = {
            row[0]: row[1]
            for row in db.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view')")
        }
        revisions = (
            [row[0] for row in db.execute("SELECT version_num FROM alembic_version")]
            if objects.get("alembic_version") == "table"
            else []
        )
        inventory = {}
        for name in sorted(set(sum((list(v) for v in FAMILIES.values()), []))):
            if objects.get(name) != "table":
                inventory[name] = {"present": False}
                continue
            columns = [row[1] for row in db.execute(f'PRAGMA table_info("{name}")')]
            count = db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            inventory[name] = {"present": True, "columns": columns, "rows": count}
        scientific = any(inventory[name]["present"] for name in FAMILIES["scientific"])
        qc = any(inventory[name]["present"] for name in FAMILIES["qc"])
        lineage = "ambiguous" if scientific and qc else "scientific" if scientific else "qc" if qc else "unknown"
        return {
            "revision_rows": revisions,
            "lineage_hint": lineage,
            "upgrade_authorized": False,
            "inventory": inventory,
            "other_schema_objects": sorted(
                name for name in objects if name not in inventory and name != "alembic_version"
            ),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, help="Path to an immutable copy of the SQLite database")
    args = parser.parse_args()
    try:
        result = inspect(args.database)
    except (sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

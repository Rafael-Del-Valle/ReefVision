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
        version_table_present = objects.get("alembic_version") == "table"
        version_columns = (
            {row[1] for row in db.execute('PRAGMA table_info("alembic_version")')}
            if version_table_present
            else set()
        )
        # A malformed Alembic table is a diagnostic finding, not an inspector crash.
        revisions = (
            [row[0] for row in db.execute("SELECT version_num FROM alembic_version")]
            if "version_num" in version_columns
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
        warnings = []
        if not version_table_present:
            warnings.append("missing_alembic_version_table")
        elif "version_num" not in version_columns:
            warnings.append("missing_alembic_version_column")
        elif len(revisions) != 1 or not isinstance(revisions[0], str) or not revisions[0]:
            warnings.append("invalid_revision_marker_count_or_value")
        # A single family marker is only a hint: partial migrations are not complete schemas.
        for family, names in FAMILIES.items():
            present = [name for name in names if inventory[name]["present"]]
            if present and len(present) != len(names):
                warnings.append(f"incomplete_{family}_schema_family")
        if lineage == "ambiguous":
            warnings.append("mixed_scientific_and_qc_lineage")
        if "0038" in revisions:
            warnings.append("revision_0038_requires_schema_lineage_reconciliation")
        if lineage == "unknown":
            warnings.append("unrecognized_schema_lineage")
        return {
            "warnings": warnings,
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
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Exit with status 2 when any lineage warning is present (for CI/preflight only)",
    )
    args = parser.parse_args()
    try:
        result = inspect(args.database)
    except (sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.fail_on_warning and result["warnings"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

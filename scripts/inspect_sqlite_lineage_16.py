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
        # quick_check is a fast diagnostic but does not validate all index
        # relationships. A migration acceptance gate must also run the full
        # SQLite integrity check (bounded to 100 diagnostic rows).
        integrity_check_details = [
            row[0] for row in connection.execute("PRAGMA integrity_check(100)")
        ]
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
        alembic_stamp_constraint_error = None
        if "alembic_version" in names:
            try:
                # A foreign or partially migrated Alembic table can contain a
                # valid version_num alongside unrelated lineage columns. Never
                # accept that stamp as evidence of a canonical Alembic table.
                stamp_columns = list(
                    connection.execute("PRAGMA table_xinfo(alembic_version)")
                )
                if [row[1] for row in stamp_columns] != ["version_num"]:
                    alembic_stamp_validation_error = (
                        "unexpected_alembic_version_columns"
                    )
                elif (
                    stamp_columns[0][3] != 1  # NOT NULL
                    or stamp_columns[0][5] != 1  # single-column primary key
                    or stamp_columns[0][6] != 0  # ordinary, non-hidden column
                ):
                    # A name-only match can conceal an unrelated table with
                    # nonunique or nullable lineage markers. Do not trust it.
                    alembic_stamp_constraint_error = (
                        "invalid_alembic_version_column_constraints"
                    )
                # Do not sort SQLite mixed-type values or serialize raw BLOBs:
                # malformed stamps must remain structured, JSON-safe evidence.
                raw_stamps = [row[0] for row in connection.execute(
                    "SELECT version_num FROM alembic_version"
                )]
                stamps = [value if isinstance(value, str) else None for value in raw_stamps]
                if len(raw_stamps) != 1:
                    if alembic_stamp_validation_error is None:
                        alembic_stamp_validation_error = "expected_exactly_one_revision_row"
                elif (
                    not isinstance(raw_stamps[0], str)
                    or not raw_stamps[0]
                    or raw_stamps[0] != raw_stamps[0].strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in raw_stamps[0])
                ):
                    if alembic_stamp_validation_error is None:
                        alembic_stamp_validation_error = "invalid_revision_marker_type_or_value"
            except sqlite3.DatabaseError as exc:
                # Partial/corrupt lineage metadata must remain visible as
                # uncertain evidence, not abort an otherwise useful report.
                alembic_stamp_error = str(exc)
        else:
            # An unstamped database cannot pass the optional migration-integrity gate.
            # Preserve read-only evidence; never infer or create a revision marker.
            alembic_stamp_validation_error = "missing_alembic_version_table"
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
            "integrity_check_details": integrity_check_details,
            "schema_sha256": schema_sha256,
            # Names and kinds permit human comparison of colliding histories
            # without exposing DDL expressions or scientific record values.
            "schema_objects": [
                {"type": kind, "name": name, "table": table}
                for kind, name, table, _sql in schema_rows
            ],
            "sqlite_header": sqlite_header,
            "foreign_key_violation_count": len(foreign_keys) if foreign_key_check_error is None else None,
            "foreign_key_check_error": foreign_key_check_error,
            "foreign_key_violations": [
                {"table": row[0], "rowid": row[1], "parent": row[2], "fkid": row[3]}
                for row in foreign_keys
            ],
            "alembic_stamps": stamps, "alembic_stamp_error": alembic_stamp_error,
            "alembic_stamp_validation_error": alembic_stamp_validation_error,
            "alembic_stamp_constraint_error": alembic_stamp_constraint_error,
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
        help="Exit 2 on SQLite integrity, FK, or Alembic metadata errors in either input; "
        "still emit complete read-only JSON evidence",
    )
    parser.add_argument(
        "--compare-to",
        type=Path,
        help="Compare structural evidence against another existing SQLite database; "
        "both databases remain read-only",
    )
    parser.add_argument(
        "--fail-on-schema-drift",
        action="store_true",
        help="Exit 2 when --compare-to finds different structural fingerprints",
    )
    parser.add_argument(
        "--fail-on-revision-mismatch",
        action="store_true",
        help="Exit 2 when --compare-to finds different Alembic revision markers; "
        "still require human review even when markers match",
    )
    parser.add_argument(
        "--fail-on-lineage-collision",
        action="store_true",
        help="Exit 2 when --compare-to has the same validated Alembic revision "
        "but a different structural schema fingerprint; matching stamps "
        "never establish migration equivalence",
    )
    parser.add_argument(
        "--fail-on-noncanonical-stamp", action="store_true",
        help="Exit 2 if Alembic version_num lacks NOT NULL and primary-key constraints; "
        "opt-in for legacy SQLite schemas",
    )
    args = parser.parse_args()
    if args.fail_on_schema_drift and args.compare_to is None:
        parser.error("--fail-on-schema-drift requires --compare-to")
    if args.fail_on_revision_mismatch and args.compare_to is None:
        parser.error("--fail-on-revision-mismatch requires --compare-to")
    if args.fail_on_lineage_collision and args.compare_to is None:
        parser.error("--fail-on-lineage-collision requires --compare-to")
    # Validate both inputs before samefile(): pathlib.samefile raises an
    # unhandled OSError for missing paths. Report a stable CLI usage error
    # without attempting to create or modify either research database.
    for candidate in (args.database, args.compare_to):
        if candidate is not None and not candidate.is_file():
            parser.error(f"database must be an existing file: {candidate}")
    if args.compare_to is not None and args.database.samefile(args.compare_to):
        parser.error("--compare-to requires an independent database, not the same file")
    # Existing files are not necessarily SQLite databases. A corrupt or
    # unrelated file must fail closed without a Python traceback or writes.
    try:
        evidence = inspect(args.database)
        reference = inspect(args.compare_to) if args.compare_to is not None else None
    except (sqlite3.DatabaseError, OSError) as exc:
        parser.error(f"unable to inspect SQLite database: {type(exc).__name__}")
    if reference is not None:
        source_objects = {
            (obj["type"], obj["name"], obj["table"])
            for obj in evidence["schema_objects"]
        }
        reference_objects = {
            (obj["type"], obj["name"], obj["table"])
            for obj in reference["schema_objects"]
        }

        def describe(objects: set[tuple[str, str, str]]) -> list[dict[str, str]]:
            return [
                {"type": kind, "name": name, "table": table}
                for kind, name, table in sorted(objects)
            ]

        evidence["schema_comparison"] = {
            "reference_database": reference["database"],
            "reference_schema_sha256": reference["schema_sha256"],
            # Show both validated revision values to support independent human
            # reconciliation; a boolean alone cannot explain mismatched stamps.
            "reference_alembic_stamps": reference["alembic_stamps"],
            "reference_integrity": {
                "quick_check_details": reference["quick_check_details"],
                "integrity_check_details": reference["integrity_check_details"],
                "foreign_key_violation_count": reference["foreign_key_violation_count"],
                "foreign_key_check_error": reference["foreign_key_check_error"],
                "alembic_stamp_error": reference["alembic_stamp_error"],
                "alembic_stamp_validation_error": reference["alembic_stamp_validation_error"],
                "alembic_stamp_constraint_error": reference["alembic_stamp_constraint_error"],
            },
            "matches": evidence["schema_sha256"] == reference["schema_sha256"],
            "revision_markers_match": (
                len(evidence["alembic_stamps"]) == 1
                and evidence["alembic_stamps"] == reference["alembic_stamps"]
                and evidence["alembic_stamp_error"] is None
                and reference["alembic_stamp_error"] is None
                and evidence["alembic_stamp_validation_error"] is None
                and reference["alembic_stamp_validation_error"] is None
            ),
            "only_in_database": describe(source_objects - reference_objects),
            "only_in_reference": describe(reference_objects - source_objects),
            # Same named object can have different DDL; hashes, not name
            # equality, determine structural equivalence.
            "requires_researcher_review": True,
        }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if args.fail_on_schema_drift and not evidence["schema_comparison"]["matches"]:
        raise SystemExit(2)

    if args.fail_on_revision_mismatch and not evidence["schema_comparison"]["revision_markers_match"]:
        raise SystemExit(2)

    if args.fail_on_lineage_collision:
        # Invalid or missing stamps must not silently pass a collision gate.
        # Legacy non-PK stamps remain inspectable unless strict mode is selected.
        if (
            not evidence["schema_comparison"]["revision_markers_match"]
            or not evidence["schema_comparison"]["matches"]
            or evidence["alembic_stamp_constraint_error"] is not None
            or reference["alembic_stamp_constraint_error"] is not None
        ):
            raise SystemExit(2)

    def has_integrity_error(report: dict) -> bool:
        return (
            report["quick_check_details"] != ["ok"]
            or report["integrity_check_details"] != ["ok"]
            or report["foreign_key_check_error"] is not None
            or report["foreign_key_violation_count"] != 0
            or report["alembic_stamp_error"] is not None
            or report["alembic_stamp_validation_error"] is not None
        )

    if args.fail_on_noncanonical_stamp and (
        evidence["alembic_stamp_constraint_error"] is not None
        or (reference is not None and reference["alembic_stamp_constraint_error"] is not None)
    ):
        raise SystemExit(2)

    if args.fail_on_integrity_error and (
        has_integrity_error(evidence)
        or (reference is not None and has_integrity_error(reference))
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()

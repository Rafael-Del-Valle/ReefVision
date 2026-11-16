#!/usr/bin/env python3
"""Read-only SQLite Alembic lineage inventory; never infers a safe upgrade."""

import argparse
import json
import sqlite3
from pathlib import Path

# 1.1 added these in revisions 0040 and 0042. They are optional at earlier
# legitimate revisions, so do not add them to the all-or-none base family.
SCIENCE_EXTENSIONS = (
    "environmental_event_definitions",
    "environmental_analysis_definitions",
    "environmental_analysis_results",
)

FAMILIES = {
    "scientific": (
        "scientific_records",
        "environmental_cache_entries",
        "computed_metric_definitions",
        "computed_metric_results",
    ),
    "qc": ("review_queue_item_events", "review_queue_bulk_requests"),
}


def inspect(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"Database file does not exist: {path}")
    # SQLite URI read-only mode prevents accidental creation of missing databases.
    resolved_path = path.resolve()
    uri = resolved_path.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        # Pin one SQLite read transaction before the first integrity probe.
        # Without BEGIN, each subsequent SELECT can see a different WAL
        # commit (revision stamp, schema and scientific counts may disagree).
        db.execute("BEGIN")
        # A corrupt snapshot must not be considered a valid migration candidate.
        # quick_check(1) is bounded in reported errors; it does not repair data.
        integrity_result = db.execute("PRAGMA quick_check(1)").fetchone()
        integrity_ok = integrity_result is not None and integrity_result[0] == "ok"
        # Unlike quick_check, integrity_check also validates UNIQUE constraints
        # and index/table consistency; an immutable scientific backup needs both.
        full_integrity_result = db.execute("PRAGMA integrity_check(1)").fetchone()
        full_integrity_ok = full_integrity_result is not None and full_integrity_result[0] == "ok"
        # quick_check does not detect orphaned foreign-key references.
        # Preserve a bounded count without exposing potentially sensitive row contents.
        try:
            foreign_key_violations = sum(1 for _ in db.execute("PRAGMA foreign_key_check"))
            foreign_key_check_error = None
        except sqlite3.DatabaseError as exc:
            # A malformed FK definition (for example, a non-unique parent key)
            # makes SQLite raise rather than enumerate orphaned rows.
            # Report an explicit unsafe state instead of aborting the inventory.
            foreign_key_violations = None
            foreign_key_check_error = str(exc)
        objects = {
            row[0]: row[1]
            for row in db.execute(
                "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        version_table_present = objects.get("alembic_version") == "table"
        version_columns = (
            {row[1] for row in db.execute('PRAGMA table_info("alembic_version")')}
            if version_table_present
            else set()
        )
        # Alembic's canonical SQLite stamp is a single non-null primary-key
        # version_num column. A plausible revision string alone is insufficient
        # evidence when a restored table permits duplicate or NULL stamps.
        version_table_info = (
            list(db.execute('PRAGMA table_info("alembic_version")'))
            if version_table_present
            else []
        )
        canonical_stamp_constraints = (
            len(version_table_info) == 1
            and version_table_info[0][1] == "version_num"
            and str(version_table_info[0][2]).upper() in {"VARCHAR(32)", "VARCHAR", "TEXT"}
            and version_table_info[0][3] == 1
            and version_table_info[0][5] == 1
        )
        # A malformed Alembic table is a diagnostic finding, not an inspector crash.
        revisions = (
            [row[0] for row in db.execute("SELECT version_num FROM alembic_version")]
            if "version_num" in version_columns
            else []
        )
        inventory = {}
        names = set(SCIENCE_EXTENSIONS)
        names.update(name for family in FAMILIES.values() for name in family)
        for name in sorted(names):
            if objects.get(name) != "table":
                inventory[name] = {"present": False}
                continue
            columns = [row[1] for row in db.execute(f'PRAGMA table_info("{name}")')]
            count = db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            inventory[name] = {"present": True, "columns": columns, "rows": count}
        scientific = any(
            inventory[name]["present"] for name in (*FAMILIES["scientific"], *SCIENCE_EXTENSIONS)
        )
        qc = any(inventory[name]["present"] for name in FAMILIES["qc"])
        lineage = (
            "ambiguous"
            if scientific and qc
            else "scientific"
            if scientific
            else "qc"
            if qc
            else "unknown"
        )
        warnings = []
        if not integrity_ok:
            warnings.append("sqlite_integrity_check_failed")
        if not full_integrity_ok:
            warnings.append("sqlite_full_integrity_check_failed")
        if foreign_key_check_error is not None:
            warnings.append("sqlite_foreign_key_check_failed")
        elif foreign_key_violations:
            warnings.append("sqlite_foreign_key_violations")
        # A live SQLite WAL/journal can contain uncheckpointed scientific edits.
        # Do not mistake a mutable database plus sidecars for an immutable backup.
        for suffix, warning in (
            ("-wal", "wal_sidecar_requires_consistent_snapshot"),
            ("-shm", "shared_memory_sidecar_requires_consistent_snapshot"),
            ("-journal", "rollback_journal_requires_consistent_snapshot"),
        ):
            if Path(str(resolved_path) + suffix).exists():
                warnings.append(warning)
        if not version_table_present:
            warnings.append("missing_alembic_version_table")
        else:
            # Preserve specific provenance diagnostics as well as the strict
            # canonical-constraint warning. The latter must not conceal a
            # missing or foreign column in read-only researcher reports.
            if "version_num" not in version_columns:
                warnings.append("missing_alembic_version_column")
            elif version_columns != {"version_num"}:
                warnings.append("unexpected_alembic_version_columns")
            if not canonical_stamp_constraints:
                warnings.append("noncanonical_alembic_stamp_constraints")
        if (
            version_table_present
            and "version_num" in version_columns
            and (
                len(revisions) != 1
                or not isinstance(revisions[0], str)
                or not revisions[0]
                or revisions[0] != revisions[0].strip()
                or any(ord(character) < 32 or ord(character) == 127 for character in revisions[0])
            )
        ):
            warnings.append("invalid_revision_marker_count_or_value")
        # The 1.1 scientific tables arrive in separate 0038 and 0039
        # migrations. A complete 0038 pair alone is NOT an interrupted
        # four-table family; inspect each stage independently.
        science_base = FAMILIES["scientific"][:2]
        science_metrics = FAMILIES["scientific"][2:]
        # Each QC migration stage is independent: 0038 creates the review
        # events, and 0041 later creates the bulk request registry. A 0038,
        # 0039, or 0040 QC database legitimately has no bulk table.
        if any(
            0 < sum(inventory[name]["present"] for name in stage) < len(stage)
            for stage in (science_base, science_metrics)
        ):
            warnings.append("incomplete_scientific_schema_family")
        qc_events_present = inventory["review_queue_item_events"]["present"]
        qc_bulk_present = inventory["review_queue_bulk_requests"]["present"]
        if qc_bulk_present and not qc_events_present:
            warnings.append("qc_bulk_registry_without_review_events")
        # A surviving later-stage table with an earlier stamp is an
        # interrupted DDL/restore, not evidence that the migration finished.
        # Some legacy backups carry stamps earlier than 0037. The QC event
        # table was first introduced in 0038, and bulk requests in 0041:
        # reject *every* earlier numeric stage, not just the immediate prior
        # stamps. Do not interpret malformed/non-numeric stamps as a stage.
        stamped_revision = revisions[0] if len(revisions) == 1 else None
        numeric_revision = (
            int(stamped_revision)
            if isinstance(stamped_revision, str)
            and len(stamped_revision) == 4
            and stamped_revision.isascii()
            and stamped_revision.isdecimal()
            else None
        )
        if qc_events_present and numeric_revision is not None and numeric_revision < 38:
            warnings.append("qc_events_before_revision_0038")
        if qc_bulk_present and numeric_revision is not None and numeric_revision < 41:
            warnings.append("qc_bulk_registry_before_revision_0041")
        if qc_events_present and not qc_bulk_present and "0041" in revisions:
            warnings.append("qc_0041_missing_bulk_registry")
        metric_present = any(inventory[name]["present"] for name in science_metrics)
        metric_complete = all(inventory[name]["present"] for name in science_metrics)
        # Installed 1.1 scientific tables cannot precede their migration
        # stages. A valid-looking 0037 stamp with fully populated 0038/0039
        # tables is an interrupted migration, not warning-free provenance.
        # This check also covers older numeric revisions, matching the
        # existing QC stage-order checks without trusting the Alembic stamp.
        if numeric_revision is not None:
            if numeric_revision < 38 and any(
                inventory[name]["present"] for name in science_base
            ):
                warnings.append("scientific_base_before_revision_0038")
            if numeric_revision < 39 and metric_present:
                warnings.append("computed_metrics_before_revision_0039")
        if metric_present and not all(inventory[name]["present"] for name in science_base):
            warnings.append("computed_metrics_without_scientific_base")
        # Environmental 0040/0042 records are identifiable even when a
        # partial restore has lost all 0038-0039 base scientific tables.
        # Do not report an incomplete optional extension on a valid 0037 DB.
        present_extensions = {name for name in SCIENCE_EXTENSIONS if inventory[name]["present"]}
        if present_extensions and not any(
            inventory[name]["present"] for name in FAMILIES["scientific"]
        ):
            warnings.append("scientific_extension_without_base_lineage")
        analysis_pair = {
            "environmental_analysis_definitions",
            "environmental_analysis_results",
        }
        if present_extensions & analysis_pair and not analysis_pair <= present_extensions:
            warnings.append("incomplete_environmental_analysis_schema_family")
        # The real 1.1 Alembic lineage creates event definitions at 0040,
        # before either analysis table at 0042. A complete analysis pair
        # without its predecessor is still an interrupted/foreign schema.
        # Do not infer that an apparently valid 0042 stamp repairs it.
        if "environmental_event_definitions" in present_extensions and not metric_complete:
            warnings.append("environmental_event_without_computed_metrics")
        if present_extensions & analysis_pair and not metric_complete:
            warnings.append("environmental_analysis_without_computed_metrics")
        if present_extensions & analysis_pair and (
            "environmental_event_definitions" not in present_extensions
        ):
            warnings.append("environmental_analysis_without_event_definitions")
        # The 1.1 environmental stages have distinct Alembic revision
        # boundaries. Complete-looking extension tables with an earlier stamp
        # can be a partial restore, not successful migrated research data.
        # Only use scientific-only lineage here: the 1.6 QC branch reuses
        # numeric revision names for unrelated schema operations.
        if lineage == "scientific" and len(revisions) == 1:
            revision = revisions[0]
            if (
                revision in {"0037", "0038", "0039"}
                and "environmental_event_definitions" in present_extensions
            ):
                warnings.append("environmental_event_before_revision_0040")
            if revision in {"0037", "0038", "0039", "0040", "0041"} and (
                present_extensions & analysis_pair
            ):
                warnings.append("environmental_analysis_before_revision_0042")
        if lineage == "ambiguous":
            warnings.append("mixed_scientific_and_qc_lineage")
        if "0038" in revisions:
            warnings.append("revision_0038_requires_schema_lineage_reconciliation")
        if lineage == "unknown":
            warnings.append("unrecognized_schema_lineage")
        return {
            "warnings": warnings,
            "sqlite_integrity_ok": integrity_ok,
            "sqlite_full_integrity_ok": full_integrity_ok,
            "sqlite_foreign_key_violations": foreign_key_violations,
            "sqlite_foreign_key_check_error": foreign_key_check_error,
            # SQLite permits BLOB/INTEGER revision cells despite Alembic expecting TEXT.
            # Keep the report JSON-safe without exposing arbitrary binary payloads.
            "revision_rows": [value if isinstance(value, str) else None for value in revisions],
            "canonical_alembic_stamp_constraints": canonical_stamp_constraints,
            "lineage_hint": lineage,
            "upgrade_authorized": False,
            "inventory": inventory,
            "other_schema_objects": sorted(
                name for name in objects if name not in inventory and name != "alembic_version"
            ),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "database", type=Path, help="Path to an immutable copy of the SQLite database"
    )
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

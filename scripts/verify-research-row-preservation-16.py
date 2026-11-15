#!/usr/bin/env python3
"""Read-only, content-level preservation gate for disposable ReefVision migration copies.

This is NOT a migrator, schema compatibility proof, or automatic release approval.
Compare an offline *before* database to its upgraded *after* copy. All existing
columns and rows (including SQLite generated-column values) in protected
scientific, review, class, and workflow tables must be identical; added columns
and new tables are allowed, but changed rows
and new rows in preexisting tables require independent researcher review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import ExitStack
from pathlib import Path

# An explicitly bounded coverage contract: this does not prove preservation of
# other project tables, external media, model checkpoints, or sidecar files.
PROTECTED_TABLES = (
    "projects",
    "label_classes",
    "class_operations",
    "class_visibility_preferences",
    "project_class_visibility_defaults",
    "annotations",
    "annotation_events",
    "mask_annotations",
    "mask_annotation_events",
    "dataset_versions",
    "dataset_version_items",
    "quality_control_runs",
    "review_queues",
    "review_queue_items",
    "review_queue_item_events",
    "review_queue_bulk_requests",
    "workflow_graph_records",
    "workflow_runs",
    "workflow_node_runs",
    "workflow_artifacts",
    "scientific_records",
    "environmental_cache_entries",
    "computed_metric_definitions",
    "computed_metric_results",
    "environmental_event_definitions",
    "environmental_analysis_definitions",
    "environmental_analysis_results",
)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _sidecars(path: Path) -> bool:
    return any(Path(f"{path}{suffix}").exists() for suffix in ("-wal", "-shm", "-journal"))


def _open_snapshot(path: Path, stack: ExitStack) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError("database_missing")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    stack.callback(connection.close)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    if connection.execute("PRAGMA integrity_check(1)").fetchone() != ("ok",):
        raise ValueError("integrity_check_failed")
    try:
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("foreign_key_violation")
    except sqlite3.DatabaseError as exc:
        raise ValueError("foreign_key_check_failed") from exc
    return connection


def _table_columns(
    connection: sqlite3.Connection, table: str
) -> tuple[list[str], list[str]] | None:
    exists = connection.execute(
        "SELECT type FROM sqlite_master WHERE name = ?", (table,)
    ).fetchone()
    if exists is None:
        return None
    if exists[0] != "table":
        raise ValueError("protected_name_not_a_table")
    # table_info silently omits VIRTUAL/STORED generated columns. They can
    # contain measured or interpreted scientific values that must survive a
    # migration, even if every ordinary source column remains byte-identical.
    info = list(connection.execute(f"PRAGMA table_xinfo({_quote(table)})"))
    if not info:
        raise ValueError("protected_table_has_no_columns")
    if any(row[6] == 1 for row in info):
        # Hidden virtual-table fields have implementation-specific behavior;
        # do not issue a preservation PASS for an unsupported table type.
        raise ValueError("protected_virtual_table_not_supported")
    columns = [row[1] for row in info]
    primary_key = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
    return columns, primary_key


def _encode_row(row: tuple) -> bytes:
    typed = []
    for value in row:
        if value is None:
            typed.append(["null", None])
        elif isinstance(value, int):
            typed.append(["integer", str(value)])
        elif isinstance(value, float):
            typed.append(["real", value.hex()])
        elif isinstance(value, str):
            typed.append(["text", value])
        elif isinstance(value, bytes):
            typed.append(["blob", value.hex()])
        else:
            raise ValueError("unsupported_sqlite_value_type")
    return json.dumps(typed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _fingerprint(
    connection: sqlite3.Connection, table: str, columns: list[str], order_by: list[str]
) -> tuple[int, str]:
    projected = ", ".join(_quote(column) for column in columns)
    ordered = ", ".join(_quote(column) for column in order_by)
    sha = hashlib.sha256()
    rows = 0
    for row in connection.execute(f"SELECT {projected} FROM {_quote(table)} ORDER BY {ordered}"):
        encoded = _encode_row(row)
        sha.update(len(encoded).to_bytes(8, "big"))
        sha.update(encoded)
        rows += 1
    return rows, sha.hexdigest()


def verify(before: Path, after: Path) -> dict:
    """Produce only diagnostic digests/counts; never return research row values."""
    before = before.resolve()
    after = after.resolve()
    if before == after or (before.is_file() and after.is_file() and before.samefile(after)):
        raise ValueError("inputs_must_be_independent_database_copies")
    sidecars_before = _sidecars(before) or _sidecars(after)
    with ExitStack() as stack:
        old = _open_snapshot(before, stack)
        new = _open_snapshot(after, stack)
        tables = []
        problems = []
        covered = 0
        for table in PROTECTED_TABLES:
            old_info = _table_columns(old, table)
            new_info = _table_columns(new, table)
            if old_info is None:
                tables.append({"table": table, "status": "not_in_baseline"})
                continue
            covered += 1
            old_columns, old_primary_key = old_info
            item: dict = {"table": table, "status": "preserved"}
            if new_info is None:
                item["status"] = "removed_table"
            else:
                new_columns, new_primary_key = new_info
                missing = [column for column in old_columns if column not in new_columns]
                if missing:
                    item["status"] = "removed_columns"
                    item["removed_columns"] = missing
                elif old_primary_key != new_primary_key:
                    item["status"] = "changed_primary_key"
                else:
                    order_by = old_primary_key or old_columns
                    old_count, old_sha = _fingerprint(old, table, old_columns, order_by)
                    new_count, new_sha = _fingerprint(new, table, old_columns, order_by)
                    item.update(
                        baseline_rows=old_count,
                        candidate_rows=new_count,
                        baseline_sha256=old_sha,
                        candidate_sha256=new_sha,
                    )
                    if old_count != new_count or old_sha != new_sha:
                        item["status"] = "changed_records"
            if item["status"] != "preserved":
                problems.append(table + ":" + item["status"])
            tables.append(item)
        if covered == 0:
            problems.append("no_protected_baseline_tables")
        # Sidecars can appear or disappear while reading a WAL database. Even
        # successful snapshots are not approval to copy a live DB's main file.
        if sidecars_before or _sidecars(before) or _sidecars(after):
            problems.append("mutable_sqlite_sidecar_detected")
        return {
            "status": "HOLD" if problems else "PASS_PRESERVATION_ONLY",
            "upgrade_authorized": False,
            "requires_researcher_approval": True,
            "protected_tables_examined": covered,
            "problems": problems,
            "tables": tables,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--before", required=True, type=Path, help="Unmodified offline baseline copy"
    )
    parser.add_argument(
        "--after", required=True, type=Path, help="Independent upgraded offline copy"
    )
    args = parser.parse_args()
    try:
        report = verify(args.before, args.after)
    except (OSError, sqlite3.DatabaseError, ValueError) as exc:
        report = {
            "status": "HOLD",
            "upgrade_authorized": False,
            "requires_researcher_approval": True,
            "problems": [str(exc) if isinstance(exc, ValueError) else type(exc).__name__],
        }
    print(json.dumps(report, sort_keys=True, indent=2))
    if report["status"] != "PASS_PRESERVATION_ONLY":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

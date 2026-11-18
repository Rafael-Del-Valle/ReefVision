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
import os
import sqlite3
import stat
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


def _column_contracts(connection: sqlite3.Connection, table: str) -> dict[str, tuple]:
    """Preserve the interpretation of every existing scientific column.

    Equal current values cannot prove that an upgrade retained NOT NULL,
    declared type/affinity, defaults, primary-key positions or generated-column
    flags for observations written after the migration.
    """
    return {
        row[1]: (row[2].strip().upper(), row[3], row[4], row[5], row[6])
        for row in connection.execute(f"PRAGMA table_xinfo({_quote(table)})")
    }


def _foreign_key_contracts(connection: sqlite3.Connection, table: str) -> set[tuple]:
    """Compare complete original FK groups, including composite-key order.

    New constraints are allowed, but existing scientific parent relationships,
    ON DELETE and ON UPDATE actions must survive unchanged.
    """
    groups: dict[int, list[tuple]] = {}
    for row in connection.execute(f"PRAGMA foreign_key_list({_quote(table)})"):
        groups.setdefault(row[0], []).append(tuple(row[1:]))
    return {tuple(sorted(group)) for group in groups.values()}


def _unique_index_contracts(connection: sqlite3.Connection, table: str) -> set[tuple]:
    """Retain original uniqueness semantics for future scientific observations.

    SQLite's index_list/xinfo expose ordinary, auto-generated and expression
    indexes. Include key order, collation, direction and partial predicates;
    compare SQL only when the predicate or key expression cannot be recovered
    structurally. Never include this private SQL in the public report.
    """
    contracts: set[tuple] = set()
    for _seq, index, unique, origin, partial in connection.execute(
        f"PRAGMA index_list({_quote(table)})"
    ):
        if not unique:
            continue
        components = tuple(
            (entry[1], entry[2], entry[3], entry[4])
            for entry in connection.execute(f"PRAGMA index_xinfo({_quote(index)})")
            if entry[5]
        )
        definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (index,)
        ).fetchone()
        sql = definition[0] if definition else None
        # Index names are not scientific constraints: allow an equivalent
        # ordinary index to be renamed, but reject changed WHERE predicates
        # and functional expressions that index_xinfo cannot fully describe.
        expression_or_predicate = bool(partial) or any(part[0] == -2 for part in components)
        contracts.add((origin, bool(partial), components, sql if expression_or_predicate else None))
    return contracts


def _ddl_tokens(sql: str) -> tuple[str, ...]:
    """Tokenize stored table DDL without confusing quoted text with SQL rules.

    Reworded but logically equivalent CHECK expressions require manual review
    rather than an automatic preservation PASS.
    """
    tokens: list[str] = []
    index = 0
    while index < len(sql):
        char = sql[index]
        if char.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = len(sql) if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                raise ValueError("unterminated_table_ddl_comment")
            index = end + 2
            continue
        if char in ("'", '"', chr(96), "["):
            closing = "]" if char == "[" else char
            end = index + 1
            while end < len(sql):
                if sql[end] == closing:
                    if closing != "]" and end + 1 < len(sql) and sql[end + 1] == closing:
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            else:
                raise ValueError("unterminated_table_ddl_quote")
            tokens.append(sql[index:end])
            index = end
            continue
        if char.isalnum() or char in ("_", "$"):
            end = index + 1
            while end < len(sql) and (sql[end].isalnum() or sql[end] in ("_", "$")):
                end += 1
            tokens.append(sql[index:end].upper())
            index = end
            continue
        tokens.append(char)
        index += 1
    return tuple(tokens)


def _check_constraint_contracts(
    connection: sqlite3.Connection, table: str
) -> set[tuple[str, ...]]:
    """Preserve existing nested CHECK predicates without exposing private DDL."""
    definition = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if definition is None or not isinstance(definition[0], str):
        raise ValueError("protected_table_ddl_missing")
    tokens = _ddl_tokens(definition[0])
    contracts: set[tuple[str, ...]] = set()
    for index, token in enumerate(tokens[:-1]):
        if token != "CHECK" or tokens[index + 1] != "(":
            continue
        depth = 0
        for end in range(index + 1, len(tokens)):
            if tokens[end] == "(":
                depth += 1
            elif tokens[end] == ")":
                depth -= 1
                if depth == 0:
                    contracts.add(tokens[index + 1 : end + 1])
                    break
        else:
            raise ValueError("unterminated_table_check_constraint")
    return contracts


def _table_storage_contract(connection: sqlite3.Connection, table: str) -> tuple[int, int]:
    """Retain WITHOUT ROWID and STRICT enforcement of protected tables."""
    row = connection.execute(
        "SELECT wr, strict FROM pragma_table_list "
        "WHERE schema = 'main' AND type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if row is None:
        raise ValueError("protected_table_storage_unknown")
    return (row[0], row[1])


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


def _protected_autoincrement_sequences(
    connection: sqlite3.Connection,
) -> dict[str, list[object]]:
    """Read allocation history for protected AUTOINCREMENT tables, if present.

    sqlite_sequence is SQLite bookkeeping rather than an ordinary scientific
    table. Equal existing row values alone do not prove the next allocated
    identifier is preserved, particularly after a highest-numbered row was
    deleted. Only protect counters belonging to our explicitly scoped tables.
    """
    present = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
    ).fetchone()
    if present is None:
        return {}
    placeholders = ", ".join("?" for _ in PROTECTED_TABLES)
    rows = connection.execute(
        f"SELECT name, seq FROM sqlite_sequence WHERE name IN ({placeholders}) ORDER BY rowid",
        PROTECTED_TABLES,
    )
    counters: dict[str, list[object]] = {}
    for name, sequence in rows:
        counters.setdefault(name, []).append(sequence)
    return counters


def _is_unsafe_asset_link(path: Path, info: os.stat_result | None = None) -> bool:
    """Reject links and Windows junctions/reparse points, not merely symlinks.

    A Windows junction can expose files outside an apparently isolated
    researcher-owned directory without Path.is_symlink() returning True.
    """
    details = path.lstat() if info is None else info
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return (
        stat.S_ISLNK(details.st_mode)
        or bool(reparse and (getattr(details, "st_file_attributes", 0) & reparse))
        or bool(getattr(path, "is_junction", lambda: False)())
    )


def _asset_state(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    """Identity and mutation-sensitive metadata for an offline regular file."""
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        stat.S_IFMT(info.st_mode),
        info.st_nlink,
    )


def _asset_handle_state(info: os.stat_result) -> tuple[int, ...]:
    """Compare path/handle identity excluding Windows creation-time discrepancies.

    Windows may report differing ctime through lstat and fstat for the same
    file, even when inode, contents and timestamps are stable. Compare ctime
    within each metadata source instead: path before/after, handle before/after.
    """
    values = _asset_state(info)
    return values[:4] + values[5:]


def _asset_mismatch_fields(first: os.stat_result, second: os.stat_result) -> str:
    """Identify differing identity fields without exposing research paths or values."""
    labels = ("device", "inode", "size", "mtime", "type", "links")
    return ",".join(
        label
        for label, a, b in zip(
            labels, _asset_handle_state(first), _asset_handle_state(second), strict=True
        )
        if a != b
    )


def _asset_inventory(
    root: Path,
) -> tuple[
    dict[str, str],
    set[tuple[int, int]],
    dict[str, tuple[int, ...]],
    dict[str, tuple[int, ...]],
]:
    """Hash regular research assets in bounded chunks without following symlinks.

    File names are used only for an in-process relative-path comparison and
    are never included in the public diagnostic report.
    """
    if _is_unsafe_asset_link(root) or not root.is_dir():
        raise ValueError("invalid_asset_root")

    def _on_walk_error(exc: OSError) -> None:
        raise ValueError("asset_inventory_io_error") from exc

    inventory: dict[str, str] = {}
    file_identities: set[tuple[int, int]] = set()
    file_states: dict[str, tuple[int, ...]] = {}
    directory_states: dict[str, tuple[int, ...]] = {}
    for parent, directories, filenames in os.walk(
        root, topdown=True, followlinks=False, onerror=_on_walk_error
    ):
        directories.sort()
        filenames.sort()
        directory = Path(parent)
        directory_info = directory.lstat()
        if _is_unsafe_asset_link(directory, directory_info):
            raise ValueError("asset_symlink_not_allowed")
        if not stat.S_ISDIR(directory_info.st_mode):
            raise ValueError("asset_changed_during_inspection")
        directory_states[directory.relative_to(root).as_posix()] = _asset_state(directory_info)
        for child in directories:
            if _is_unsafe_asset_link(directory / child):
                raise ValueError("asset_symlink_not_allowed")
        for filename in filenames:
            path = directory / filename
            initial = path.lstat()
            if _is_unsafe_asset_link(path, initial):
                raise ValueError("asset_symlink_not_allowed")
            if not stat.S_ISREG(initial.st_mode):
                raise ValueError("asset_not_regular_file")
            # Open the checked path rather than following a symlink introduced
            # after lstat. Windows lacks O_NOFOLLOW, so the descriptor/path
            # identity and type comparisons below are mandatory there.
            flags = (
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            try:
                descriptor = os.open(path, flags)
            except OSError as exc:
                if path.is_symlink():
                    raise ValueError("asset_symlink_not_allowed") from exc
                raise ValueError("asset_changed_during_inspection") from exc
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or _is_unsafe_asset_link(path, opened)
                    or _asset_handle_state(opened) != _asset_handle_state(initial)
                ):
                    raise ValueError(
                        "asset_changed_during_inspection:" + _asset_mismatch_fields(initial, opened)
                    )
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                end_opened = os.fstat(stream.fileno())
            final = path.lstat()
            if (
                not stat.S_ISREG(final.st_mode)
                or _is_unsafe_asset_link(path, final)
                or _asset_handle_state(initial) != _asset_handle_state(end_opened)
                or _asset_state(initial) != _asset_state(final)
                or _asset_state(opened) != _asset_state(end_opened)
            ):
                raise ValueError(
                    "asset_changed_during_inspection:"
                    + _asset_mismatch_fields(initial, end_opened)
                    + ":"
                    + _asset_mismatch_fields(initial, final)
                    + ":"
                    + _asset_mismatch_fields(opened, end_opened)
                )
            relative_path = path.relative_to(root).as_posix()
            inventory[relative_path] = digest.hexdigest()
            file_states[relative_path] = _asset_state(final)
            if final.st_ino:
                file_identities.add((final.st_dev, final.st_ino))
    return inventory, file_identities, file_states, directory_states


def _assert_asset_tree_unchanged(
    root: Path,
    initial_states: dict[str, tuple[int, ...]],
    initial_directories: dict[str, tuple[int, ...]],
) -> None:
    """Reject a source or candidate tree changed after its hashing pass."""
    if _is_unsafe_asset_link(root) or not root.is_dir():
        raise ValueError("asset_changed_after_inventory")

    def _on_walk_error(exc: OSError) -> None:
        raise ValueError("asset_changed_after_inventory") from exc

    observed: set[str] = set()
    observed_directories: set[str] = set()
    for parent, directories, filenames in os.walk(
        root, topdown=True, followlinks=False, onerror=_on_walk_error
    ):
        directory = Path(parent)
        directory_info = directory.lstat()
        if _is_unsafe_asset_link(directory, directory_info):
            raise ValueError("asset_symlink_not_allowed")
        directory_key = directory.relative_to(root).as_posix()
        if not stat.S_ISDIR(directory_info.st_mode) or initial_directories.get(
            directory_key
        ) != _asset_state(directory_info):
            raise ValueError("asset_changed_after_inventory")
        observed_directories.add(directory_key)
        for child in directories:
            if _is_unsafe_asset_link(directory / child):
                raise ValueError("asset_symlink_not_allowed")
        for filename in filenames:
            path = directory / filename
            info = path.lstat()
            if _is_unsafe_asset_link(path, info):
                raise ValueError("asset_symlink_not_allowed")
            relative_path = path.relative_to(root).as_posix()
            if not stat.S_ISREG(info.st_mode) or initial_states.get(relative_path) != _asset_state(
                info
            ):
                raise ValueError("asset_changed_after_inventory")
            observed.add(relative_path)
    if observed != initial_states.keys() or observed_directories != initial_directories.keys():
        raise ValueError("asset_changed_after_inventory")


def _compare_assets(before_root: Path, after_root: Path) -> dict:
    """Require each original asset at the same relative path with equal bytes."""
    if _is_unsafe_asset_link(before_root) or _is_unsafe_asset_link(after_root):
        raise ValueError("asset_symlink_not_allowed")
    if not before_root.is_dir() or not after_root.is_dir():
        raise ValueError("invalid_asset_root")
    before_real, after_real = before_root.resolve(), after_root.resolve()
    if (
        before_real == after_real
        or before_real in after_real.parents
        or after_real in before_real.parents
    ):
        raise ValueError("asset_roots_must_be_independent")
    baseline, baseline_ids, baseline_states, baseline_dirs = _asset_inventory(before_root)
    if not baseline:
        raise ValueError("no_research_assets_in_baseline")
    candidate, candidate_ids, candidate_states, candidate_dirs = _asset_inventory(after_root)
    # A baseline file can be rewritten while the candidate is being hashed.
    # Check both trees once more before allowing even a preservation-only PASS.
    # This is a bounded mutation detector, not a filesystem snapshot.
    _assert_asset_tree_unchanged(before_root, baseline_states, baseline_dirs)
    _assert_asset_tree_unchanged(after_root, candidate_states, candidate_dirs)
    if baseline_ids & candidate_ids:
        raise ValueError("asset_copies_share_hardlinks")
    # Distinct roots can still contain hardlinks to a THIRD directory. A later
    # edit through that undisclosed alias would change supposedly independent
    # original or candidate data. Require a single filesystem link per file;
    # link-count changes during either scan are caught by _asset_state.
    if any(
        state[-1] != 1
        for states in (baseline_states, candidate_states)
        for state in states.values()
    ):
        raise ValueError("asset_hardlinks_not_independent")
    missing = sum(path not in candidate for path in baseline)
    changed = sum(
        path in candidate and candidate[path] != checksum for path, checksum in baseline.items()
    )
    added = sum(path not in baseline for path in candidate)
    return {
        "checked": True,
        "baseline_files": len(baseline),
        "candidate_files": len(candidate),
        "missing_files": missing,
        "changed_files": changed,
        "added_files": added,
    }


def verify(
    before: Path,
    after: Path,
    before_assets: Path | None = None,
    after_assets: Path | None = None,
) -> dict:
    """Produce only diagnostic digests/counts; never return research row values."""
    if (before_assets is None) != (after_assets is None):
        raise ValueError("asset_roots_must_be_supplied_together")
    before = before.resolve()
    after = after.resolve()
    if before == after or (before.is_file() and after.is_file() and before.samefile(after)):
        raise ValueError("inputs_must_be_independent_database_copies")
    sidecars_before = _sidecars(before) or _sidecars(after)
    with ExitStack() as stack:
        old = _open_snapshot(before, stack)
        new = _open_snapshot(after, stack)
        old_sequences = _protected_autoincrement_sequences(old)
        new_sequences = _protected_autoincrement_sequences(new)
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
                elif _table_storage_contract(old, table) != _table_storage_contract(new, table):
                    item["status"] = "changed_table_storage_contract"
                elif _column_contracts(old, table) != {
                    name: contract
                    for name, contract in _column_contracts(new, table).items()
                    if name in old_columns
                }:
                    # Do not disclose SQL defaults or row values in the report.
                    item["status"] = "changed_column_contract"
                elif not _foreign_key_contracts(old, table).issubset(
                    _foreign_key_contracts(new, table)
                ):
                    item["status"] = "changed_foreign_key_contract"
                elif not _unique_index_contracts(old, table).issubset(
                    _unique_index_contracts(new, table)
                ):
                    item["status"] = "changed_unique_index_contract"
                elif not _check_constraint_contracts(old, table).issubset(
                    _check_constraint_contracts(new, table)
                ):
                    item["status"] = "changed_check_constraint_contract"
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
            # The 1.6 reviewer-history API interprets SQLite rowid as the
            # append chronology for assignment/unassignment, including clock
            # rollbacks. Rebuilding a UUID-primary-key table can preserve all
            # logical row values while changing that chronology. Inspect the
            # id -> rowid mapping, never disclosing individual reviewer IDs.
            if table == "review_queue_item_events" and item["status"] == "preserved":
                # A new explicitly named rowid/_rowid_/oid column would shadow
                # the SQLite pseudocolumn and make this evidence ambiguous.
                aliases = {"rowid", "_rowid_", "oid"}
                if any(column.lower() in aliases for column in (*old_columns, *new_columns)):
                    item["status"] = "ambiguous_review_event_rowid"
                else:
                    _, old_order_sha = _fingerprint(old, table, ["id", "rowid"], ["id"])
                    _, new_order_sha = _fingerprint(new, table, ["id", "rowid"], ["id"])
                    if old_order_sha != new_order_sha:
                        item["status"] = "changed_review_event_append_order"
            # AUTOINCREMENT history affects identifiers of future observations,
            # even when all current protected rows are byte-for-byte unchanged.
            # Do not print the source/candidate sequence numbers or IDs.
            if item["status"] == "preserved" and old_sequences.get(table, []) != new_sequences.get(
                table, []
            ):
                item["status"] = "changed_autoincrement_sequence"
            if item["status"] != "preserved":
                problems.append(table + ":" + item["status"])
            tables.append(item)
        if covered == 0:
            problems.append("no_protected_baseline_tables")
        asset_evidence = {"checked": False}
        if before_assets is not None and after_assets is not None:
            asset_evidence = _compare_assets(before_assets, after_assets)
            if asset_evidence["missing_files"]:
                problems.append("research_assets_missing")
            if asset_evidence["changed_files"]:
                problems.append("research_assets_changed")
        # Sidecars can appear or disappear while reading a WAL database. Even
        # successful snapshots are not approval to copy a live DB's main file.
        if sidecars_before or _sidecars(before) or _sidecars(after):
            problems.append("mutable_sqlite_sidecar_detected")
        return {
            "status": "HOLD" if problems else "PASS_PRESERVATION_ONLY",
            "upgrade_authorized": False,
            "requires_researcher_approval": True,
            "protected_tables_examined": covered,
            "research_assets": asset_evidence,
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
    parser.add_argument(
        "--before-assets", type=Path, help="Original offline research media/model directory"
    )
    parser.add_argument(
        "--after-assets", type=Path, help="Candidate upgraded research media/model directory"
    )
    args = parser.parse_args()
    try:
        report = verify(args.before, args.after, args.before_assets, args.after_assets)
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

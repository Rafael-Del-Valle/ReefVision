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


def _sidecar_presence(database: Path) -> dict[str, bool]:
    """Check SQLite sidecars without opening, modifying, or removing them."""
    return {suffix: Path(f"{database}{suffix}").exists() for suffix in ("-wal", "-shm", "-journal")}


def _database_stat_signature(database: Path) -> tuple[int, int, int, int, int] | None:
    """Observe file identity and metadata without reading or modifying research bytes.

    Matching observations do not prove an immutable backup; a separate verified
    quiescent snapshot remains mandatory for installation or migration acceptance.
    """
    try:
        stat = database.stat()
    except OSError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


FAMILIES = {
    "scientific": (
        "scientific_records",
        "environmental_cache_entries",
        "computed_metric_definitions",
        "computed_metric_results",
    ),
    "qc": ("review_queue_item_events", "review_queue_bulk_requests"),
}


# The two independent revision-0038 migrations create distinct table families. This
# optional read-only structural audit checks their declared SQLite column types and DDL shapes
# to help a researcher assess provenance, not to authorize a migration.
# The 1.1 environmental 0040/0042 contracts are also audited below. The
# scientific metric tables and QC registry still require separate reconciliation.
_POST_0037_TABLE_CONTRACTS = {
    "scientific_records": {
        "columns": frozenset(
            {
                "id",
                "project_id",
                "variable",
                "source_kind",
                "observed_at",
                "image_id",
                "video_id",
                "track_id",
                "model_run_id",
                "payload_json",
                "content_sha256",
                "created_at",
            }
        ),
        "types": {
            "id": "VARCHAR(36)",
            "project_id": "VARCHAR(36)",
            "variable": "VARCHAR(100)",
            "source_kind": "VARCHAR(30)",
            "observed_at": "DATETIME",
            "image_id": "VARCHAR(36)",
            "video_id": "VARCHAR(36)",
            "track_id": "VARCHAR(36)",
            "model_run_id": "VARCHAR(36)",
            "payload_json": "JSON",
            "content_sha256": "VARCHAR(64)",
            "created_at": "DATETIME",
        },
        "required": frozenset(
            {
                "id",
                "project_id",
                "variable",
                "source_kind",
                "observed_at",
                "payload_json",
                "content_sha256",
                "created_at",
            }
        ),
        "foreign_keys": frozenset(
            {
                ("project_id", "projects", "id", "CASCADE"),
                ("image_id", "images", "id", "RESTRICT"),
                ("video_id", "videos", "id", "RESTRICT"),
                ("track_id", "video_tracks", "id", "RESTRICT"),
                ("model_run_id", "jobs", "id", "RESTRICT"),
            }
        ),
        "indexes": frozenset(
            {
                (("project_id", "variable", "observed_at"), False),
            }
        ),
    },
    "environmental_cache_entries": {
        "columns": frozenset(
            {
                "id",
                "project_id",
                "cache_key",
                "source_url",
                "payload_json",
                "content_sha256",
                "fetched_at",
                "expires_at",
            }
        ),
        "types": {
            "id": "VARCHAR(36)",
            "project_id": "VARCHAR(36)",
            "cache_key": "VARCHAR(64)",
            "source_url": "VARCHAR(2000)",
            "payload_json": "JSON",
            "content_sha256": "VARCHAR(64)",
            "fetched_at": "DATETIME",
            "expires_at": "DATETIME",
        },
        "required": frozenset(
            {
                "id",
                "project_id",
                "cache_key",
                "source_url",
                "payload_json",
                "content_sha256",
                "fetched_at",
                "expires_at",
            }
        ),
        "foreign_keys": frozenset({("project_id", "projects", "id", "CASCADE")}),
        "indexes": frozenset({(("project_id", "cache_key"), True)}),
    },
    "environmental_event_definitions": {
        "columns": frozenset(
            {
                "id",
                "project_id",
                "name",
                "query_json",
                "definition_sha256",
                "created_at",
            }
        ),
        "types": {
            "id": "VARCHAR(36)",
            "project_id": "VARCHAR(36)",
            "name": "VARCHAR(200)",
            "query_json": "JSON",
            "definition_sha256": "VARCHAR(64)",
            "created_at": "DATETIME",
        },
        "required": frozenset(
            {
                "id",
                "project_id",
                "name",
                "query_json",
                "definition_sha256",
                "created_at",
            }
        ),
        "foreign_keys": frozenset({("project_id", "projects", "id", "CASCADE")}),
        "indexes": frozenset(
            {
                (("project_id", "created_at"), False),
            }
        ),
    },
    "environmental_analysis_definitions": {
        "columns": frozenset(
            {
                "id",
                "project_id",
                "analysis_kind",
                "name",
                "configuration_json",
                "calculation_version",
                "definition_sha256",
                "created_at",
            }
        ),
        "types": {
            "id": "VARCHAR(36)",
            "project_id": "VARCHAR(36)",
            "analysis_kind": "VARCHAR(50)",
            "name": "VARCHAR(200)",
            "configuration_json": "JSON",
            "calculation_version": "VARCHAR(100)",
            "definition_sha256": "VARCHAR(64)",
            "created_at": "DATETIME",
        },
        "required": frozenset(
            {
                "id",
                "project_id",
                "analysis_kind",
                "name",
                "configuration_json",
                "calculation_version",
                "definition_sha256",
                "created_at",
            }
        ),
        "foreign_keys": frozenset({("project_id", "projects", "id", "CASCADE")}),
        "indexes": frozenset(
            {
                (("project_id", "analysis_kind", "created_at"), False),
            }
        ),
    },
    "environmental_analysis_results": {
        "columns": frozenset(
            {
                "id",
                "project_id",
                "definition_id",
                "analysis_kind",
                "observed_at",
                "payload_json",
                "input_snapshot_json",
                "source_record_ids_json",
                "source_analysis_result_ids_json",
                "quality_control_json",
                "uncertainty_json",
                "content_sha256",
                "workflow_run_id",
                "workflow_node_run_id",
                "created_at",
            }
        ),
        "types": {
            "id": "VARCHAR(36)",
            "project_id": "VARCHAR(36)",
            "definition_id": "VARCHAR(36)",
            "analysis_kind": "VARCHAR(50)",
            "observed_at": "DATETIME",
            "payload_json": "JSON",
            "input_snapshot_json": "JSON",
            "source_record_ids_json": "JSON",
            "source_analysis_result_ids_json": "JSON",
            "quality_control_json": "JSON",
            "uncertainty_json": "JSON",
            "content_sha256": "VARCHAR(64)",
            "workflow_run_id": "VARCHAR(36)",
            "workflow_node_run_id": "VARCHAR(36)",
            "created_at": "DATETIME",
        },
        "required": frozenset(
            {
                "id",
                "project_id",
                "definition_id",
                "analysis_kind",
                "observed_at",
                "payload_json",
                "input_snapshot_json",
                "source_record_ids_json",
                "source_analysis_result_ids_json",
                "quality_control_json",
                "content_sha256",
                "created_at",
            }
        ),
        "foreign_keys": frozenset(
            {
                ("project_id", "projects", "id", "CASCADE"),
                ("definition_id", "environmental_analysis_definitions", "id", "RESTRICT"),
                ("workflow_run_id", "workflow_runs", "id", "RESTRICT"),
                ("workflow_node_run_id", "workflow_node_runs", "id", "RESTRICT"),
            }
        ),
        "indexes": frozenset(
            {
                (("project_id", "analysis_kind", "created_at"), False),
                (("definition_id", "created_at"), False),
                (("workflow_node_run_id",), True),
            }
        ),
    },
    "review_queue_item_events": {
        "columns": frozenset(
            {
                "id",
                "review_queue_id",
                "review_queue_item_id",
                "project_id",
                "client_request_id",
                "event_type",
                "actor",
                "comment",
                "assignee",
                "created_at",
            }
        ),
        "types": {
            "id": "VARCHAR(36)",
            "review_queue_id": "VARCHAR(36)",
            "review_queue_item_id": "VARCHAR(36)",
            "project_id": "VARCHAR(36)",
            "client_request_id": "VARCHAR(36)",
            "event_type": "VARCHAR(20)",
            "actor": "VARCHAR(100)",
            "comment": "TEXT",
            "assignee": "VARCHAR(100)",
            "created_at": "DATETIME",
        },
        "required": frozenset(
            {
                "id",
                "review_queue_id",
                "review_queue_item_id",
                "project_id",
                "client_request_id",
                "event_type",
                "actor",
                "created_at",
            }
        ),
        "foreign_keys": frozenset(
            {
                ("review_queue_id", "review_queues", "id", "CASCADE"),
                ("review_queue_item_id", "review_queue_items", "id", "CASCADE"),
                ("project_id", "projects", "id", "CASCADE"),
            }
        ),
        "indexes": frozenset(
            {
                (("review_queue_item_id", "client_request_id"), True),
                (("review_queue_item_id", "created_at"), False),
                (("review_queue_id", "created_at"), False),
            }
        ),
    },
}

# Preserve named lookup indexes as well as their key columns. The original
# 1.1/1.6 migrations explicitly create and later drop these indexes by name;
# a renamed replacement can satisfy a column-only check yet fail an upgrade
# or downgrade after researcher data has been copied. SQLite UNIQUE
# constraints generate internal autoindexes, whose names are not stable.
_POST_0037_NAMED_LOOKUP_INDEXES = {
    "scientific_records": {
        "ix_scientific_project_variable_time": ("project_id", "variable", "observed_at"),
    },
    "environmental_cache_entries": {},
    "environmental_event_definitions": {
        "ix_environmental_event_definition_project": ("project_id", "created_at"),
    },
    "environmental_analysis_definitions": {
        "ix_environmental_analysis_definition_project_kind": (
            "project_id",
            "analysis_kind",
            "created_at",
        ),
    },
    "environmental_analysis_results": {
        "ix_environmental_analysis_result_project_kind": (
            "project_id",
            "analysis_kind",
            "created_at",
        ),
        "ix_environmental_analysis_result_definition": ("definition_id", "created_at"),
    },
    "review_queue_item_events": {
        "ix_review_queue_item_events_item_created": ("review_queue_item_id", "created_at"),
        "ix_review_queue_item_events_queue_created": ("review_queue_id", "created_at"),
    },
}


def _sqlite_schema_tokens(ddl: str) -> tuple[str, ...] | None:
    """Lex table DDL while preserving SQL literal values and ignoring comments.

    SQLite has no CHECK-constraint PRAGMA. This deliberately conservative
    parser is only used to reject drift, never to authorize a migration.
    """
    tokens: list[str] = []
    cursor = 0
    while cursor < len(ddl):
        char = ddl[cursor]
        if char.isspace():
            cursor += 1
            continue
        if ddl.startswith("--", cursor):
            end = ddl.find("\n", cursor + 2)
            cursor = len(ddl) if end < 0 else end + 1
            continue
        if ddl.startswith("/*", cursor):
            end = ddl.find("*/", cursor + 2)
            if end < 0:
                return None
            cursor = end + 2
            continue
        if char in ("'", '"', "`", "["):
            closer = "]" if char == "[" else char
            cursor += 1
            payload: list[str] = []
            while cursor < len(ddl):
                if ddl[cursor] == closer:
                    if cursor + 1 < len(ddl) and ddl[cursor + 1] == closer:
                        payload.append(closer)
                        cursor += 2
                        continue
                    cursor += 1
                    break
                payload.append(ddl[cursor])
                cursor += 1
            else:
                return None
            value = "".join(payload)
            tokens.append("'" + value + "'" if char == "'" else value.upper())
            continue
        if char.isalnum() or char in "_$":
            end = cursor + 1
            while end < len(ddl) and (ddl[end].isalnum() or ddl[end] in "_$"):
                end += 1
            tokens.append(ddl[cursor:end].upper())
            cursor = end
            continue
        tokens.append(char)
        cursor += 1
    return tuple(tokens)


def _original_0038_check_contract_matches(
    table: str, ddl: str, revision: str | None = None
) -> bool:
    """Reject changed QC event vocabularies and unexpected scientific CHECKs.

    The QC constraint was intentionally expanded in revisions 0039 and 0040.
    Require the exact historical vocabulary for a known QC revision.
    This does NOT prove the correct revision was actually applied.
    """
    tokens = _sqlite_schema_tokens(ddl)
    if not tokens:
        return False
    # PRAGMA foreign_key_list reports target/action but not whether an FK is
    # DEFERRABLE. The source 0038 migrations require immediate enforcement;
    # deferring an observation or review-parent check changes transaction
    # semantics while the reported FK columns and actions still match.
    if any(token in {"DEFERRABLE", "INITIALLY", "DEFERRED"} for token in tokens):
        return False
    # WITHOUT ROWID changes SQLite primary-key/row storage semantics but can
    # leave table_xinfo, index_list and foreign_key_list superficially identical.
    if any(tokens[i : i + 2] == ("WITHOUT", "ROWID") for i in range(len(tokens) - 1)):
        return False
    # These source migrations declare no table-level collation overrides or
    # alternate SQLite constraint conflict actions. Both could silently alter
    # future reviewer events or biological observations.
    if "COLLATE" in tokens or any(
        tokens[i : i + 2] == ("ON", "CONFLICT") for i in range(len(tokens) - 1)
    ):
        return False
    checks = [i for i, token in enumerate(tokens) if token == "CHECK"]
    if table != "review_queue_item_events":
        return not checks
    if len(checks) != 1 or checks[0] < 2:
        return False
    # 0038 -> 0039 -> 0040/0041; never accept an arbitrary extra category,
    # a missing constraint or a second constraint suppressing valid events.
    histories = (
        ("comment", "assign", "unassign"),
        (
            "comment",
            "assign",
            "unassign",
            "triage_start",
            "triage_skip",
            "triage_return",
        ),
        (
            "comment",
            "assign",
            "unassign",
            "triage_start",
            "triage_skip",
            "triage_return",
            "triage_complete",
        ),
    )
    start = (
        "CONSTRAINT",
        "CK_REVIEW_QUEUE_ITEM_EVENT_TYPE",
        "CHECK",
        "(",
        "EVENT_TYPE",
        "IN",
        "(",
    )
    stage = {"0038": 0, "0039": 1, "0040": 2, "0041": 2}.get(revision)
    if stage is not None:
        histories = (histories[stage],)
    for history in histories:
        values: list[str] = []
        for event in history:
            if values:
                values.append(",")
            values.append(f"'{event}'")
        expected = start + tuple(values) + (")", ")")
        if tokens[checks[0] - 2 : checks[0] - 2 + len(expected)] == expected:
            return True
    return False


def _post_0037_table_contract_matches(
    db: sqlite3.Connection, table: str, revision: str | None = None
) -> bool:
    """Check fixed migration DDL without exposing SQL, identities or row data.

    Structural equivalence is NOT proof of a migration's provenance, safety
    for upgrade, or an immutable backup. Only an integrated reviewed lineage
    and data-preserving migration acceptance can resolve the revision conflict.
    """
    contract = _POST_0037_TABLE_CONTRACTS[table]
    # Neither verified revision-0038 source migration declares table triggers.
    # Extra AFTER/BEFORE/INSTEAD OF triggers can change future scientific
    # records or reviewer events while every column, FK and index still
    # matches. Fail closed without reading/reporting potentially private SQL.
    if (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'trigger' "
            "AND tbl_name = ? COLLATE NOCASE LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    ):
        return False
    # table_xinfo, foreign_key_list and index_list cannot reveal CHECK clauses
    # or nonindexed column collations. Compare only known source constraints.
    ddl_row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ? COLLATE NOCASE",
        (table,),
    ).fetchone()
    if ddl_row is None or not isinstance(ddl_row[0], str):
        return False
    if not _original_0038_check_contract_matches(table, ddl_row[0], revision):
        return False
    quoted = '"' + table.replace('"', '""') + '"'
    columns = list(db.execute(f"PRAGMA table_xinfo({quoted})"))
    by_name = {row[1]: row for row in columns}
    declared_types = {name: " ".join(str(row[2]).upper().split()) for name, row in by_name.items()}
    if (
        set(by_name) != contract["columns"]
        or declared_types != contract["types"]
        or any(row[6] != 0 for row in columns)
        # A new NOT NULL on an originally nullable observation or review field
        # can reject legitimate future data; making a required field nullable
        # can admit unattributed evidence. Check the complete original contract.
        or any(bool(row[3]) != (name in contract["required"]) for name, row in by_name.items())
        # Neither source 0038 table declares column defaults. Injected defaults
        # can fabricate future measurements or reviewer attribution while all
        # current rows and indices remain unchanged.
        or any(row[4] is not None for row in columns)
        or [row[1] for row in columns if row[5] > 0] != ["id"]
    ):
        return False

    foreign_key_rows = list(db.execute(f"PRAGMA foreign_key_list({quoted})"))
    # Both source migrations declare only single-column foreign keys.
    if any(row[1] != 0 for row in foreign_key_rows):
        return False
    foreign_keys = {(row[3], row[2], row[4], row[6].upper()) for row in foreign_key_rows}
    if foreign_keys != contract["foreign_keys"]:
        return False
    # The source migrations do not declare ON UPDATE actions. CASCADE or
    # SET NULL could silently alter biological links or reviewer ownership
    # after a parent ID changes, even when ON DELETE and FK targets match.
    if any(row[5].upper() != "NO ACTION" for row in foreign_key_rows):
        return False

    canonical_indexes = set()
    named_lookup_indexes = {}
    nonprimary_unique_indexes = set()
    has_partial_unique = False
    has_noncanonical_unique_keys = False
    for index in db.execute(f"PRAGMA index_list({quoted})"):
        index_name = '"' + index[1].replace('"', '""') + '"'
        columns_in_index = tuple(row[2] for row in db.execute(f"PRAGMA index_info({index_name})"))
        # SQLite's index_info hides sort order and collation, while
        # index_list reports partial indexes separately. All required source
        # indexes (including non-UNIQUE time lookups) are full, ascending and
        # BINARY. A partial or NOCASE lookup with the right column names is
        # not migration-equivalent, and may omit or reorder observations.
        key_rows = [row for row in db.execute(f"PRAGMA index_xinfo({index_name})") if row[5]]
        canonical_keys = len(key_rows) == len(columns_in_index) and all(
            row[3] == 0 and row[4] == "BINARY" for row in key_rows
        )
        if canonical_keys and not index[4]:
            canonical_indexes.add((columns_in_index, bool(index[2])))
        if index[3] == "c" and not index[2]:
            # A structurally equivalent but renamed CREATE INDEX is not the
            # source migration's index. Future op.drop_index uses its name.
            named_lookup_indexes[index[1]] = (columns_in_index, canonical_keys and not index[4])
        if index[2] and not canonical_keys:
            # A forged UNIQUE key may collapse distinct researcher request IDs.
            has_noncanonical_unique_keys = True
        if index[2] and index[3] != "pk":
            # A partial replacement of the QC idempotency constraint can
            # admit duplicate review requests for excluded researchers.
            # Unexpected UNIQUE indexes can also prevent otherwise valid
            # biological observations or reviewer events. Require review.
            nonprimary_unique_indexes.add(columns_in_index)
            has_partial_unique |= bool(index[4])
            # Source request/cache uniqueness is a table UNIQUE constraint
            # (origin 'u'), not a manually created index (origin 'c').
            # That distinction is required for compatible batch migrations.
            if index[3] != "u":
                has_noncanonical_unique_keys = True
    required_unique_indexes = {columns for columns, unique in contract["indexes"] if unique}
    return (
        contract["indexes"] <= canonical_indexes
        and not has_partial_unique
        and not has_noncanonical_unique_keys
        and nonprimary_unique_indexes == required_unique_indexes
        and all(
            named_lookup_indexes.get(name) == (columns, True)
            for name, columns in _POST_0037_NAMED_LOOKUP_INDEXES[table].items()
        )
    )


def _annotation_aggregate_column_contract_matches(db: sqlite3.Connection) -> bool:
    """Compare the original 1.1 revision 0041 added-column contracts."""
    expected_contracts = {
        "computed_metric_definitions": {
            "definition_kind": ("VARCHAR(40)", 1, "'scalar'", 0, 0),
            "configuration_json": ("JSON", 0, None, 0, 0),
        },
        "computed_metric_results": {
            "result_kind": ("VARCHAR(40)", 1, "'scalar'", 0, 0),
        },
    }
    for table, expected in expected_contracts.items():
        actual = {
            row[1]: (str(row[2]).upper(), *row[3:7])
            for row in db.execute(f'PRAGMA table_xinfo("{table}")')
        }
        if any(actual.get(name) != contract for name, contract in expected.items()):
            return False
    return True


def inspect(path: Path, *, verify_structural_contracts: bool = False) -> dict:
    if not path.is_file():
        raise ValueError(f"Database file does not exist: {path}")
    # SQLite URI read-only mode prevents accidental creation of missing databases.
    resolved_path = path.resolve()
    database_stat_before = _database_stat_signature(resolved_path)
    sidecars_before = _sidecar_presence(resolved_path)
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
        noncanonical_version_object = any(
            name.isascii()
            and name.lower() == "alembic_version"
            and (name != "alembic_version" or kind != "table")
            for name, kind in objects.items()
        )
        # table_info hides SQLite generated and virtual-table hidden columns.
        # Use xinfo so a forged Alembic table cannot pass as single-column
        # canonical merely because its extra columns are hidden from table_info.
        # Alembic UPDATE/INSERT/DELETE may execute arbitrary SQLite triggers
        # attached to the revision table. Count them without exposing SQL or
        # trigger names (which may themselves contain private research terms).
        version_trigger_count = (
            db.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = 'alembic_version' COLLATE NOCASE"
            ).fetchone()[0]
            if version_table_present
            else 0
        )
        version_has_foreign_keys = (
            db.execute(
                "SELECT 1 FROM sqlite_master AS objects "
                "JOIN pragma_foreign_key_list(objects.name) AS links "
                "WHERE objects.type = 'table' AND ("
                "objects.name = 'alembic_version' COLLATE NOCASE OR "
                "links.\"table\" = 'alembic_version' COLLATE NOCASE) LIMIT 1"
            ).fetchone()
            is not None
            if version_table_present
            else False
        )
        version_table_info = (
            list(db.execute('PRAGMA table_xinfo("alembic_version")'))
            if version_table_present
            else []
        )
        version_columns = {row[1] for row in version_table_info}
        # A canonical Alembic stamp has precisely one ordinary, non-null
        # text primary-key column. A plausible revision string is not enough.
        canonical_stamp_constraints = (
            len(version_table_info) == 1
            and version_table_info[0][1] == "version_num"
            and str(version_table_info[0][2]).upper() in {"VARCHAR(32)", "VARCHAR", "TEXT"}
            and version_table_info[0][3] == 1
            and version_table_info[0][5] == 1
            and version_table_info[0][6] == 0
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
        # SQLite identifiers are ASCII case-insensitive even though sqlite_master
        # preserves their spelling. Report case-variant tables as present, and
        # reject aliases or views occupying reserved scientific/QC table names.
        lineage_objects = {
            name.lower(): kind
            for name, kind in objects.items()
            if name.isascii() and name.lower() in names
        }
        noncanonical_lineage_object = any(
            name.isascii() and name.lower() in names and (name not in names or kind != "table")
            for name, kind in objects.items()
        )
        for name in sorted(names):
            if lineage_objects.get(name) != "table":
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
        structural_contracts = {}
        revision = revisions[0] if len(revisions) == 1 and isinstance(revisions[0], str) else None
        if verify_structural_contracts:
            for table in _POST_0037_TABLE_CONTRACTS:
                if lineage_objects.get(table) != "table":
                    structural_contracts[table] = "absent"
                elif _post_0037_table_contract_matches(db, table, revision):
                    structural_contracts[table] = "matches"
                else:
                    structural_contracts[table] = "mismatch"
        warnings = []
        if noncanonical_lineage_object:
            warnings.append("noncanonical_lineage_schema_object")
        if noncanonical_version_object:
            warnings.append("noncanonical_alembic_version_object")
        for table, outcome in structural_contracts.items():
            if outcome == "mismatch":
                warnings.append(f"lineage_table_contract_mismatch_{table}")
        if not integrity_ok:
            warnings.append("sqlite_integrity_check_failed")
        if not full_integrity_ok:
            warnings.append("sqlite_full_integrity_check_failed")
        if foreign_key_check_error is not None:
            warnings.append("sqlite_foreign_key_check_failed")
        elif foreign_key_violations:
            warnings.append("sqlite_foreign_key_violations")
        # A SQLite writer may checkpoint and remove a WAL or journal while
        # read-only evidence is collected. Observe sidecars at both boundaries:
        # a clean end state does not prove the original file was immutable.
        sidecars_after = _sidecar_presence(resolved_path)
        database_stat_after = _database_stat_signature(resolved_path)
        # A writer can also replace or change the main SQLite file during a
        # lengthy integrity/lineage report, even if no sidecar exists at either
        # boundary. This is only a fail-closed metadata probe, not a proof of
        # immutability or a substitute for a verified offline snapshot.
        database_stat_observations_match = (
            database_stat_before is not None
            and database_stat_after is not None
            and database_stat_before == database_stat_after
        )
        if not database_stat_observations_match:
            warnings.append("database_file_changed_during_inspection")
        for suffix, warning in (
            ("-wal", "wal_sidecar_requires_consistent_snapshot"),
            ("-shm", "shared_memory_sidecar_requires_consistent_snapshot"),
            ("-journal", "rollback_journal_requires_consistent_snapshot"),
        ):
            if sidecars_before[suffix] or sidecars_after[suffix]:
                warnings.append(warning)
        if version_trigger_count:
            warnings.append("alembic_version_triggers_require_review")
        if version_has_foreign_keys:
            warnings.append("alembic_version_foreign_keys_require_review")
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
        # The independent scientific branch ends at 0042; QC ends at 0041.
        # Unknown numeric or foreign textual heads cannot establish a later
        # compatible schema. The shared historical mask revision is also too
        # early to contain either of these post-0037 schema families.
        supported_post_review = {"0038", "0039", "0040", "0041"}
        if lineage == "scientific":
            supported_post_review.add("0042")
        if (
            lineage in {"scientific", "qc"}
            and isinstance(stamped_revision, str)
            and stamped_revision not in supported_post_review
            and not (numeric_revision is not None and 1 <= numeric_revision <= 37)
        ):
            warnings.append("revision_not_supported_for_schema_lineage")
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
            if numeric_revision < 38 and any(inventory[name]["present"] for name in science_base):
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
            # 1.1 revision 0041 adds three reviewed-annotation aggregate
            # columns to the earlier scalar metric tables. Table presence
            # alone cannot distinguish an interrupted 0041 migration.
            aggregate_columns = {
                "computed_metric_definitions": {"definition_kind", "configuration_json"},
                "computed_metric_results": {"result_kind"},
            }
            aggregate_columns_present = any(
                columns.intersection(inventory[table].get("columns", ()))
                for table, columns in aggregate_columns.items()
            )
            aggregate_columns_complete = all(
                columns.issubset(inventory[table].get("columns", ()))
                for table, columns in aggregate_columns.items()
            )
            if revision in {"0041", "0042"} and metric_complete and not aggregate_columns_complete:
                warnings.append("scientific_revision_missing_annotation_aggregate_columns")
            if (
                revision in {"0041", "0042"}
                and metric_complete
                and aggregate_columns_complete
                and not _annotation_aggregate_column_contract_matches(db)
            ):
                warnings.append("scientific_annotation_aggregate_column_contract_mismatch")
            if revision in {"0037", "0038", "0039", "0040"} and aggregate_columns_present:
                warnings.append("annotation_aggregate_columns_before_revision_0041")
            # A later scientific stamp also promises that its own DDL exists.
            if revision in {"0039", "0040", "0041", "0042"} and not metric_complete:
                warnings.append("scientific_revision_missing_computed_metric_pair")
            # Earlier stage checks only diagnose tables arriving too soon or
            # missing dependencies of tables that survived a partial restore.
            if (
                revision in {"0040", "0041", "0042"}
                and "environmental_event_definitions" not in present_extensions
            ):
                warnings.append("scientific_revision_missing_environmental_event_definitions")
            if revision == "0042" and not analysis_pair <= present_extensions:
                warnings.append("scientific_revision_missing_environmental_analysis_pair")
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
            "sqlite_sidecars_before": sidecars_before,
            "sqlite_sidecars_after": sidecars_after,
            "sqlite_database_stat_observations_match": database_stat_observations_match,
            "sqlite_integrity_ok": integrity_ok,
            "sqlite_full_integrity_ok": full_integrity_ok,
            "sqlite_foreign_key_violations": foreign_key_violations,
            "sqlite_foreign_key_check_error": foreign_key_check_error,
            # SQLite permits BLOB/INTEGER revision cells despite Alembic expecting TEXT.
            # Keep the report JSON-safe without exposing arbitrary binary payloads.
            "revision_rows": [value if isinstance(value, str) else None for value in revisions],
            "alembic_version_trigger_count": version_trigger_count,
            "alembic_version_has_foreign_keys": version_has_foreign_keys,
            "canonical_alembic_stamp_constraints": canonical_stamp_constraints,
            "lineage_hint": lineage,
            "upgrade_authorized": False,
            "structural_contracts": structural_contracts,
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
    parser.add_argument(
        "--verify-structural-contracts",
        action="store_true",
        help="Read-only selected 1.1/1.6 DDL evidence checks (never authorizes migration)",
    )
    args = parser.parse_args()
    try:
        result = inspect(
            args.database, verify_structural_contracts=args.verify_structural_contracts
        )
    except (sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.fail_on_warning and result["warnings"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

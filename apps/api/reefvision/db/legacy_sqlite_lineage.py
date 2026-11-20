"""Recognize shipped SQLite histories without changing the original database."""

from __future__ import annotations

import json
from collections.abc import Iterable
from uuid import UUID

from alembic.runtime.migration import MigrationContext
from alembic.util import CommandError
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from reefvision.db.legacy_sqlite_fingerprints import (
    BASE_VARIABLE_TABLES,
    COMMON_SHA256,
    REVISION_CHANGES,
)
from reefvision.db.legacy_sqlite_schema import changed_tables, digest, sqlite_table_signatures

VARIABLE_TABLES = set(BASE_VARIABLE_TABLES).union(*(set(v) for v in REVISION_CHANGES.values()))
QC_TABLES = {"review_queue_item_events", "review_queue_bulk_requests"}


def refusal(detail: str) -> CommandError:
    return CommandError(
        f"Cannot determine migration lineage. {detail} "
        "Preserve the original profile. Inspect a disposable copy with its originating build "
        "or restore a verified pre-upgrade backup."
    )


def read_migration_heads(connection: Connection) -> tuple[str, ...]:
    if connection.dialect.name != "sqlite":
        return MigrationContext.configure(connection).get_current_heads()
    objects = connection.exec_driver_sql(
        "SELECT type, name FROM sqlite_master WHERE tbl_name = 'alembic_version' COLLATE NOCASE"
    ).all()
    if objects:
        if not any(t == "table" and name == "alembic_version" for t, name in objects) or any(
            t not in {"index", "table"} for t, _ in objects
        ):
            raise refusal("The migration ledger must be a table without attached triggers.")
        columns = connection.exec_driver_sql("PRAGMA table_xinfo('alembic_version')").all()
        if (
            len(columns) != 1
            or tuple(columns[0][1:]) != ("version_num", "VARCHAR(32)", 1, None, 1, 0)
            or any(
                row[3] != "pk"
                for row in connection.exec_driver_sql("PRAGMA index_list('alembic_version')")
            )
        ):
            raise refusal("The migration ledger has an unexpected column or index definition.")
        heads = tuple(
            row[0] for row in connection.exec_driver_sql("SELECT version_num FROM alembic_version")
        )
        if any(not isinstance(head, str) or not head.strip() for head in heads):
            raise refusal("The migration ledger contains an invalid revision.")
        if heads:
            return heads
    existing = connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' "
        "AND tbl_name != 'alembic_version' LIMIT 1"
    ).first()
    if existing:
        raise refusal("A populated schema has no recorded migration revision.")
    return ()


def _qc_records_are_scoped(connection: Connection, *, bulk: bool) -> bool:
    bad_event = connection.exec_driver_sql(
        "SELECT 1 FROM review_queue_item_events e JOIN review_queue_items i "
        "ON i.id = e.review_queue_item_id JOIN review_queues q ON q.id = e.review_queue_id "
        "WHERE i.review_queue_id != q.id OR i.project_id != e.project_id "
        "OR q.project_id != e.project_id LIMIT 1"
    ).first()
    if bad_event or not bulk:
        return not bad_event
    # JSON arrays in the original 0041 registry are also references. SQLite's
    # foreign_key_check cannot detect a request recording another queue's item.
    requests = connection.exec_driver_sql(
        "SELECT b.id, b.item_ids_json, b.project_id, b.review_queue_id, q.project_id "
        "FROM review_queue_bulk_requests b JOIN review_queues q ON b.review_queue_id=q.id"
    )
    for request, payload, project, queue, owner in requests:
        if not isinstance(request, str) or not isinstance(payload, str):
            return False
        try:
            UUID(request)
            items = json.loads(payload)
            if (
                project != owner
                or not isinstance(items, list)
                or not items
                or len(items) != len(set(items))
                or not all(isinstance(item, str) and str(UUID(item)) == item for item in items)
            ):
                return False
        except (TypeError, ValueError, AttributeError):
            return False
        count: int = connection.exec_driver_sql(
            "SELECT count(*) FROM review_queue_items WHERE review_queue_id=? AND project_id=? "
            "AND id IN (SELECT value FROM json_each(?))",
            (queue, project, payload),
        ).scalar_one()
        if count != len(items):
            return False
    return True


def _check_links(connection: Connection, observed: Iterable[str]) -> None:
    if connection.exec_driver_sql("PRAGMA integrity_check(1)").scalar() != "ok":
        raise refusal("SQLite reported an integrity failure.")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
        raise refusal("The historical database contains an unresolved foreign key.")
    if "review_queue_item_events" in observed and not _qc_records_are_scoped(
        connection, bulk="review_queue_bulk_requests" in observed
    ):
        raise refusal("QC history contains an inconsistent project, queue or item reference.")


def identify_numeric_history(
    connection: Connection, heads: tuple[str, ...], numeric: list[str]
) -> str | None:
    if len(numeric) != 1:
        raise refusal("There are multiple unqualified numeric branches.")
    legacy = numeric[0]
    siblings = [h for h in heads if h != legacy]
    candidates = (
        [legacy]
        if siblings
        else [legacy, f"reviewq_{legacy}", f"reefpose_{legacy}", f"spatial_{legacy}"]
    )
    if any(sibling not in REVISION_CHANGES for sibling in siblings):
        raise refusal("The numeric revision has an unrecognized sibling branch.")
    try:
        actual = sqlite_table_signatures(connection)
        common = {k: v for k, v in actual.items() if k not in VARIABLE_TABLES}
        observed = {k: v for k, v in actual.items() if k in VARIABLE_TABLES}
        if digest(common) != COMMON_SHA256:
            raise refusal("The common schema differs from the shipped historical migrations.")
        for candidate in candidates:
            if candidate not in REVISION_CHANGES:
                continue
            expected = changed_tables(
                BASE_VARIABLE_TABLES, REVISION_CHANGES, [candidate, *siblings]
            )
            if observed == expected:
                _check_links(connection, observed)
                return None if candidate == legacy else candidate
    except (ValueError, SQLAlchemyError) as exc:
        raise refusal("SQLite could not verify the historical schema and its references.") from exc
    raise refusal(
        f"The schema does not match its recorded history at {', '.join(heads)}. "
        "The scientific, QC, pose and spatial migrations require distinct complete fingerprints."
    )


def validate_named_qc_history(connection: Connection, heads: tuple[str, ...]) -> None:
    named = [h for h in heads if h.startswith("reviewq_")]
    if not named:
        return
    if len(named) != 1 or named[0] not in REVISION_CHANGES:
        raise refusal("The explicitly named QC branch is unrecognized.")
    expected = changed_tables({}, REVISION_CHANGES, named)
    try:
        actual = sqlite_table_signatures(connection)
        if {k: actual[k] for k in QC_TABLES if k in actual} != expected:
            raise refusal("The QC schema does not match its recorded revision.")
        _check_links(connection, actual)
    except (ValueError, SQLAlchemyError) as exc:
        raise refusal("The QC schema or its references could not be verified.") from exc

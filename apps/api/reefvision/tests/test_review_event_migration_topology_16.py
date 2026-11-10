"""Verify the original QC event migration's referential and ordering contracts."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
import pytest


def test_review_event_migration_retains_foreign_keys_and_ordering_indexes() -> None:
    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    spec = importlib.util.spec_from_file_location(
        "review_event_migration_0038", versions / "0038_review_queue_item_events.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            for parent in ("projects", "review_queues", "review_queue_items"):
                connection.execute(text(f"CREATE TABLE {parent} (id VARCHAR(36) PRIMARY KEY)"))
            context = MigrationContext.configure(connection)
            operations = Operations(context)
            original_op = module.op
            try:
                module.op = operations
                module.upgrade()
            finally:
                module.op = original_op

            inspector = inspect(connection)
            foreign_keys = {
                (
                    tuple(fk["constrained_columns"]),
                    fk["referred_table"],
                    tuple(fk["referred_columns"]),
                    fk["options"].get("ondelete"),
                )
                for fk in inspector.get_foreign_keys("review_queue_item_events")
            }
            assert foreign_keys == {
                (("review_queue_id",), "review_queues", ("id",), "CASCADE"),
                (("review_queue_item_id",), "review_queue_items", ("id",), "CASCADE"),
                (("project_id",), "projects", ("id",), "CASCADE"),
            }
            indexes = {
                index["name"]: tuple(index["column_names"])
                for index in inspector.get_indexes("review_queue_item_events")
            }
            assert indexes == {
                "ix_review_queue_item_events_item_created": (
                    "review_queue_item_id",
                    "created_at",
                ),
                "ix_review_queue_item_events_queue_created": (
                    "review_queue_id",
                    "created_at",
                ),
            }
    finally:
        engine.dispose()


@pytest.mark.parametrize("parent_to_delete", ["projects", "review_queues", "review_queue_items"])
def test_review_event_migration_enforces_cascading_links_with_foreign_keys_enabled(
    parent_to_delete: str,
) -> None:
    """Each of the three 0038 parent links must reject orphans and cascade deletes."""
    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    spec = importlib.util.spec_from_file_location(
        "review_event_migration_0038_cascade", versions / "0038_review_queue_item_events.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.connect() as connection:
            # SQLite does not enforce declared foreign keys unless explicitly enabled.
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            for parent in ("projects", "review_queues", "review_queue_items"):
                connection.execute(text(f"CREATE TABLE {parent} (id VARCHAR(36) PRIMARY KEY)"))
                connection.execute(text(f"INSERT INTO {parent} (id) VALUES ('parent')"))
            operations = Operations(MigrationContext.configure(connection))
            original_op = module.op
            try:
                module.op = operations
                module.upgrade()
            finally:
                module.op = original_op

            # An invalid relationship must fail before any audit event is recorded.
            event_sql = text(
                "INSERT INTO review_queue_item_events "
                "(id, review_queue_id, review_queue_item_id, project_id, "
                "client_request_id, event_type, actor, created_at) "
                "VALUES (:id, :queue, :item, :project, :request, "
                "'comment', 'researcher', '2026-11-09 12:00:00')"
            )
            # Exercise every foreign-key edge independently. A queue-only
            # orphan check would miss a missing project/item constraint.
            for missing_column in ("queue", "item", "project"):
                values = {
                    "id": f"orphan-{missing_column}",
                    "queue": "parent",
                    "item": "parent",
                    "project": "parent",
                    "request": f"bad-{missing_column}",
                }
                values[missing_column] = "missing"
                with pytest.raises(IntegrityError):
                    connection.execute(event_sql, values)
            assert connection.execute(
                text("SELECT COUNT(*) FROM review_queue_item_events")
            ).scalar_one() == 0
            connection.execute(
                event_sql, {"id": "valid", "queue": "parent", "item": "parent", "project": "parent", "request": "good"}
            )
            assert connection.execute(
                text("SELECT COUNT(*) FROM review_queue_item_events")
            ).scalar_one() == 1
            connection.execute(text(f"DELETE FROM {parent_to_delete} WHERE id='parent'"))
            assert connection.execute(
                text("SELECT COUNT(*) FROM review_queue_item_events")
            ).scalar_one() == 0
    finally:
        engine.dispose()

"""Verify the original QC event migration's referential and ordering contracts."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


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

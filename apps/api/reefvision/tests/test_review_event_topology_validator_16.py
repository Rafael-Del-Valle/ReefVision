"""Standalone read-only checks for QC event foreign keys and ordering indexes."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.review_event_topology_16 import assert_review_event_relationship_topology


@pytest.mark.parametrize(
    "broken",
    [
        "none",
        "missing_fk",
        "wrong_delete",
        "missing_index",
        "reordered_index",
        "wrong_parent",
        "extra_fk",
        "duplicate_fk",
        "extra_index",
        "wrong_index_name",
        "unique_index",
        "partial_index",
        "descending_item_index",
        "descending_queue_index",
    ],
)
def test_review_event_topology_is_read_only_and_fails_closed(broken: str) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            for parent in ("projects", "review_queues", "review_queue_items"):
                connection.execute(text(f"CREATE TABLE {parent} (id TEXT PRIMARY KEY)"))
            delete = "RESTRICT" if broken == "wrong_delete" else "CASCADE"
            item_parent = "review_queues" if broken == "wrong_parent" else "review_queue_items"
            item_fk = (
                ""
                if broken == "missing_fk"
                else (
                    ", FOREIGN KEY (review_queue_item_id) "
                    f"REFERENCES {item_parent}(id) ON DELETE CASCADE"
                )
            )
            extra_fk = (
                ", FOREIGN KEY (created_at) REFERENCES projects(id) ON DELETE CASCADE"
                if broken == "extra_fk"
                else ""
            )
            duplicate_fk = (
                ", FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
                if broken == "duplicate_fk"
                else ""
            )
            connection.execute(
                text(
                    "CREATE TABLE review_queue_item_events ("
                    "id TEXT PRIMARY KEY, review_queue_id TEXT, review_queue_item_id TEXT, "
                    "project_id TEXT, created_at TEXT, "
                    f"FOREIGN KEY (review_queue_id) REFERENCES review_queues(id) ON DELETE {delete}, "
                    "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
                    f"{item_fk}{extra_fk}{duplicate_fk})"
                )
            )
            item_order = (
                "created_at, review_queue_item_id"
                if broken == "reordered_index"
                else (
                    "review_queue_item_id, created_at DESC"
                    if broken == "descending_item_index"
                    else "review_queue_item_id, created_at"
                )
            )
            item_index_name = (
                "ix_review_queue_item_events_item_changed"
                if broken == "wrong_index_name"
                else "ix_review_queue_item_events_item_created"
            )
            connection.execute(
                text(
                    f"CREATE {'UNIQUE ' if broken == 'unique_index' else ''}INDEX "
                    f"{item_index_name} ON review_queue_item_events ({item_order})"
                    + (" WHERE created_at IS NOT NULL" if broken == "partial_index" else "")
                )
            )
            if broken != "missing_index":
                connection.execute(
                    text(
                        "CREATE INDEX ix_review_queue_item_events_queue_created "
                        "ON review_queue_item_events (review_queue_id, created_at DESC)"
                        if broken == "descending_queue_index"
                        else "CREATE INDEX ix_review_queue_item_events_queue_created "
                        "ON review_queue_item_events (review_queue_id, created_at)"
                    )
                )
            if broken == "extra_index":
                connection.execute(
                    text(
                        "CREATE INDEX ix_review_queue_item_events_extra "
                        "ON review_queue_item_events (project_id)"
                    )
                )
            connection.execute(text("CREATE TABLE preserved (observation TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO preserved VALUES ('original research data')"))
            before = connection.scalar(
                text("SELECT sql FROM sqlite_master WHERE name='review_queue_item_events'")
            )
            if broken == "none":
                assert_review_event_relationship_topology(connection)
            else:
                with pytest.raises(RuntimeError, match="topology"):
                    assert_review_event_relationship_topology(connection)
            assert (
                connection.scalar(text("SELECT observation FROM preserved"))
                == "original research data"
            )
            assert (
                connection.scalar(
                    text("SELECT sql FROM sqlite_master WHERE name='review_queue_item_events'")
                )
                == before
            )
    finally:
        engine.dispose()


def test_non_sqlite_composite_foreign_key_rejected_without_querying_rows() -> None:
    """Do not silently discard a malformed multi-column audit relationship."""
    connection = MagicMock()
    connection.dialect.name = "postgresql"
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["review_queue_item_events"]
    inspector.get_foreign_keys.return_value = [
        {
            "constrained_columns": ["review_queue_id", "project_id"],
            "referred_table": "review_queues",
            "referred_columns": ["id", "project_id"],
            "options": {"ondelete": "CASCADE"},
        }
    ]
    with patch("reefvision.db.review_event_topology_16.inspect", return_value=inspector):
        with pytest.raises(RuntimeError, match="composite or incomplete"):
            assert_review_event_relationship_topology(connection)
    connection.execute.assert_not_called()
    inspector.get_indexes.assert_not_called()


@pytest.mark.parametrize("duplicate", ["foreign_key", "index"])
def test_non_sqlite_duplicate_inspection_entries_fail_closed(duplicate: str) -> None:
    """Inspector duplicates must not disappear through dict/set deduplication."""
    connection = MagicMock()
    connection.dialect.name = "postgresql"
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["review_queue_item_events"]
    foreign_keys = [
        {
            "constrained_columns": [column],
            "referred_table": parent,
            "referred_columns": ["id"],
            "options": {"ondelete": "CASCADE"},
        }
        for column, parent in (
            ("review_queue_id", "review_queues"),
            ("review_queue_item_id", "review_queue_items"),
            ("project_id", "projects"),
        )
    ]
    indexes = [
        {
            "name": name,
            "column_names": list(columns),
        }
        for name, columns in (
            ("ix_review_queue_item_events_item_created", ("review_queue_item_id", "created_at")),
            ("ix_review_queue_item_events_queue_created", ("review_queue_id", "created_at")),
        )
    ]
    if duplicate == "foreign_key":
        foreign_keys.append(dict(foreign_keys[0]))
    else:
        indexes.append(dict(indexes[0]))
    inspector.get_foreign_keys.return_value = foreign_keys
    inspector.get_indexes.return_value = indexes
    with patch("reefvision.db.review_event_topology_16.inspect", return_value=inspector):
        with pytest.raises(RuntimeError, match="duplicate"):
            assert_review_event_relationship_topology(connection)
    connection.execute.assert_not_called()
    if duplicate == "foreign_key":
        inspector.get_indexes.assert_not_called()

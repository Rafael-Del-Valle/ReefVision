"""Standalone read-only checks for QC event foreign keys and ordering indexes."""

import pytest
from sqlalchemy import create_engine, text

from reefvision.db.review_event_topology_16 import assert_review_event_relationship_topology


@pytest.mark.parametrize("broken", ["none", "missing_fk", "wrong_delete", "missing_index", "reordered_index"])
def test_review_event_topology_is_read_only_and_fails_closed(broken: str) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            for parent in ("projects", "review_queues", "review_queue_items"):
                connection.execute(text(f"CREATE TABLE {parent} (id TEXT PRIMARY KEY)"))
            delete = "RESTRICT" if broken == "wrong_delete" else "CASCADE"
            item_fk = (
                "" if broken == "missing_fk" else
                ", FOREIGN KEY (review_queue_item_id) REFERENCES review_queue_items(id) ON DELETE CASCADE"
            )
            connection.execute(text(
                "CREATE TABLE review_queue_item_events ("
                "id TEXT PRIMARY KEY, review_queue_id TEXT, review_queue_item_id TEXT, "
                "project_id TEXT, created_at TEXT, "
                f"FOREIGN KEY (review_queue_id) REFERENCES review_queues(id) ON DELETE {delete}, "
                "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
                f"{item_fk})"
            ))
            item_order = (
                "created_at, review_queue_item_id"
                if broken == "reordered_index" else "review_queue_item_id, created_at"
            )
            connection.execute(text(
                "CREATE INDEX ix_review_queue_item_events_item_created "
                f"ON review_queue_item_events ({item_order})"
            ))
            if broken != "missing_index":
                connection.execute(text(
                    "CREATE INDEX ix_review_queue_item_events_queue_created "
                    "ON review_queue_item_events (review_queue_id, created_at)"
                ))
            connection.execute(text("CREATE TABLE preserved (observation TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO preserved VALUES ('original research data')"))
            before = connection.scalar(text(
                "SELECT sql FROM sqlite_master WHERE name='review_queue_item_events'"
            ))
            if broken == "none":
                assert_review_event_relationship_topology(connection)
            else:
                with pytest.raises(RuntimeError, match="topology"):
                    assert_review_event_relationship_topology(connection)
            assert connection.scalar(text("SELECT observation FROM preserved")) == "original research data"
            assert connection.scalar(text(
                "SELECT sql FROM sqlite_master WHERE name='review_queue_item_events'"
            )) == before
    finally:
        engine.dispose()

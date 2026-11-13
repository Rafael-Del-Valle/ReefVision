"""Synthetic QC audit-event relationships matching the real 0038 migration.

Reuse this only in 1.6 SQLite migration/startup regressions. Negative tests
must deliberately corrupt a single contract rather than accidentally omitting
the earlier revision's cascading foreign keys and ordered history indexes.
"""

from sqlalchemy import Connection, text

REVIEW_EVENT_FK_SQL = (
    ", FOREIGN KEY (review_queue_id) REFERENCES review_queues(id) ON DELETE CASCADE"
    ", FOREIGN KEY (review_queue_item_id) REFERENCES review_queue_items(id) ON DELETE CASCADE"
    ", FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
)


def install_review_event_parent_rows(connection: Connection) -> None:
    """Seed minimal parents so synthetic QC audit events have valid provenance."""
    for table, values in (
        ("projects", ("project-1",)),
        ("review_queues", ("queue-1", "queue-2")),
        ("review_queue_items", ("item-1", "item-2")),
    ):
        connection.execute(text(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY)"))
        for value in values:
            connection.execute(
                text(f"INSERT OR IGNORE INTO {table} (id) VALUES (:id)"),
                {"id": value},
            )


def install_review_event_history_indexes(connection: Connection) -> None:
    """Install exactly the ascending, nonunique audit indexes from revision 0038."""
    connection.execute(
        text(
            "CREATE INDEX ix_review_queue_item_events_item_created "
            "ON review_queue_item_events (review_queue_item_id, created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX ix_review_queue_item_events_queue_created "
            "ON review_queue_item_events (review_queue_id, created_at)"
        )
    )

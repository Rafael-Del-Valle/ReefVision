"""Read-only structural contract for the original 0038 QC event relationships.

This helper intentionally does not repair, stamp, or modify research databases.
Callers must first establish that the database belongs to the 1.6 review lineage.
"""

from sqlalchemy import Connection, inspect, text

_EXPECTED_FOREIGN_KEYS = {
    ("review_queue_id", "review_queues", "id", "CASCADE"),
    ("review_queue_item_id", "review_queue_items", "id", "CASCADE"),
    ("project_id", "projects", "id", "CASCADE"),
}
_EXPECTED_INDEXES = {
    "ix_review_queue_item_events_item_created": ("review_queue_item_id", "created_at"),
    "ix_review_queue_item_events_queue_created": ("review_queue_id", "created_at"),
}


def assert_review_event_relationship_topology(connection: Connection) -> None:
    """Reject altered parent links and history indexes without writing to the DB."""
    table = "review_queue_item_events"
    inspector = inspect(connection)
    if table not in inspector.get_table_names():
        raise RuntimeError("Unsafe QC review-event schema: missing event table.")
    if connection.dialect.name == "sqlite":
        foreign_keys = {
            (row["from"], row["table"], row["to"], str(row["on_delete"]).upper())
            for row in connection.execute(text("PRAGMA foreign_key_list(review_queue_item_events)")).mappings()
        }
    else:
        foreign_keys = {
            (
                fk["constrained_columns"][0],
                fk["referred_table"],
                fk["referred_columns"][0],
                str((fk.get("options") or {}).get("ondelete") or "").upper(),
            )
            for fk in inspector.get_foreign_keys(table)
            if len(fk.get("constrained_columns") or ()) == 1
            and len(fk.get("referred_columns") or ()) == 1
        }
    if foreign_keys != _EXPECTED_FOREIGN_KEYS:
        raise RuntimeError(
            "Unsafe QC review-event foreign-key topology: "
            f"actual={sorted(foreign_keys)}; expected={sorted(_EXPECTED_FOREIGN_KEYS)}. "
            "Preserve reviewer history and reconcile using a reviewed migration."
        )
    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes(table)
    }
    if indexes != _EXPECTED_INDEXES:
        raise RuntimeError(
            "Unsafe QC review-event history index topology: "
            f"actual={sorted(indexes.items())}; expected={sorted(_EXPECTED_INDEXES.items())}. "
            "Preserve reviewer history and reconcile using a reviewed migration."
        )

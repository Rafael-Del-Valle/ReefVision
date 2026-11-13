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
        # A set alone conceals duplicate declared relationships.
        foreign_key_rows = list(
            connection.execute(text("PRAGMA foreign_key_list(review_queue_item_events)")).mappings()
        )
        foreign_keys = {
            (row["from"], row["table"], row["to"], str(row["on_delete"]).upper())
            for row in foreign_key_rows
        }
        if len(foreign_key_rows) != len(foreign_keys):
            raise RuntimeError(
                "Unsafe QC review-event foreign-key topology: duplicate relationship. "
                "Preserve reviewer history."
            )
    else:
        # A composite link must never disappear from the comparison merely
        # because the inspector reports more than one constrained column.
        # Fail closed instead of silently accepting a modified audit schema.
        inspected_foreign_keys = inspector.get_foreign_keys(table)
        if any(
            len(fk.get("constrained_columns") or ()) != 1
            or len(fk.get("referred_columns") or ()) != 1
            for fk in inspected_foreign_keys
        ):
            raise RuntimeError(
                "Unsafe QC review-event foreign-key topology: composite or "
                "incomplete relationship. Preserve reviewer history."
            )
        foreign_keys = {
            (
                fk["constrained_columns"][0],
                fk["referred_table"],
                fk["referred_columns"][0],
                str((fk.get("options") or {}).get("ondelete") or "").upper(),
            )
            for fk in inspected_foreign_keys
        }
        if len(inspected_foreign_keys) != len(foreign_keys):
            raise RuntimeError(
                "Unsafe QC review-event foreign-key topology: duplicate relationship. "
                "Preserve reviewer history."
            )
    if foreign_keys != _EXPECTED_FOREIGN_KEYS:
        raise RuntimeError(
            "Unsafe QC review-event foreign-key topology: "
            f"actual={sorted(foreign_keys)}; expected={sorted(_EXPECTED_FOREIGN_KEYS)}. "
            "Preserve reviewer history and reconcile using a reviewed migration."
        )
    inspected_indexes = inspector.get_indexes(table)
    # UNIQUE or partial history indexes alter the original 0038 audit contract.
    # An expression index cannot provide the required full-column ordering.
    if any(
        index.get("unique", False)
        or (index.get("dialect_options") or {}).get("sqlite_where") is not None
        or (index.get("dialect_options") or {}).get("postgresql_where") is not None
        or any(column is None for column in index.get("column_names") or ())
        for index in inspected_indexes
    ):
        raise RuntimeError(
            "Unsafe QC review-event history index topology: unique, partial, or "
            "expression index. Preserve reviewer history."
        )
    indexes = {index["name"]: tuple(index["column_names"]) for index in inspected_indexes}
    if len(inspected_indexes) != len(indexes):
        raise RuntimeError(
            "Unsafe QC review-event history index topology: duplicate index name. "
            "Preserve reviewer history."
        )
    # SQLAlchemy's column_names does not encode SQLite ASC/DESC ordering.
    # The original 0038 history indexes use ascending columns; a DESC
    # replacement can silently alter deterministic QC-history traversal.
    # Query only fixed, known index identifiers (never user-supplied SQL).
    if connection.dialect.name == "sqlite":
        for index_name in _EXPECTED_INDEXES:
            if index_name not in indexes:
                continue
            key_columns = [
                row
                for row in connection.execute(text(f"PRAGMA index_xinfo({index_name})")).mappings()
                if row["key"]
            ]
            if any(str(row["coll"]).upper() != "BINARY" for row in key_columns):
                raise RuntimeError(
                    "Unsafe QC review-event history index topology: "
                    f"non-binary collation in {index_name}. "
                    "Preserve reviewer history."
                )
            if any(row["desc"] for row in key_columns):
                raise RuntimeError(
                    "Unsafe QC review-event history index topology: "
                    f"descending index columns in {index_name}. "
                    "Preserve reviewer history."
                )
    if indexes != _EXPECTED_INDEXES:
        raise RuntimeError(
            "Unsafe QC review-event history index topology: "
            f"actual={sorted(indexes.items())}; expected={sorted(_EXPECTED_INDEXES.items())}. "
            "Preserve reviewer history and reconcile using a reviewed migration."
        )

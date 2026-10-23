"""Fail closed when independent development branches reused Alembic revision 0038.

ReefVision 1.6's 0038 adds review_queue_item_events; 1.1's 0038 instead
adds scientific_records and environmental_cache_entries. Alembic records only
the revision identifier, so a cross-branch upgrade can silently skip the
missing migration. Do not stamp, mutate, or delete any user schema here.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


_REVIEW_TABLE = "review_queue_item_events"
_REVIEW_COLUMNS = frozenset(
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
)
_SCIENCE_TABLES = frozenset({"scientific_records", "environmental_cache_entries"})


def assert_compatible_revision_0038(connection: Connection) -> None:
    """Reject ambiguous 0038 before Alembic runs any schema-changing step.

    Older databases (including unversioned fresh installations) are unaffected.
    A deliberate, data-preserving migration reconciliation must supersede this
    guard before combining the 1.1 and 1.6 development lineages.
    """
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        return
    revisions = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if "0038" not in revisions:
        return

    tables = set(inspector.get_table_names())
    unexpected_science = sorted(tables & _SCIENCE_TABLES)
    actual_columns = (
        {column["name"] for column in inspector.get_columns(_REVIEW_TABLE)}
        if _REVIEW_TABLE in tables
        else set()
    )
    missing_columns = sorted(_REVIEW_COLUMNS - actual_columns)
    if missing_columns or unexpected_science:
        raise RuntimeError(
            "Unsafe ReefVision Alembic revision 0038 collision: the installed "
            "database is not the ReefVision 1.6 review-events lineage "
            f"(missing review columns={missing_columns}; "
            f"scientific tables present={unexpected_science}). "
            "ReefVision 1.1 independently used revision 0038 for scientific "
            "records. Stop migration, preserve the original database and "
            "resolve the two lineages with a reviewed data-preserving "
            "migration; do not stamp, downgrade, or delete tables."
        )

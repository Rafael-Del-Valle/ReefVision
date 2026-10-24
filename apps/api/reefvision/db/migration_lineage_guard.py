"""Fail closed on incompatible QC audit schemas at Alembic revisions 0038/0039.

ReefVision 1.6's 0038 adds review_queue_item_events; 1.1's 0038 instead
adds scientific_records and environmental_cache_entries. Alembic records only
the revision identifier, so a cross-branch upgrade can silently skip the
missing migration. Do not stamp, mutate, or delete any user schema here.
"""

from sqlalchemy import Connection, inspect, text

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
    """Reject incompatible 0038/0039 schemas before any desktop write.

    Older databases (including unversioned fresh installations) are unaffected.
    A deliberate, data-preserving migration reconciliation must supersede this
    guard before combining the 1.1 and 1.6 development lineages.
    """
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        return
    revisions: set[str] = set(
        connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
    )
    review_revisions = revisions & {"0038", "0039"}
    if not review_revisions:
        return
    revision = "0039" if "0039" in review_revisions else "0038"

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
            f"Unsafe ReefVision Alembic revision {revision} collision: the installed "
            "database is not the ReefVision 1.6 review-events lineage "
            f"(missing review columns={missing_columns}; "
            f"scientific tables present={unexpected_science}). "
            "ReefVision 1.1 independently used revision 0038 for scientific "
            "records. Stop migration, preserve the original database and "
            "resolve the two lineages with a reviewed data-preserving "
            "migration; do not stamp, downgrade, or delete tables."
        )

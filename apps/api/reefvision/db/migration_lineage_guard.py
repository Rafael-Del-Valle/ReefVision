"""Fail closed on incompatible QC audit schemas at Alembic revisions 0038-0040.

ReefVision 1.6's 0038 adds review_queue_item_events; 1.1's 0038 instead
adds scientific_records and environmental_cache_entries. Alembic records only
the revision identifier, so a cross-branch upgrade can silently skip the
missing migration. Do not stamp, mutate, or delete any user schema here.
"""

import re

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
    """Reject incompatible 0038-0040 schemas before any desktop write.

    Older databases (including unversioned fresh installations) are unaffected.
    A deliberate, data-preserving migration reconciliation must supersede this
    guard before combining the 1.1 and 1.6 development lineages.
    """
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        return
    # Preserve row multiplicity: two identical stamps are still an invalid
    # Alembic state and must not be hidden by set deduplication.
    revision_rows: tuple[str, ...] = tuple(
        connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
    )
    revisions = set(revision_rows)
    review_revisions = revisions & {"0038", "0039", "0040"}
    if not review_revisions:
        return
    # Alembic can record unrelated branch heads in the same version table.
    # A review lineage combined with any other head is not an accepted
    # migration graph here; reject it before desktop startup or schema writes.
    if len(revision_rows) != 1:
        raise RuntimeError(
            "Unsafe ReefVision Alembic concurrent review revisions or foreign heads: "
            f"{sorted(revision_rows)}. Preserve the database and reconcile "
            "the migration heads without stamping or deleting records."
        )
    revision = next(iter(review_revisions))

    tables = set(inspector.get_table_names())
    unexpected_science = sorted(tables & _SCIENCE_TABLES)
    review_columns = inspector.get_columns(_REVIEW_TABLE) if _REVIEW_TABLE in tables else []
    actual_columns = {column["name"] for column in review_columns}
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

    # SQL CHECK constraints do not reject NULL in SQLite. An event_type
    # column that became nullable would allow untyped audit events despite
    # an otherwise correct named allowlist. The original 0038 migration
    # requires NOT NULL; fail closed without changing any stored records.
    event_type_column = next(column for column in review_columns if column["name"] == "event_type")
    if event_type_column.get("nullable", True):
        raise RuntimeError(
            f"Unsafe ReefVision Alembic revision {revision} collision: "
            "review-event event_type is nullable, allowing NULL to bypass "
            "the audit CHECK constraint. Preserve the database and repair "
            "the schema through a reviewed, data-preserving migration."
        )

    # The original audit migration requires an explicit event type on every
    # write. A server default can silently mislabel omitted triage transitions
    # as comments, destroying the reliability of reviewer provenance.
    if event_type_column.get("default") is not None:
        raise RuntimeError(
            f"Unsafe ReefVision Alembic revision {revision} collision: "
            "review-event event_type has an unexpected server default, "
            "allowing omitted event types to be misclassified. Preserve "
            "the database and reconcile through a reviewed migration."
        )

    # Every 0038-0040 stamp requires the exact named audit-event CHECK from its
    # migration. A missing/renamed or obsolete CHECK is unsafe even when the
    # revision marker claims otherwise. Read-only inspection.
    if revision in {"0038", "0039", "0040"}:
        event_checks = inspector.get_check_constraints(_REVIEW_TABLE)
        named_check = next(
            (
                constraint
                for constraint in event_checks
                if constraint.get("name") == "ck_review_queue_item_event_type"
            ),
            None,
        )
        if named_check is None:
            raise RuntimeError(
                f"Unsafe ReefVision Alembic revision {revision} collision: the "
                "review-event CHECK constraint is missing or renamed. "
                "Preserve the database; do not stamp or rewrite audit history."
            )
        # Match the exact migration-specific allowlist. Reject weakened
        # CHECK expressions, missing values and unreviewed extra event types.
        allowed = ["comment", "assign", "unassign"]
        if revision in {"0039", "0040"}:
            allowed.extend(["triage_start", "triage_skip", "triage_return"])
        if revision == "0040":
            allowed.append("triage_complete")
        expected_check = (
            r"\s*event_type\s+IN\s*\(\s*"
            + r"\s*,\s*".join(f"'{event_type}'" for event_type in allowed)
            + r"\s*\)\s*"
        )
        expression = str(named_check.get("sqltext") or "")
        if re.fullmatch(expected_check, expression, flags=re.IGNORECASE) is None:
            raise RuntimeError(
                f"Unsafe ReefVision Alembic revision {revision} collision: the "
                "review-event CHECK constraint still excludes required event "
                "types or permits unsupported event types. Preserve the "
                "database and reconcile the migration lineage without "
                "stamping or deleting records."
            )

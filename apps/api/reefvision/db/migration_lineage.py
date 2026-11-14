"""Disambiguate numeric Alembic revisions shared by 1.1 and standalone ReefPose."""

from alembic.util import CommandError
from sqlalchemy import Connection, inspect

from reefvision.db.base import Base

# Feature names without a dot are tables. Dotted names are columns or indexes
# on tables that already existed at the common branch point.
_SCIENCE_STEPS = {
    "0038": ("scientific_records", "environmental_cache_entries"),
    "0039": ("computed_metric_definitions", "computed_metric_results"),
    "0040": ("environmental_event_definitions",),
    "0041": (
        "computed_metric_definitions.definition_kind",
        "computed_metric_definitions.configuration_json",
        "computed_metric_results.result_kind",
    ),
    "0042": ("environmental_analysis_definitions", "environmental_analysis_results"),
}
_POSE_STEPS = {
    "0038": ("pose_landmark_schema_revisions.definition_json",),
    "0039": ("pose_evaluation_runs",),
    "0040": ("jobs.deduplication_key", "jobs.ux_jobs_deduplication_key"),
    "0041": (
        "pose_identity_association_runs",
        "pose_animal_identities",
        "pose_identity_observations",
        "pose_identity_association_decisions",
        "pose_identity_occlusions",
        "pose_identity_corrections",
        "pose_identity_truth_datasets",
        "pose_identity_evaluation_runs",
    ),
    "0042": (
        "pose_measurement_runs",
        "pose_measurement_series",
        "pose_measurement_samples",
        "pose_event_detection_runs",
        "pose_biological_event_revisions",
    ),
    "0043": ("reefpose_references",),
    "0044": ("reefpose_heldout_locks",),
}
LEGACY_NUMERIC_REVISIONS = frozenset(_POSE_STEPS)
_POSE_PREFIX = "reefpose_"
_ECOLOGY_TABLES = {
    "ecology_identity_revisions",
    "ecology_identity_image_evidence",
    "ecology_identity_annotation_evidence",
    "ecology_identity_calibration_evidence",
}


def _expected_features(steps: dict[str, tuple[str, ...]], revision: str) -> set[str]:
    return {feature for step, features in steps.items() if step <= revision for feature in features}


def resolve_legacy_revision(connection: Connection, heads: tuple[str, ...]) -> str | None:
    """Return a proven ReefPose alias, or validate the existing 1.1 revision."""

    legacy_heads = sorted(set(heads) & LEGACY_NUMERIC_REVISIONS)
    if not legacy_heads:
        return None

    legacy = legacy_heads[0]
    schema = inspect(connection)
    tables = set(schema.get_table_names())
    observed_features = tables.copy()
    for table in (
        "pose_landmark_schema_revisions",
        "jobs",
        "computed_metric_definitions",
        "computed_metric_results",
    ):
        if table in tables:
            observed_features.update(
                f"{table}.{column['name']}" for column in schema.get_columns(table)
            )
    if "jobs" in tables:
        indexes = schema.get_indexes("jobs")
        observed_features.update(
            f"jobs.{index['name']}"
            for index in indexes
            if index["unique"] and index["column_names"] == ["deduplication_key"]
        )
    branch_tables = {
        feature
        for feature in _expected_features(_POSE_STEPS, "0044")
        | _expected_features(_SCIENCE_STEPS, "0042")
        | _ECOLOGY_TABLES
        if "." not in feature
    }
    later_columns = {
        # The revision signature checks these 1.1 additions separately.
        "computed_metric_definitions": {"definition_kind", "configuration_json"},
        "computed_metric_results": {"result_kind"},
        "ecology_identity_image_evidence": {"source_metadata_sha256"},
    }
    missing_columns = []
    for table in sorted(tables & branch_tables):
        required = set(Base.metadata.tables[table].columns.keys()) - later_columns.get(table, set())
        actual = {column["name"] for column in schema.get_columns(table)}
        missing_columns.extend(f"{table}.{name}" for name in sorted(required - actual))

    pose_features = observed_features & _expected_features(_POSE_STEPS, "0044")
    science_features = observed_features & _expected_features(_SCIENCE_STEPS, "0042")

    # Multiple heads can arise through valid targeted migrations in the new
    # graph. An explicit sibling head makes its schema valid alongside 1.1.
    sibling_pose_heads = [
        head.removeprefix(_POSE_PREFIX) for head in heads if head.startswith(_POSE_PREFIX)
    ]
    ecology_active = any(head.startswith("b12_identity_") for head in heads)
    unexpected_schema = "review_queue_item_events" in tables or bool(
        tables & _ECOLOGY_TABLES and not ecology_active
    )
    if len(legacy_heads) == 1 and not unexpected_schema and not missing_columns:
        if (
            legacy in _SCIENCE_STEPS
            and science_features == _expected_features(_SCIENCE_STEPS, legacy)
            and pose_features
            == _expected_features(_POSE_STEPS, max(sibling_pose_heads, default=""))
        ):
            return None
        if (
            len(heads) == 1
            and not science_features
            and pose_features == _expected_features(_POSE_STEPS, legacy)
        ):
            return f"{_POSE_PREFIX}{legacy}"

    raise CommandError(
        f"Cannot determine migration lineage for Alembic revision(s) {', '.join(heads)}. "
        "The database schema does not match its recorded ReefVision or ReefPose history."
        + (f" Missing columns: {', '.join(missing_columns)}." if missing_columns else "")
    )

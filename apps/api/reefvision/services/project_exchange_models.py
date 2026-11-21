"""Local relational bindings for portable model registrations."""

from __future__ import annotations

from typing import Any


def has_local_model_lineage(row: dict[str, Any]) -> bool:
    """Only these registration formats declare ReefVision-owned metadata links."""
    return row.get("provider_name") in {"ultralytics", "reefpose", "reefpose_temporal", "nnunet"}


def _remap_registration_fields(
    record: dict[str, Any], fields: tuple[str, ...], id_map: dict[str, str]
) -> dict[str, Any]:
    result = dict(record)
    for field in fields:
        identifier = record.get(field)
        if isinstance(identifier, str) and identifier in id_map:
            result[field] = id_map[identifier]
    return result


def remap_model_registration(row: dict[str, Any], id_map: dict[str, str]) -> dict[str, Any]:
    """Rebind ReefVision links while preserving checkpoint labels and provider-owned data."""
    values = _remap_registration_fields(row, ("id", "project_id"), id_map)
    if isinstance(class_map := row.get("class_map_json"), dict):
        classes = dict(class_map)
        if isinstance(mapping := class_map.get("mapping"), dict):
            classes["mapping"] = _remap_registration_fields(mapping, tuple(mapping), id_map)
        if isinstance(folders := class_map.get("provider_classes"), dict):
            classes["provider_classes"] = {
                key: _remap_registration_fields(entry, ("label_class_id",), id_map)
                if isinstance(entry, dict)
                else entry
                for key, entry in folders.items()
            }
        values["class_map_json"] = classes
    if has_local_model_lineage(row) and isinstance(metadata := row.get("metadata_json"), dict):
        bindings = _remap_registration_fields(
            metadata,
            (
                "source_training_run_id",
                "source_dataset_version_id",
                "source_resolved_model_asset_id",
                "source_experiment_id",
                "classification_dataset_id",
                "source_pose_training_dataset_id",
                "source_pose_validation_dataset_id",
                "source_pose_schema_id",
                "source_initial_pose_model_id",
                "source_temporal_dataset_id",
                "source_temporal_run_id",
                "frame_model_id",
                "promoted_by_evaluation_id",
                "promoted_by_segmentation_evaluation_id",
                "active_segmentation_deployment_id",
            ),
            id_map,
        )
        if isinstance(schema := metadata.get("pose_landmark_schema"), dict):
            bindings["pose_landmark_schema"] = _remap_registration_fields(
                schema, ("schema_id",), id_map
            )
        values["metadata_json"] = bindings
    return values

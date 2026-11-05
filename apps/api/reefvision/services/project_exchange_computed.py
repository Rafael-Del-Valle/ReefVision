"""Validate and remap computed scientific evidence without rewriting source provenance."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from math import isclose
from typing import Any

from pydantic import ValidationError as SchemaError

from reefvision.domain.computed_metrics import (
    FORMULA_ENGINE_VERSION,
    MetricExpressionError,
    MetricQuantity,
    evaluate_expression,
)
from reefvision.domain.errors import ValidationError
from reefvision.domain.scientific_units import UNITS
from reefvision.schemas.annotation_comparison import (
    AnnotationComparisonPreviewRequest,
    AnnotationComparisonPreviewResponse,
)
from reefvision.schemas.computed_aggregate_metrics import ComputedAggregateDefinitionCreate
from reefvision.schemas.computed_mask_coverage import (
    ComputedMaskCoverageDefinitionCreate,
    ComputedMaskCoverageResultResponse,
)
from reefvision.schemas.computed_metrics import ComputedMetricDefinitionCreate
from reefvision.schemas.measurements import MeasurementCalibrationUpdate
from reefvision.schemas.scientific_data import ScientificRecordResponse
from reefvision.services.computed_metrics import ComputedMetricService
from reefvision.services.scientific_data import content_hash

COMPUTED_SECTIONS = {"computed_metric_definitions", "computed_metric_results"}
AGGREGATE_KIND = "annotation_aggregate"
AGGREGATE_FORMULA_VERSION = "reefvision.annotation-aggregate.v1"
MASK_COVERAGE_KIND = "mask_coverage"
MASK_COVERAGE_FORMULA_VERSION = "reefvision.mask-coverage.v1"
MASK_COVERAGE_ALGORITHM = "reefvision.source-pixel-mask-union.v1"
ANNOTATION_COMPARISON_KIND = "annotation_comparison"
ANNOTATION_COMPARISON_VERSION = "reefvision.annotation-comparison.v1"


def _remap_identifiers(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return id_map.get(value, value)
    if isinstance(value, list):
        return [_remap_identifiers(item, id_map) for item in value]
    if isinstance(value, dict):
        return {key: _remap_identifiers(item, id_map) for key, item in value.items()}
    return value


def _validate_annotation_comparison_definition(
    project_id: str, row: dict[str, Any], sections: dict[str, list[dict[str, Any]]]
) -> None:
    config = row.get("configuration_json")
    request = AnnotationComparisonPreviewRequest.model_validate(config)
    images = {item["id"]: item for item in sections.get("images", [])}
    image = images.get(str(request.image_id))
    if image is None or image.get("project_id") != project_id:
        raise ValidationError("Annotation comparison refers to a missing project image")
    if (
        row.get("project_id") != project_id
        or row.get("definition_kind") != ANNOTATION_COMPARISON_KIND
        or row.get("formula_version") != ANNOTATION_COMPARISON_VERSION
        or row.get("input_spec_json") != []
        or row.get("output_unit") != "count"
        or content_hash(_aggregate_definition_payload(row)) != row.get("definition_sha256")
    ):
        raise ValidationError("Annotation comparison definition checksum mismatch")


def _validate_annotation_comparison_result(
    project_id: str, row: dict[str, Any], definition: dict[str, Any]
) -> None:
    payload = row.get("payload_json")
    if (
        row.get("project_id") != project_id
        or row.get("result_kind") != ANNOTATION_COMPARISON_KIND
        or not isinstance(payload, dict)
        or content_hash(payload) != row.get("content_sha256")
        or payload.get("definition_id") != definition.get("id")
        or payload.get("definition_name") != definition.get("name")
        or payload.get("definition_sha256") != definition.get("definition_sha256")
        or payload.get("formula_version") != ANNOTATION_COMPARISON_VERSION
    ):
        raise ValidationError("Annotation comparison result checksum mismatch")
    comparison = payload.get("comparison")
    AnnotationComparisonPreviewResponse.model_validate(comparison)
    if not isinstance(comparison, dict):
        raise ValidationError("Annotation comparison payload is invalid")
    comparison_content = {
        key: value for key, value in comparison.items() if key != "content_sha256"
    }
    if content_hash(comparison_content) != comparison.get("content_sha256"):
        raise ValidationError("Annotation comparison evidence checksum mismatch")


def _definition_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "expression": row["expression"],
        "formula_version": row["formula_version"],
        "inputs": row["input_spec_json"],
        "output_unit": row["output_unit"],
    }


def _aggregate_definition_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "expression": row["expression"],
        "formula_version": row["formula_version"],
        "output_unit": row["output_unit"],
        "configuration": row["configuration_json"],
    }


def _validate_mask_coverage_definition(
    project_id: str,
    row: dict[str, Any],
    labels: dict[str, dict[str, Any]],
) -> None:
    config = row.get("configuration_json")
    if not isinstance(config, dict):
        raise ValidationError("Mask coverage definition configuration is invalid")
    payload = ComputedMaskCoverageDefinitionCreate.model_validate(
        {
            "name": row["name"],
            "grouping_level": config["grouping_level"],
            "label_class_ids": config.get("label_class_ids", []),
            "roi_label_class_id": config.get("roi_label_class_id"),
        }
    )
    expected_config = {
        "schema_version": "1.1.0",
        "grouping_level": payload.grouping_level,
        "label_class_ids": [str(value) for value in payload.label_class_ids],
        "roi_label_class_id": (
            str(payload.roi_label_class_id) if payload.roi_label_class_id else None
        ),
        "operation": "verified_mask_union_coverage",
        "required_review_state": "reviewed",
        "independence_contract": (
            "one_unit_per_image"
            if payload.grouping_level == "image"
            else "one_unit_per_image_group_key"
        ),
        "roi_contract": (
            "verified_mask_class_union" if payload.roi_label_class_id else "full_image"
        ),
    }
    referenced_labels = [str(value) for value in payload.label_class_ids]
    if payload.roi_label_class_id is not None:
        referenced_labels.append(str(payload.roi_label_class_id))
    if any(
        label_id not in labels or labels[label_id].get("project_id") != project_id
        for label_id in referenced_labels
    ):
        raise ValidationError("Mask coverage definition has a missing label class")
    if (
        row.get("project_id") != project_id
        or row.get("definition_kind") != MASK_COVERAGE_KIND
        or row.get("formula_version") != MASK_COVERAGE_FORMULA_VERSION
        or row.get("expression") != "union_area(verified_masks) / explicit_denominator"
        or row.get("input_spec_json") != []
        or row.get("output_unit") != "percent"
        or config != expected_config
        or content_hash(_aggregate_definition_payload(row)) != row.get("definition_sha256")
    ):
        raise ValidationError("Mask coverage definition checksum or contract mismatch")


def _validate_mask_coverage_result(
    project_id: str,
    row: dict[str, Any],
    definition: dict[str, Any],
    sections: dict[str, list[dict[str, Any]]],
    workflow_runs: dict[str, dict[str, Any]],
    workflow_nodes: dict[str, dict[str, Any]],
) -> None:
    payload = row.get("payload_json")
    if (
        row.get("project_id") != project_id
        or row.get("result_kind") != MASK_COVERAGE_KIND
        or not isinstance(payload, dict)
        or content_hash(payload) != row.get("content_sha256")
    ):
        raise ValidationError("Mask coverage result checksum mismatch")
    ComputedMaskCoverageResultResponse.model_validate(
        {
            **payload,
            "id": row["id"],
            "project_id": row["project_id"],
            "result_kind": row["result_kind"],
            "content_sha256": row["content_sha256"],
            "workflow_run_id": row.get("workflow_run_id"),
            "workflow_node_run_id": row.get("workflow_node_run_id"),
            "created_at": row["created_at"],
        }
    )
    if (
        payload.get("definition_id") != definition.get("id")
        or payload.get("definition_name") != definition.get("name")
        or payload.get("expression") != definition.get("expression")
        or payload.get("formula_version") != definition.get("formula_version")
        or payload.get("definition_sha256") != definition.get("definition_sha256")
        or payload.get("output_unit") != "percent"
        or payload.get("algorithm") != MASK_COVERAGE_ALGORITHM
        or payload.get("coordinate_frame") != "source_image_pixels"
    ):
        raise ValidationError("Mask coverage result definition snapshot mismatch")
    workflow_run_id = row.get("workflow_run_id")
    workflow_node_run_id = row.get("workflow_node_run_id")
    if workflow_run_id is not None and workflow_run_id not in workflow_runs:
        raise ValidationError("Mask coverage result refers to a missing workflow run")
    if workflow_node_run_id is not None:
        node = workflow_nodes.get(workflow_node_run_id)
        if (
            node is None
            or workflow_run_id is None
            or node.get("workflow_run_id") != workflow_run_id
            or node.get("node_type") != "mask_coverage"
        ):
            raise ValidationError("Mask coverage result workflow provenance mismatch")

    images = {item["id"]: item for item in sections.get("images", [])}
    labels = {item["id"]: item for item in sections.get("label_classes", [])}
    masks = {item["id"]: item for item in sections.get("mask_annotations", [])}
    image_snapshot = payload.get("image_snapshot")
    mask_snapshot = payload.get("mask_snapshot")
    if not isinstance(image_snapshot, list) or not isinstance(mask_snapshot, list):
        raise ValidationError("Mask coverage evidence inventory is invalid")
    raw_image_ids = [item.get("image_id") for item in image_snapshot if isinstance(item, dict)]
    raw_mask_ids = [item.get("id") for item in mask_snapshot if isinstance(item, dict)]
    if (
        len(raw_image_ids) != len(image_snapshot)
        or any(not isinstance(value, str) for value in raw_image_ids)
        or len(raw_mask_ids) != len(mask_snapshot)
        or any(not isinstance(value, str) for value in raw_mask_ids)
    ):
        raise ValidationError("Mask coverage evidence inventory is invalid")
    image_ids = [str(value) for value in raw_image_ids]
    mask_ids = [str(value) for value in raw_mask_ids]
    if (
        image_ids != sorted(image_ids)
        or len(image_ids) != len(set(image_ids))
        or mask_ids != sorted(mask_ids)
        or len(mask_ids) != len(set(mask_ids))
    ):
        raise ValidationError("Mask coverage evidence inventory is duplicated or unordered")
    config = definition["configuration_json"]
    for snapshot in image_snapshot:
        image = images.get(snapshot["image_id"])
        if image is None or image.get("project_id") != project_id:
            raise ValidationError("Mask coverage image snapshot refers to a missing image")
        raw_calibration = dict(image.get("metadata_json") or {}).get("measurement_calibration")
        unavailable = None
        calibration = raw_calibration
        if raw_calibration is None:
            unavailable = "missing_calibration"
        elif not isinstance(raw_calibration, dict):
            unavailable = "invalid_calibration"
        else:
            try:
                parsed_calibration = MeasurementCalibrationUpdate.model_validate(raw_calibration)
            except SchemaError:
                unavailable = "invalid_calibration"
            else:
                calibration = parsed_calibration.model_dump(mode="json")
                if (
                    parsed_calibration.unit not in UNITS
                    or UNITS[parsed_calibration.unit][0] != "length"
                ):
                    unavailable = "unsupported_calibration_unit"
                elif parsed_calibration.perspective_homography is not None:
                    unavailable = "perspective_homography_requires_union_resampling"
        expected = {
            "image_id": image["id"],
            "sha256": image["sha256"],
            "width_px": image["width_px"],
            "height_px": image["height_px"],
            "annotation_revision": image["annotation_revision"],
            "annotation_status": image["annotation_status"],
            "group_key": image.get("group_key"),
            "updated_at": _utc(image["updated_at"]).isoformat(),
            "calibration": calibration,
            "physical_unavailable_reason": unavailable,
        }
        if snapshot != expected or image.get("annotation_status") != "reviewed":
            raise ValidationError("Mask coverage image snapshot mismatch")
        if config["grouping_level"] == "image_group_key" and not image.get("group_key"):
            raise ValidationError("Mask coverage group key is missing")

    label_filter = set(config.get("label_class_ids", []))
    roi_label = config.get("roi_label_class_id")
    eligible_ids: set[str] = set()
    for mask in masks.values():
        is_eligible = (
            mask.get("image_id") in image_ids
            and mask.get("deleted_at") is None
            and mask.get("status") == "verified"
            and (
                mask.get("label_class_id") == roi_label
                or (
                    mask.get("label_class_id") != roi_label
                    and (not label_filter or mask.get("label_class_id") in label_filter)
                )
            )
        )
        if is_eligible:
            eligible_ids.add(mask["id"])
    if eligible_ids != set(mask_ids):
        raise ValidationError("Mask coverage mask inventory mismatch")
    for snapshot in mask_snapshot:
        mask = masks[snapshot["id"]]
        label_id = mask.get("label_class_id")
        expected_label = labels.get(label_id, {}).get("name", "Unclassified")
        if (
            snapshot.get("image_id") != mask.get("image_id")
            or snapshot.get("role") != ("roi" if label_id == roi_label else "target")
            or snapshot.get("label_class_id") != label_id
            or snapshot.get("label_name") != expected_label
            or snapshot.get("geometry_kind") != mask.get("geometry_kind")
            or snapshot.get("polygon") != mask.get("polygon_json")
            or snapshot.get("mask_path") != mask.get("mask_path")
            or snapshot.get("source_type") != mask.get("source_type")
            or snapshot.get("status") != mask.get("status")
            or snapshot.get("revision") != mask.get("revision")
        ):
            raise ValidationError("Mask coverage mask snapshot mismatch")
    evidence_hash = content_hash(
        {
            "definition_sha256": definition["definition_sha256"],
            "algorithm": MASK_COVERAGE_ALGORITHM,
            "coordinate_frame": "source_image_pixels",
            "images": image_snapshot,
            "masks": mask_snapshot,
        }
    )
    if payload.get("evidence_sha256") != evidence_hash:
        raise ValidationError("Mask coverage evidence checksum mismatch")
    provenance = payload.get("provenance")
    expected_provenance = {
        "definition_sha256": definition["definition_sha256"],
        "evidence_sha256": evidence_hash,
        "selection_is_explicit": True,
        "verified_masks_only": True,
        "predictions_counted": False,
        "algorithm": MASK_COVERAGE_ALGORITHM,
        "coordinate_frame": "source_image_pixels",
        "density_numerator": "verified_target_masks_intersecting_sampling_region",
        "density_denominator": "verified_roi_area_or_full_image_area",
    }
    if provenance != expected_provenance:
        raise ValidationError("Mask coverage provenance mismatch")
    observed_at = _utc(row["observed_at"])
    expected_observed_at = max(_utc(images[image_id]["updated_at"]) for image_id in image_ids)
    if _utc(payload["observed_at"]) != observed_at or observed_at != expected_observed_at:
        raise ValidationError("Mask coverage observation timestamp mismatch")


def _validate_aggregate_definition(
    project_id: str,
    row: dict[str, Any],
    labels: dict[str, dict[str, Any]],
) -> None:
    config = row.get("configuration_json")
    if not isinstance(config, dict):
        raise ValidationError("Computed aggregate definition configuration is invalid")
    payload = ComputedAggregateDefinitionCreate.model_validate(
        {
            "name": row["name"],
            "source_kind": config["source_kind"],
            "grouping_level": config["grouping_level"],
            "label_class_ids": config.get("label_class_ids", []),
        }
    )
    expected_contract = (
        "one_unit_per_image"
        if payload.grouping_level == "image"
        else "one_unit_per_image_group_key"
    )
    expected_config = {
        "schema_version": "1.1.0",
        "source_kind": payload.source_kind,
        "grouping_level": payload.grouping_level,
        "label_class_ids": [str(value) for value in payload.label_class_ids],
        "operation": "count",
        "required_review_state": "reviewed",
        "independence_contract": expected_contract,
    }
    label_ids = expected_config["label_class_ids"]
    if any(
        label_id not in labels or labels[label_id].get("project_id") != project_id
        for label_id in label_ids
    ):
        raise ValidationError("Computed aggregate definition has a missing label filter")
    if (
        row.get("project_id") != project_id
        or row.get("definition_kind") != AGGREGATE_KIND
        or row.get("formula_version") != AGGREGATE_FORMULA_VERSION
        or row.get("expression") != f"count({payload.source_kind})"
        or row.get("input_spec_json") != []
        or row.get("output_unit") != "count"
        or config != expected_config
        or content_hash(_aggregate_definition_payload(row)) != row.get("definition_sha256")
    ):
        raise ValidationError("Computed aggregate definition checksum or contract mismatch")


def _validate_aggregate_result(
    project_id: str,
    row: dict[str, Any],
    definition: dict[str, Any],
    sections: dict[str, list[dict[str, Any]]],
    workflow_runs: dict[str, dict[str, Any]],
    workflow_nodes: dict[str, dict[str, Any]],
) -> None:
    payload = row.get("payload_json")
    if (
        row.get("project_id") != project_id
        or row.get("result_kind") != AGGREGATE_KIND
        or not isinstance(payload, dict)
        or content_hash(payload) != row.get("content_sha256")
    ):
        raise ValidationError("Computed aggregate result checksum mismatch")
    if (
        payload.get("definition_id") != definition.get("id")
        or payload.get("definition_name") != definition.get("name")
        or payload.get("expression") != definition.get("expression")
        or payload.get("formula_version") != definition.get("formula_version")
        or payload.get("definition_sha256") != definition.get("definition_sha256")
        or payload.get("output_unit") != "count"
    ):
        raise ValidationError("Computed aggregate result definition snapshot mismatch")
    workflow_run_id = row.get("workflow_run_id")
    workflow_node_run_id = row.get("workflow_node_run_id")
    if workflow_run_id is not None and workflow_run_id not in workflow_runs:
        raise ValidationError("Computed aggregate result refers to a missing workflow run")
    if workflow_node_run_id is not None:
        node = workflow_nodes.get(workflow_node_run_id)
        if (
            node is None
            or workflow_run_id is None
            or node.get("workflow_run_id") != workflow_run_id
            or node.get("node_type") != "annotation_aggregate"
        ):
            raise ValidationError("Computed aggregate result workflow provenance mismatch")

    images = {item["id"]: item for item in sections.get("images", [])}
    labels = {item["id"]: item for item in sections.get("label_classes", [])}
    config = definition["configuration_json"]
    image_snapshot = payload.get("image_snapshot")
    observation_snapshot = payload.get("observation_snapshot")
    if not isinstance(image_snapshot, list) or not isinstance(observation_snapshot, list):
        raise ValidationError("Computed aggregate evidence inventory is invalid")
    raw_image_ids = [item.get("image_id") for item in image_snapshot if isinstance(item, dict)]
    if (
        len(raw_image_ids) != len(image_snapshot)
        or any(not isinstance(value, str) for value in raw_image_ids)
        or len(raw_image_ids) != len(set(raw_image_ids))
    ):
        raise ValidationError("Computed aggregate image inventory is duplicated or invalid")
    image_ids = [value for value in raw_image_ids if isinstance(value, str)]
    if image_ids != sorted(image_ids):
        raise ValidationError("Computed aggregate image inventory is not deterministic")
    for snapshot in image_snapshot:
        image = images.get(snapshot["image_id"])
        expected = (
            {
                "image_id": image["id"],
                "sha256": image["sha256"],
                "annotation_revision": image["annotation_revision"],
                "annotation_status": image["annotation_status"],
                "group_key": image.get("group_key"),
            }
            if image is not None
            else None
        )
        if (
            image is None
            or image.get("project_id") != project_id
            or image.get("annotation_status") != "reviewed"
            or snapshot != expected
        ):
            raise ValidationError("Computed aggregate image snapshot mismatch")
        if config["grouping_level"] == "image_group_key" and not image.get("group_key"):
            raise ValidationError("Computed aggregate group key is missing")
    observed_at = _utc(row["observed_at"])
    expected_observed_at = max(_utc(images[image_id]["updated_at"]) for image_id in image_ids)
    if _utc(payload["observed_at"]) != observed_at or observed_at != expected_observed_at:
        raise ValidationError("Computed aggregate observation timestamp mismatch")

    source_section = (
        "annotations" if config["source_kind"] == "verified_annotations" else "mask_annotations"
    )
    source_rows = {item["id"]: item for item in sections.get(source_section, [])}
    label_filter = set(config.get("label_class_ids", []))
    expected_observations: list[dict[str, Any]] = []
    for source in sorted(source_rows.values(), key=lambda item: item["id"]):
        eligible = (
            source.get("image_id") in image_ids
            and source.get("deleted_at") is None
            and (not label_filter or source.get("label_class_id") in label_filter)
            and (source_section == "annotations" or source.get("status") == "verified")
        )
        if eligible:
            expected_observations.append(
                {
                    "id": source["id"],
                    "image_id": source["image_id"],
                    "label_class_id": source.get("label_class_id"),
                    "source_type": source["source_type"],
                    "revision": source["revision"],
                }
            )
    if observation_snapshot != expected_observations:
        raise ValidationError("Computed aggregate observation snapshot mismatch")
    if any(
        item["label_class_id"] is not None and item["label_class_id"] not in labels
        for item in expected_observations
    ):
        raise ValidationError("Computed aggregate observation label is missing")

    def class_counts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        item_counts = Counter(item["label_class_id"] for item in items)
        return [
            {
                "label_class_id": label_id,
                "label_name": (
                    labels[label_id]["name"] if label_id is not None else "Unclassified"
                ),
                "count": count,
            }
            for label_id, count in sorted(item_counts.items(), key=lambda item: str(item[0] or ""))
        ]

    units: dict[str, list[str]] = defaultdict(list)
    for image_id in image_ids:
        image = images[image_id]
        unit_key = image_id if config["grouping_level"] == "image" else image["group_key"]
        units[str(unit_key)].append(image_id)
    expected_groups = []
    for unit_key in sorted(units):
        unit_image_ids = sorted(units[unit_key])
        unit_rows = [item for item in expected_observations if item["image_id"] in unit_image_ids]
        expected_groups.append(
            {
                "unit_key": unit_key,
                "image_ids": unit_image_ids,
                "observation_count": len(unit_rows),
                "counts_by_class": class_counts(unit_rows),
            }
        )
    proposals = [
        item
        for item in sections.get("prediction_proposals", [])
        if item.get("image_id") in image_ids
        and (not label_filter or item.get("label_class_id") in label_filter)
    ]
    excluded = dict(sorted(Counter(item["review_status"] for item in proposals).items()))
    evidence_hash = content_hash(
        {
            "definition_sha256": definition["definition_sha256"],
            "images": image_snapshot,
            "observations": expected_observations,
            "excluded_proposals_by_status": excluded,
        }
    )
    expected_mean = len(expected_observations) / len(expected_groups)
    if (
        payload.get("source_kind") != config["source_kind"]
        or payload.get("grouping_level") != config["grouping_level"]
        or payload.get("operation") != "count"
        or payload.get("required_review_state") != "reviewed"
        or payload.get("image_count") != len(image_ids)
        or payload.get("independent_unit_count") != len(expected_groups)
        or payload.get("observation_count") != len(expected_observations)
        or not _same_number(payload.get("mean_per_independent_unit"), expected_mean)
        or payload.get("counts_by_class") != class_counts(expected_observations)
        or payload.get("groups") != expected_groups
        or payload.get("excluded_proposals_by_status") != excluded
        or payload.get("evidence_sha256") != evidence_hash
    ):
        raise ValidationError("Computed aggregate result is not reproducible from its evidence")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or provenance != {
        "definition_sha256": definition["definition_sha256"],
        "evidence_sha256": evidence_hash,
        "selection_is_explicit": True,
        "predictions_counted": False,
    }:
        raise ValidationError("Computed aggregate result provenance mismatch")


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _snapshot(
    row: dict[str, Any],
    *,
    project_id: str,
    calibration_current: bool | None,
    environmental_snapshot_current: bool | None,
) -> dict[str, Any]:
    return ScientificRecordResponse.model_validate(
        {
            **row["payload_json"],
            "id": row["id"],
            "project_id": project_id,
            "content_sha256": row["content_sha256"],
            "calibration_current": calibration_current,
            "environmental_snapshot_current": environmental_snapshot_current,
        }
    ).model_dump(mode="json")


def _same_number(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return left == right
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    return isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)


def _source_category(subject: dict[str, Any]) -> str:
    if subject.get("prediction_id"):
        return "model_prediction"
    if subject.get("annotation_id") or subject.get("mask_id"):
        return "verified_annotation"
    return "scientific_observation"


def validate_computed_exchange_records(
    project_id: str, sections: dict[str, list[dict[str, Any]]]
) -> None:
    """Reject computed rows that cannot be reproduced from archived scientific inputs."""

    definitions = {row["id"]: row for row in sections.get("computed_metric_definitions", [])}
    scientific = {row["id"]: row for row in sections.get("scientific_records", [])}
    workflow_runs = {row["id"]: row for row in sections.get("workflow_runs", [])}
    workflow_nodes = {row["id"]: row for row in sections.get("workflow_node_runs", [])}
    labels = {row["id"]: row for row in sections.get("label_classes", [])}
    try:
        compiled_by_id: dict[str, Any] = {}
        for identifier, row in definitions.items():
            if row.get("definition_kind") == ANNOTATION_COMPARISON_KIND:
                _validate_annotation_comparison_definition(project_id, row, sections)
                compiled_by_id[identifier] = None
                continue
            if row.get("definition_kind", "scalar") == AGGREGATE_KIND:
                _validate_aggregate_definition(project_id, row, labels)
                compiled_by_id[identifier] = None
                continue
            if row.get("definition_kind") == MASK_COVERAGE_KIND:
                _validate_mask_coverage_definition(project_id, row, labels)
                compiled_by_id[identifier] = None
                continue
            if row.get("project_id") != project_id:
                raise ValidationError("Foreign project reference in computed metric definitions")
            if row.get("formula_version") != FORMULA_ENGINE_VERSION:
                raise ValidationError(
                    f"Unsupported computed metric formula version: {row.get('formula_version')}"
                )
            if content_hash(_definition_payload(row)) != row.get("definition_sha256"):
                raise ValidationError("Computed metric definition checksum mismatch")
            payload = ComputedMetricDefinitionCreate.model_validate(
                {
                    "name": row["name"],
                    "expression": row["expression"],
                    "inputs": row["input_spec_json"],
                    "output_unit": row["output_unit"],
                }
            )
            compiled_by_id[identifier] = ComputedMetricService._compile_definition(payload)

        for row in sections.get("computed_metric_results", []):
            if row.get("result_kind") == ANNOTATION_COMPARISON_KIND:
                definition = definitions.get(row.get("definition_id"))
                if (
                    definition is None
                    or definition.get("definition_kind") != ANNOTATION_COMPARISON_KIND
                ):
                    raise ValidationError(
                        "Annotation comparison result refers to a missing definition"
                    )
                _validate_annotation_comparison_result(project_id, row, definition)
                continue
            if row.get("result_kind", "scalar") == AGGREGATE_KIND:
                definition_id = row.get("definition_id")
                definition = definitions.get(definition_id)
                if definition is None or definition.get("definition_kind") != AGGREGATE_KIND:
                    raise ValidationError(
                        "Computed aggregate result refers to a missing definition"
                    )
                _validate_aggregate_result(
                    project_id,
                    row,
                    definition,
                    sections,
                    workflow_runs,
                    workflow_nodes,
                )
                continue
            if row.get("result_kind") == MASK_COVERAGE_KIND:
                definition_id = row.get("definition_id")
                definition = definitions.get(definition_id)
                if definition is None or definition.get("definition_kind") != MASK_COVERAGE_KIND:
                    raise ValidationError("Mask coverage result refers to a missing definition")
                _validate_mask_coverage_result(
                    project_id,
                    row,
                    definition,
                    sections,
                    workflow_runs,
                    workflow_nodes,
                )
                continue
            if row.get("project_id") != project_id:
                raise ValidationError("Foreign project reference in computed metric results")
            payload = row["payload_json"]
            if not isinstance(payload, dict) or content_hash(payload) != row.get("content_sha256"):
                raise ValidationError("Computed metric result checksum mismatch")
            definition_id = row.get("definition_id")
            if not isinstance(definition_id, str):
                raise ValidationError("Computed metric result definition ID is invalid")
            definition = definitions.get(definition_id)
            if definition is None or payload.get("definition_id") != definition_id:
                raise ValidationError("Computed metric result refers to a missing definition")
            workflow_run_id = row.get("workflow_run_id")
            workflow_node_run_id = row.get("workflow_node_run_id")
            if workflow_run_id is not None and workflow_run_id not in workflow_runs:
                raise ValidationError("Computed metric result refers to a missing workflow run")
            if workflow_node_run_id is not None:
                workflow_node = workflow_nodes.get(workflow_node_run_id)
                if (
                    workflow_node is None
                    or workflow_run_id is None
                    or workflow_node.get("workflow_run_id") != workflow_run_id
                ):
                    raise ValidationError("Computed metric result workflow provenance mismatch")
            for field, definition_field in (
                ("definition_name", "name"),
                ("expression", "expression"),
                ("formula_version", "formula_version"),
                ("definition_sha256", "definition_sha256"),
            ):
                if payload.get(field) != definition.get(definition_field):
                    raise ValidationError("Computed metric result definition snapshot mismatch")
            bindings = payload.get("input_record_ids")
            snapshots = payload.get("input_snapshot")
            if not isinstance(bindings, dict) or not isinstance(snapshots, dict):
                raise ValidationError("Computed metric result input inventory is invalid")
            specs = definition["input_spec_json"]
            symbols = {item["symbol"] for item in specs}
            if set(bindings) != symbols or set(snapshots) != symbols:
                raise ValidationError("Computed metric result inputs do not match its definition")

            quantities: dict[str, MetricQuantity] = {}
            expected_hashes: dict[str, str] = {}
            for symbol, record_id in bindings.items():
                record = scientific.get(record_id)
                if record is None:
                    raise ValidationError("Computed metric result refers to a missing input record")
                archived_snapshot = snapshots[symbol]
                if not isinstance(archived_snapshot, dict):
                    raise ValidationError("Computed metric result input snapshot is invalid")
                expected = _snapshot(
                    record,
                    project_id=project_id,
                    calibration_current=archived_snapshot.get("calibration_current"),
                    environmental_snapshot_current=archived_snapshot.get(
                        "environmental_snapshot_current"
                    ),
                )
                if archived_snapshot != expected:
                    raise ValidationError("Computed metric result input snapshot mismatch")
                uncertainty = archived_snapshot.get("uncertainty")
                quantities[symbol] = MetricQuantity(
                    value=archived_snapshot["value"],
                    unit=archived_snapshot["unit"],
                    uncertainty=(uncertainty["value"] if uncertainty is not None else None),
                )
                expected_hashes[symbol] = record["content_sha256"]

            provenance = payload.get("provenance")
            if (
                not isinstance(provenance, dict)
                or provenance.get("input_content_sha256") != expected_hashes
            ):
                raise ValidationError("Computed metric input checksum provenance mismatch")
            if (
                provenance.get("formula_engine") != FORMULA_ENGINE_VERSION
                or provenance.get("definition_sha256") != definition["definition_sha256"]
            ):
                raise ValidationError("Computed metric formula engine provenance mismatch")
            ordered_snapshots = [snapshots[symbol] for symbol in sorted(symbols)]
            subjects = [
                {key: value for key, value in snapshot["subject"].items() if value is not None}
                for snapshot in ordered_snapshots
            ]
            if (
                any(subject != subjects[0] for subject in subjects[1:])
                or payload.get("subject") != subjects[0]
            ):
                raise ValidationError("Computed metric result subject snapshot mismatch")
            evaluation = evaluate_expression(
                compiled_by_id[definition_id], quantities, output_unit=definition["output_unit"]
            )
            uncertainty_kinds = {
                uncertainty["kind"]
                for snapshot in ordered_snapshots
                if (uncertainty := snapshot.get("uncertainty")) is not None
            }
            expected_provenance = {
                "source_categories": sorted({_source_category(subject) for subject in subjects}),
                "uncertainty_kind": (
                    next(iter(uncertainty_kinds)) if evaluation.uncertainty is not None else None
                ),
                "uncertainty_method": (
                    "independent_first_order_root_sum_square"
                    if evaluation.uncertainty is not None
                    else "unavailable_missing_input_uncertainty"
                ),
            }
            if (
                "bound" in uncertainty_kinds
                or len(uncertainty_kinds) > 1
                or any(provenance.get(key) != value for key, value in expected_provenance.items())
            ):
                raise ValidationError("Computed metric result provenance mismatch")
            expected_values = {
                "value": evaluation.value,
                "normalized_value": evaluation.normalized_value,
                "uncertainty": evaluation.uncertainty,
                "normalized_uncertainty": evaluation.normalized_uncertainty,
            }
            if any(
                not _same_number(payload.get(key), value) for key, value in expected_values.items()
            ):
                raise ValidationError("Computed metric result is not reproducible from its inputs")
            for key, value in (
                ("unit", evaluation.unit),
                ("normalized_unit", evaluation.normalized_unit),
                ("dimension", evaluation.dimension),
            ):
                if payload.get(key) != value:
                    raise ValidationError("Computed metric result unit metadata mismatch")
            observed_at = _utc(row["observed_at"])
            if _utc(payload["observed_at"]) != observed_at or any(
                _utc(snapshot["observed_at"]) != observed_at for snapshot in snapshots.values()
            ):
                raise ValidationError("Computed metric observation timestamp mismatch")
    except ValidationError:
        raise
    except (KeyError, TypeError, ValueError, SchemaError, MetricExpressionError) as exc:
        raise ValidationError("Invalid computed metric exchange inventory") from exc


def remap_computed_sections(
    sections: dict[str, list[dict[str, Any]]],
    id_map: dict[str, str],
    remapped_science: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Remap declared computed links and rebuild snapshots from remapped science."""

    result = {name: deepcopy(sections.get(name, [])) for name in COMPUTED_SECTIONS}
    remapped_records = {
        source["id"]: mapped
        for source, mapped in zip(
            sections.get("scientific_records", []),
            remapped_science.get("scientific_records", []),
            strict=True,
        )
    }
    remapped_definitions: dict[str, dict[str, Any]] = {}
    for row in result["computed_metric_definitions"]:
        old_id = row["id"]
        row["id"] = id_map[old_id]
        row["project_id"] = id_map[row["project_id"]]
        if row.get("definition_kind", "scalar") == AGGREGATE_KIND:
            config = deepcopy(row["configuration_json"])
            config["label_class_ids"] = [
                id_map[label_id] for label_id in config.get("label_class_ids", [])
            ]
            row["configuration_json"] = config
            row["definition_sha256"] = content_hash(_aggregate_definition_payload(row))
        elif row.get("definition_kind") == MASK_COVERAGE_KIND:
            config = deepcopy(row["configuration_json"])
            config["label_class_ids"] = [
                id_map[label_id] for label_id in config.get("label_class_ids", [])
            ]
            if config.get("roi_label_class_id") is not None:
                config["roi_label_class_id"] = id_map[config["roi_label_class_id"]]
            row["configuration_json"] = config
            row["definition_sha256"] = content_hash(_aggregate_definition_payload(row))
        elif row.get("definition_kind") == ANNOTATION_COMPARISON_KIND:
            row["configuration_json"] = _remap_identifiers(row["configuration_json"], id_map)
            row["definition_sha256"] = content_hash(_aggregate_definition_payload(row))
        remapped_definitions[old_id] = row
    for row in result["computed_metric_results"]:
        payload = row["payload_json"]
        old_definition_id = row["definition_id"]
        if row.get("result_kind") == ANNOTATION_COMPARISON_KIND:
            mapped_definition = remapped_definitions[old_definition_id]
            payload = _remap_identifiers(payload, id_map)
            comparison = payload["comparison"]
            comparison["content_sha256"] = content_hash(
                {key: value for key, value in comparison.items() if key != "content_sha256"}
            )
            payload["definition_id"] = mapped_definition["id"]
            payload["definition_sha256"] = mapped_definition["definition_sha256"]
            row["payload_json"] = payload
            row["project_id"] = id_map[row["project_id"]]
            row["definition_id"] = mapped_definition["id"]
            row["content_sha256"] = content_hash(payload)
            continue
        if row.get("result_kind", "scalar") == AGGREGATE_KIND:
            mapped_definition = remapped_definitions[old_definition_id]
            payload["definition_id"] = mapped_definition["id"]
            payload["definition_sha256"] = mapped_definition["definition_sha256"]
            for snapshot in payload["image_snapshot"]:
                snapshot["image_id"] = id_map[snapshot["image_id"]]
            payload["image_snapshot"].sort(key=lambda item: item["image_id"])
            for snapshot in payload["observation_snapshot"]:
                snapshot["id"] = id_map[snapshot["id"]]
                snapshot["image_id"] = id_map[snapshot["image_id"]]
                if snapshot.get("label_class_id") is not None:
                    snapshot["label_class_id"] = id_map[snapshot["label_class_id"]]
            payload["observation_snapshot"].sort(key=lambda item: item["id"])
            for class_count in payload["counts_by_class"]:
                if class_count.get("label_class_id") is not None:
                    class_count["label_class_id"] = id_map[class_count["label_class_id"]]
            payload["counts_by_class"].sort(key=lambda item: str(item.get("label_class_id") or ""))
            for group in payload["groups"]:
                if payload["grouping_level"] == "image":
                    group["unit_key"] = id_map[group["unit_key"]]
                # image_group_key is researcher-authored metadata, never an implicit ID link.
                group["image_ids"] = [id_map[image_id] for image_id in group["image_ids"]]
                group["image_ids"].sort()
                for class_count in group["counts_by_class"]:
                    if class_count.get("label_class_id") is not None:
                        class_count["label_class_id"] = id_map[class_count["label_class_id"]]
                group["counts_by_class"].sort(
                    key=lambda item: str(item.get("label_class_id") or "")
                )
            payload["groups"].sort(key=lambda item: item["unit_key"])
            payload["evidence_sha256"] = content_hash(
                {
                    "definition_sha256": mapped_definition["definition_sha256"],
                    "images": payload["image_snapshot"],
                    "observations": payload["observation_snapshot"],
                    "excluded_proposals_by_status": payload["excluded_proposals_by_status"],
                }
            )
            payload["provenance"]["definition_sha256"] = mapped_definition["definition_sha256"]
            payload["provenance"]["evidence_sha256"] = payload["evidence_sha256"]
            row["project_id"] = id_map[row["project_id"]]
            row["definition_id"] = mapped_definition["id"]
            row["content_sha256"] = content_hash(payload)
            continue
        if row.get("result_kind") == MASK_COVERAGE_KIND:
            mapped_definition = remapped_definitions[old_definition_id]
            payload["definition_id"] = mapped_definition["id"]
            payload["definition_sha256"] = mapped_definition["definition_sha256"]
            for snapshot in payload["image_snapshot"]:
                snapshot["image_id"] = id_map[snapshot["image_id"]]
            payload["image_snapshot"].sort(key=lambda item: item["image_id"])
            for snapshot in payload["mask_snapshot"]:
                snapshot["id"] = id_map[snapshot["id"]]
                snapshot["image_id"] = id_map[snapshot["image_id"]]
                if snapshot.get("label_class_id") is not None:
                    snapshot["label_class_id"] = id_map[snapshot["label_class_id"]]
            payload["mask_snapshot"].sort(key=lambda item: item["id"])

            def remap_class_areas(rows: list[dict[str, Any]]) -> None:
                for item in rows:
                    if item.get("label_class_id") is not None:
                        item["label_class_id"] = id_map[item["label_class_id"]]
                rows.sort(key=lambda item: str(item.get("label_class_id") or ""))

            remap_class_areas(payload["area_by_class"])
            for image in payload["images"]:
                old_image_id = image["image_id"]
                image["image_id"] = id_map[old_image_id]
                if payload["grouping_level"] == "image":
                    image["unit_key"] = id_map[old_image_id]
                remap_class_areas(image["area_by_class"])
            payload["images"].sort(key=lambda item: item["image_id"])
            for group in payload["groups"]:
                if payload["grouping_level"] == "image":
                    group["unit_key"] = id_map[group["unit_key"]]
                group["image_ids"] = [id_map[image_id] for image_id in group["image_ids"]]
                group["image_ids"].sort()
                remap_class_areas(group["area_by_class"])
            payload["groups"].sort(key=lambda item: item["unit_key"])
            payload["evidence_sha256"] = content_hash(
                {
                    "definition_sha256": mapped_definition["definition_sha256"],
                    "algorithm": MASK_COVERAGE_ALGORITHM,
                    "coordinate_frame": "source_image_pixels",
                    "images": payload["image_snapshot"],
                    "masks": payload["mask_snapshot"],
                }
            )
            payload["provenance"]["definition_sha256"] = mapped_definition["definition_sha256"]
            payload["provenance"]["evidence_sha256"] = payload["evidence_sha256"]
            row["project_id"] = id_map[row["project_id"]]
            row["definition_id"] = mapped_definition["id"]
            row["content_sha256"] = content_hash(payload)
            continue
        source_snapshots = payload["input_snapshot"]
        mapped_bindings: dict[str, str] = {}
        mapped_snapshots: dict[str, dict[str, Any]] = {}
        mapped_hashes: dict[str, str] = {}
        for symbol, old_record_id in payload["input_record_ids"].items():
            mapped_record = remapped_records[old_record_id]
            new_record_id = id_map[old_record_id]
            mapped_bindings[symbol] = new_record_id
            mapped_snapshots[symbol] = _snapshot(
                {**mapped_record, "id": new_record_id},
                project_id=id_map[row["project_id"]],
                calibration_current=source_snapshots[symbol].get("calibration_current"),
                environmental_snapshot_current=source_snapshots[symbol].get(
                    "environmental_snapshot_current"
                ),
            )
            mapped_hashes[symbol] = mapped_record["content_sha256"]
        payload["definition_id"] = id_map[payload["definition_id"]]
        payload["input_record_ids"] = mapped_bindings
        payload["input_snapshot"] = mapped_snapshots
        subject = next(iter(mapped_snapshots.values()))["subject"]
        payload["subject"] = {key: value for key, value in subject.items() if value is not None}
        payload["provenance"]["input_content_sha256"] = mapped_hashes
        row["content_sha256"] = content_hash(payload)
    return result

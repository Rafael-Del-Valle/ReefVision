"""Paired detector and mask diagnostics on one immutable grouped image test split."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from math import dist, isfinite
from statistics import fmean
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    ImageAsset,
    Job,
    ModelRegistration,
    PredictionProposal,
)
from reefvision.domain.annotation_comparison import (
    BoxEvidence,
    MaskEvidence,
    compare_box_evidence,
    compare_mask_evidence,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.jobs.inference import process_inference_job
from reefvision.schemas.paired_growth_contrast import Digest
from reefvision.schemas.static_comparison import (
    ReferenceAnnotation,
    StaticLineage,
    StaticReferenceImage,
)
from reefvision.services.segmentation_scoring import _verified_runs
from reefvision.services.static_comparison import _model_mapping, reference_image
from reefvision.services.static_comparison_lineage import detector_lineage
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.model_comparison_stills_v15 import read_comparison_raster
from reefvision.storage.static_comparison import verify_static_content

MATCH_IOU = 0.5
MASK_TASKS = {"segment", "semantic_segment"}


class ExecutionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: UUID
    checkpoint_sha256: Digest
    runtime_selection_id: UUID
    runtime_selection_sha256: Digest
    device: Literal["cpu", "cuda"]
    confidence_threshold: FiniteFloat = Field(ge=0, le=1, strict=True)
    iou_threshold: FiniteFloat = Field(ge=0, le=1, strict=True)


@dataclass(frozen=True)
class ModelEvidence:
    choice: ExecutionSelection
    task: str
    labels: list[str]
    mapping: dict[str, UUID | None]
    semantic_indices: dict[str, int]
    lineage: StaticLineage
    class_map: dict[str, Any]


@dataclass(frozen=True)
class ImageTruth:
    item: DatasetVersionItem
    boxes: list[BoxEvidence]
    masks: list[MaskEvidence]
    exclusion: str | None = None


@dataclass(frozen=True)
class ModelOutputs:
    by_image: dict[str, list[PredictionProposal]]
    invalid_images: set[str]
    digest: str


def _dataset_items(session: Session, version: DatasetVersion) -> list[DatasetVersionItem]:
    manifest = version.manifest_json
    snapshots = manifest.get("items")
    if (
        version.status != "complete"
        or not isinstance(snapshots, list)
        or canonical_json_sha256(manifest) != version.manifest_sha256
        or manifest.get("class_map") != version.class_map_json
    ):
        raise ValidationError("Comparison requires a complete immutable dataset manifest")
    if any(
        not isinstance(row, dict) or not isinstance(row.get("image_id"), str) for row in snapshots
    ):
        raise ValidationError("Malformed image membership in the immutable dataset manifest")
    index = {row["image_id"]: row for row in snapshots}
    items = list(
        session.scalars(
            select(DatasetVersionItem)
            .where(DatasetVersionItem.dataset_version_id == version.id)
            .order_by(DatasetVersionItem.image_id)
        )
    )
    if len(items) != len(snapshots) or set(index) != {item.image_id for item in items}:
        raise ValidationError("Image membership differs from the immutable dataset manifest")
    for item in items:
        saved = index[item.image_id]
        expected = {
            "image_sha256": item.image_sha256,
            "width_px": item.width_px,
            "height_px": item.height_px,
            "split": item.split,
            "group_key": item.group_key,
            "annotation_status": item.image_annotation_status,
            "annotations": item.annotation_snapshot_json,
            "annotation_count": item.annotation_count,
        }
        if (
            saved.get("snapshot_sha256") != item.snapshot_sha256
            or canonical_json_sha256(
                {key: value for key, value in saved.items() if key != "snapshot_sha256"}
            )
            != item.snapshot_sha256
            or any(saved.get(key) != value for key, value in expected.items())
            or saved.get("mask_annotations", []) != item.mask_annotation_snapshot_json
            or saved.get("mask_annotation_count", 0) != item.mask_annotation_count
        ):
            raise ValidationError("Frozen image or geometry no longer matches its dataset manifest")
    return items


def _holdout(items: list[DatasetVersionItem]) -> list[DatasetVersionItem]:
    groups: dict[str, tuple[str, str]] = {}
    content: dict[str, str] = {}
    selected = []
    for item in items:
        if item.split == "test":
            if not item.group_key or not item.group_key.strip():
                raise ValidationError("Every test image needs an explicit frozen sampling group")
            selected.append(item)
        if item.group_key:
            identity = (item.group_key, item.split)
            previous = groups.setdefault(item.group_key.strip().casefold(), identity)
            if previous != identity:
                raise ValidationError(
                    "A frozen sampling group crosses splits or has conflicting labels"
                )
        if content.setdefault(item.image_sha256, item.split) != item.split:
            raise ValidationError("Identical image content crosses dataset splits")
    if len({item.image_sha256 for item in selected}) != len(selected):
        raise ValidationError("Duplicated test image bytes cannot count as new evidence")
    if not selected:
        raise ValidationError("The frozen dataset does not contain a test split")
    return selected


def _lineage_reference(item: DatasetVersionItem, task: str) -> StaticReferenceImage:
    reference = reference_image(item)
    if task == "detector":
        return reference
    return reference.model_copy(
        update={
            "annotations": [
                ReferenceAnnotation(
                    id=row["id"],
                    class_id=row["label_class_id"],
                    revision=row["revision"],
                    source_model_id=(row.get("provenance_json") or {}).get("source_model_id"),
                )
                for row in item.mask_annotation_snapshot_json
            ]
        }
    )


def _semantic_indices(model: ModelRegistration, labels: list[str]) -> dict[str, int]:
    if model.task != "semantic_segment":
        return {}
    try:
        entries = model.metadata_json["classes"]
        result = {row["class_name"]: row["class_index"] for row in entries}
        pixel_values = {row["pixel_value"] for row in entries}
        if (
            len(result) != len(entries)
            or len(pixel_values) != len(entries)
            or set(result) != set(labels)
            or len(set(result.values())) != len(entries)
            or any(type(index) is not int or index < 0 for index in result.values())
            or any(type(value) is not int or not 1 <= value <= 255 for value in pixel_values)
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(
            "Semantic model lacks a compatible class and pixel-value map"
        ) from exc
    return result


def _model(
    session: Session,
    settings: Settings,
    project_id: str,
    task: str,
    choice: ExecutionSelection,
    references: Sequence[StaticReferenceImage],
    selection_jobs: Sequence[Job],
    dataset_classes: set[str],
) -> ModelEvidence:
    registration = session.get(ModelRegistration, str(choice.model_id))
    if registration is None or registration.project_id != project_id:
        raise NotFoundError("Comparison model is missing from this project")
    if registration.task not in ({"detect"} if task == "detector" else MASK_TASKS):
        raise ValidationError("The registered model tasks do not support this comparison")
    if registration.sha256 != choice.checkpoint_sha256:
        raise ConflictError("The comparison model checkpoint changed after review")
    verify_static_content(settings, registration.managed_path, choice.checkpoint_sha256, fresh=True)
    labels, mapping = _model_mapping(registration)
    known = {str(value) for value in mapping.values() if value is not None}
    if not known or len(known) != len(labels) or not known.issubset(dataset_classes):
        raise ValidationError("Model classes must map one-to-one to the frozen dataset classes")
    lineage = detector_lineage(
        session, registration, references, selection_jobs, training_task=registration.task
    )
    if lineage.status == "overlap":
        raise ValidationError(
            f"Known holdout overlap for {registration.display_name}; choose disjoint evidence"
        )
    return ModelEvidence(
        choice,
        registration.task,
        labels,
        mapping,
        _semantic_indices(registration, labels),
        lineage,
        deepcopy(registration.class_map_json),
    )


def _verify_image(
    session: Session, settings: Settings, project_id: str, item: DatasetVersionItem
) -> None:
    asset = session.get(ImageAsset, item.image_id)
    if asset is None or asset.project_id != project_id:
        raise NotFoundError("The frozen original image is missing")
    if (
        asset.sha256 != item.image_sha256
        or asset.width_px != item.width_px
        or asset.height_px != item.height_px
    ):
        raise ValidationError("The original image differs from the frozen reference")
    verify_static_content(settings, asset.managed_path, item.image_sha256, fresh=True)


def _box(
    identifier: str, item: DatasetVersionItem, class_id: str, bounds: Sequence[float]
) -> BoxEvidence:
    x0, y0, x1, y1 = bounds
    if not (0 <= x0 < x1 <= item.width_px and 0 <= y0 < y1 <= item.height_px):
        raise ValueError("Box geometry falls outside frozen image bounds")
    return BoxEvidence(identifier, item.image_id, class_id, (x0, y0, x1, y1))


def _mask(
    settings: Settings,
    identifier: str,
    item: DatasetVersionItem,
    class_id: str,
    snapshot: dict[str, Any],
) -> MaskEvidence:
    runs = _verified_runs(
        snapshot,
        width=item.width_px,
        height=item.height_px,
        read_managed_raster=lambda path: read_comparison_raster(settings, path),
    )
    return MaskEvidence(identifier, item.image_id, class_id, item.width_px, item.height_px, runs)


def _truth(
    session: Session,
    settings: Settings,
    project_id: str,
    item: DatasetVersionItem,
    task: str,
    classes: set[str],
) -> ImageTruth:
    if item.image_annotation_status != "reviewed":
        return ImageTruth(item, [], [], "Frozen image is excluded or was not human reviewed")
    snapshots = (
        item.annotation_snapshot_json if task == "detector" else item.mask_annotation_snapshot_json
    )
    other = (
        item.mask_annotation_snapshot_json if task == "detector" else item.annotation_snapshot_json
    )
    if not snapshots and other:
        return ImageTruth(
            item, [], [], "Reviewed image contains only a different annotation geometry"
        )
    try:
        _verify_image(session, settings, project_id, item)
        for row in snapshots:
            if row["label_class_id"] not in classes:
                raise ValidationError("Frozen reference contains a class missing from either model")
            provenance = row.get("provenance_json") or {}
            if row.get("source_type") == "evaluation_only" or provenance.get("evaluation_only"):
                raise ValidationError("Evaluation outputs cannot provide human reference evidence")
            if task == "mask" and row.get("status") != "verified":
                raise ValidationError("Frozen mask is missing human-verified status")
        if task == "detector":
            boxes = [
                _box(
                    row["id"],
                    item,
                    row["label_class_id"],
                    [row["x_min"], row["y_min"], row["x_max"], row["y_max"]],
                )
                for row in snapshots
            ]
            return ImageTruth(item, boxes, [])
        masks = [_mask(settings, row["id"], item, row["label_class_id"], row) for row in snapshots]
        return ImageTruth(item, [], masks)
    except (ValidationError, NotFoundError) as exc:
        return ImageTruth(item, [], [], str(exc))
    except (KeyError, TypeError, ValueError) as exc:
        return ImageTruth(item, [], [], f"Unreadable frozen reference geometry: {exc}")


def _prediction_fields(row: PredictionProposal) -> dict[str, Any]:
    return {
        "image_id": row.image_id,
        "class_id": row.label_class_id,
        "label": row.predicted_label,
        "index": row.predicted_index,
        "confidence": row.confidence,
        "box": [row.x_min, row.y_min, row.x_max, row.y_max],
        "geometry_kind": row.geometry_kind,
        "polygon_json": row.polygon_json,
        "mask_content_sha256": row.mask_content_sha256,
    }


def _run_side(
    session: Session,
    settings: Settings,
    project_id: str,
    model: ModelEvidence,
    image_ids: list[str],
) -> ModelOutputs:
    choice = model.choice.model_dump(mode="json")
    request = {key: value for key, value in choice.items() if key != "checkpoint_sha256"}
    job = Job(
        project_id=project_id,
        job_type="inference",
        status="queued",
        progress_current=0,
        progress_total=len(image_ids),
        request_json={
            **request,
            "model_task": model.task,
            "image_ids": image_ids,
            "evaluation_only": True,
        },
    )
    session.add(job)
    session.commit()
    job_id = job.id
    process_inference_job(
        settings, sessionmaker(bind=session.get_bind(), expire_on_commit=False), job_id
    )
    session.expire_all()
    finished = session.get(Job, job_id)
    if finished is None or finished.status != "succeeded":
        detail = finished.error_message if finished is not None else "inference receipt missing"
        raise ValidationError(
            f"Pinned comparison inference failed: {detail or 'job did not complete'}"
        )
    result = finished.result_json or {}
    rows = session.scalars(
        select(PredictionProposal).where(PredictionProposal.inference_job_id == job_id)
    ).all()
    if (
        finished.progress_current != len(image_ids)
        or finished.request_json.get("image_ids") != image_ids
        or result.get("proposal_count") != len(rows)
    ):
        raise ValidationError("Pinned inference output is incomplete")
    ranked = sorted(
        ((canonical_json_sha256(_prediction_fields(row)), row) for row in rows),
        key=lambda item: item[0],
    )
    by_image: dict[str, list[PredictionProposal]] = defaultdict(list)
    invalid: set[str] = set()
    allowed = set(image_ids)
    for _, row in ranked:
        if row.image_id not in allowed:
            raise ValidationError("Inference produced an output for a foreign frozen image")
        provenance = row.provenance_json or {}
        if (
            row.project_id != project_id
            or row.model_id != str(model.choice.model_id)
            or row.model_checksum != model.choice.checkpoint_sha256
            or row.review_status != "evaluation_only"
            or provenance.get("evaluation_only") is not True
            or provenance.get("runtime_selection_id") != str(model.choice.runtime_selection_id)
            or provenance.get("runtime_selection_sha256") != model.choice.runtime_selection_sha256
            or provenance.get("model_task") != model.task
        ):
            raise ValidationError("Inference output differs from the reviewed comparison pins")
        mapped = model.mapping.get(row.predicted_label)
        expected_index = model.semantic_indices.get(row.predicted_label)
        if expected_index is None and row.predicted_label in model.labels:
            expected_index = model.labels.index(row.predicted_label)
        if (
            mapped is None
            or str(mapped) != row.label_class_id
            or (row.predicted_index is not None and row.predicted_index != expected_index)
            or not isfinite(row.confidence)
            or not 0 <= row.confidence <= 1
        ):
            invalid.add(row.image_id)
        if model.task == "semantic_segment" or row.confidence >= model.choice.confidence_threshold:
            by_image[row.image_id].append(row)
    errors = result.get("invalid_prediction_errors") or []
    if result.get("invalid_prediction_count"):
        failed = {str(error).split(" ")[1] for error in errors if str(error).startswith("Image ")}
        invalid.update(
            failed
            if len(errors) == result["invalid_prediction_count"] and failed <= allowed
            else allowed
        )
    return ModelOutputs(
        dict(by_image),
        invalid,
        canonical_json_sha256(
            {
                "choice": choice,
                "predictions": [digest for digest, _ in ranked],
                "invalid_images": sorted(invalid),
            }
        ),
    )


def _center(box: BoxEvidence) -> tuple[float, float]:
    x0, y0, x1, y1 = box.bounds
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def _box_values(
    image: ImageTruth, predictions: list[PredictionProposal]
) -> dict[str, tuple[str, float | None]]:
    boxes = [
        _box(
            f"prediction-{index}",
            image.item,
            str(row.label_class_id),
            [row.x_min, row.y_min, row.x_max, row.y_max],
        )
        for index, row in enumerate(predictions)
        if row.geometry_kind == "bounding_box"
    ]
    if len(boxes) != len(predictions):
        raise ValueError("Detector returned non-box geometry")
    report = compare_box_evidence(image.boxes, boxes, iou_threshold=MATCH_IOU, reference_side="a")
    matches = [match for cls in report.per_class.values() for match in cls.matches]
    truth_by_id = {box.evidence_id: box for box in image.boxes}
    prediction_by_id = {box.evidence_id: box for box in boxes}
    count_error = len(boxes) - len(image.boxes)
    return {
        "false_detections": ("count", len(boxes) - len(matches)),
        "missed_detections": ("count", len(image.boxes) - len(matches)),
        "signed_count_error": ("count", count_error),
        "absolute_count_error": ("count", abs(count_error)),
        "matched_box_iou": ("ratio", fmean(match.iou for match in matches) if matches else None),
        "matched_center_error": (
            "px",
            fmean(
                dist(
                    _center(truth_by_id[match.source_a_id]),
                    _center(prediction_by_id[match.source_b_id]),
                )
                for match in matches
            )
            if matches
            else None,
        ),
    }


def _mask_values(
    settings: Settings,
    image: ImageTruth,
    predictions: list[PredictionProposal],
    *,
    instances: bool,
) -> dict[str, tuple[str, float | None]]:
    masks = [
        _mask(
            settings,
            f"prediction-{index}",
            image.item,
            str(row.label_class_id),
            _prediction_fields(row) | {"mask_path": row.mask_path},
        )
        for index, row in enumerate(predictions)
    ]
    report = compare_mask_evidence(image.masks, masks, iou_threshold=MATCH_IOU, reference_side="a")
    rows = list(report.per_class.values())
    intersection = sum(row.intersection_area_pixels for row in rows)
    union = sum(row.union_area_pixels for row in rows)
    coverage = sum(row.union_area_a_pixels + row.union_area_b_pixels for row in rows)
    values: dict[str, tuple[str, float | None]] = {
        "mask_iou": ("ratio", intersection / union if union else None),
        "mask_dice": ("ratio", 2 * intersection / coverage if coverage else None),
    }
    if instances:
        matches = [match for row in rows for match in row.matches]
        values.update(
            {
                "false_instances": ("count", len(masks) - len(matches)),
                "missed_instances": ("count", len(image.masks) - len(matches)),
                "absolute_instance_count_error": ("count", abs(len(masks) - len(image.masks))),
                "matched_instance_mask_iou": (
                    "ratio",
                    fmean(match.iou for match in matches) if matches else None,
                ),
            }
        )
    return values


def _observation(
    session: Session,
    settings: Settings,
    project_id: str,
    task: str,
    image: ImageTruth,
    first: ModelOutputs,
    second: ModelOutputs,
    *,
    instances: bool,
) -> dict[str, Any]:
    identifier = image.item.image_id
    result: dict[str, Any] = {"media_kind": "image", "media_id": identifier, "metrics": []}
    if image.exclusion:
        return {**result, "exclusion": image.exclusion}
    if identifier in first.invalid_images or identifier in second.invalid_images:
        return {
            **result,
            "exclusion": "A compared model returned invalid geometry or class evidence",
        }
    try:
        _verify_image(session, settings, project_id, image.item)
        left, right = [
            _box_values(image, output.by_image.get(identifier, []))
            if task == "detector"
            else _mask_values(
                settings, image, output.by_image.get(identifier, []), instances=instances
            )
            for output in (first, second)
        ]
    except (ValidationError, NotFoundError, ValueError) as exc:
        return {**result, "exclusion": f"Paired image evidence unavailable: {exc}"}
    result["metrics"] = [
        {"name": name, "unit": unit, "left": value, "right": right[name][1]}
        for name, (unit, value) in left.items()
    ]
    return result


def compare_image_models(
    session: Session,
    settings: Settings,
    project_id: str,
    task: str,
    source_ids: Mapping[str, Any],
    selections: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if (
        task not in {"detector", "mask"}
        or set(source_ids) != {"dataset_version_id"}
        or len(selections) != 2
    ):
        raise ValidationError("Choose two compatible image models and one reviewed dataset")
    try:
        choices = [ExecutionSelection.model_validate(row) for row in selections]
        dataset_id = str(UUID(str(source_ids["dataset_version_id"])))
    except ValueError as exc:
        raise ValidationError(
            "Comparison requires reviewed model and dataset UUIDs and digests"
        ) from exc
    if choices[0].model_id == choices[1].model_id:
        raise ValidationError("Choose two distinct registered models")
    version = session.get(DatasetVersion, dataset_id)
    if version is None or version.project_id != project_id:
        raise NotFoundError("Reviewed dataset version is missing from this project")
    reference_sha256 = version.manifest_sha256
    all_items = _dataset_items(session, version)
    items = _holdout(all_items)
    classes = {str(row["id"]) for row in version.class_map_json}
    try:
        references = [_lineage_reference(item, task) for item in items]
    except (AttributeError, ValueError, KeyError, TypeError) as exc:
        raise ValidationError("Frozen annotation provenance is malformed") from exc
    selection_jobs = list(
        session.scalars(
            select(Job).where(
                Job.project_id == project_id,
                Job.status == "succeeded",
                Job.job_type.in_(("learning_evaluation", "segmentation_learning_evaluation")),
            )
        )
    )
    left, right = [
        _model(session, settings, project_id, task, choice, references, selection_jobs, classes)
        for choice in choices
    ]
    if set(left.mapping.values()) != set(right.mapping.values()):
        raise ValidationError("Both models must cover the same frozen project classes")
    comparison_classes = {str(value) for value in left.mapping.values()}
    if any(
        str(row.class_id) not in comparison_classes
        for image in references
        if not image.exclusion
        for row in image.annotations
    ):
        raise ValidationError("A reviewed test reference class is missing from both model maps")
    frozen_datasets = {dataset_id: all_items}
    holdout_groups = {
        image.group_key.strip().casefold()
        for image in references
        if image.exclusion is None and image.group_key
    }
    for model in (left, right):
        for dataset in model.lineage.datasets:
            identifier = str(dataset.id)
            if identifier not in frozen_datasets:
                upstream = session.get(DatasetVersion, identifier)
                if upstream is None or upstream.project_id != project_id:
                    raise ConflictError("Recorded training or selection evidence is unavailable")
                frozen_datasets[identifier] = _dataset_items(session, upstream)
            if any(
                item.split in dataset.splits
                and item.group_key
                and item.group_key.strip().casefold() in holdout_groups
                for item in frozen_datasets[identifier]
            ):
                raise ValidationError(
                    "Recorded training or model selection has sampling group overlap"
                )
    truth = [
        _truth(session, settings, project_id, item, task, comparison_classes) for item in items
    ]
    if not any(image.boxes or image.masks for image in truth):
        raise ValidationError(
            "The reviewed test split has no usable positive reference for this task"
        )
    targets = [image.item.image_id for image in truth if image.exclusion is None]
    first, second = (
        _run_side(session, settings, project_id, model, targets) for model in (left, right)
    )
    for model in (left, right):
        registration = session.get(ModelRegistration, str(model.choice.model_id))
        if (
            registration is None
            or registration.class_map_json != model.class_map
            or registration.sha256 != model.choice.checkpoint_sha256
        ):
            raise ConflictError("A model registration changed during paired inference")
    if version.manifest_sha256 != reference_sha256:
        raise ConflictError("Dataset manifest changed during paired inference")
    _dataset_items(session, version)
    instances = left.task == right.task == "segment"
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for image in truth:
        assert image.item.group_key is not None
        groups[image.item.group_key].append(
            _observation(
                session, settings, project_id, task, image, first, second, instances=instances
            )
        )
    held_out = left.lineage.status == right.lineage.status == "held_out"
    limitations = [
        "Analysis units are frozen sampling groups. Verify biological independence separately.",
        "Model outputs remain isolated as evaluation evidence.",
    ]
    if not held_out:
        limitations.append(
            "Exploratory diagnostic. Held-out status requires complete disjoint ancestry "
            "for both checkpoints."
        )
    if task == "mask" and not instances:
        limitations.append(
            "Semantic maps define foreground pixels by class. "
            "This comparison scores pixel coverage."
        )
    method = (
        "Per-image source-pixel box counts and one-to-one class-aware matching at IoU ≥ 0.5."
        if task == "detector"
        else "Per-image IoU and Dice from source-pixel foreground unions, summed across classes."
    )
    if instances:
        method += " Instance metrics use one-to-one class-aware matching at IoU ≥ 0.5."
    return {
        "reference_id": dataset_id,
        "reference_sha256": reference_sha256,
        "source_sha256": [
            left.choice.checkpoint_sha256,
            right.choice.checkpoint_sha256,
            left.choice.runtime_selection_sha256,
            right.choice.runtime_selection_sha256,
            first.digest,
            second.digest,
        ],
        "groups": [{"group_id": key, "observations": rows} for key, rows in sorted(groups.items())],
        "method": method,
        "limitations": limitations,
        "evaluation_status": "held_out" if held_out else "exploratory",
        "lineage": [
            {"model_id": str(model.choice.model_id), **model.lineage.model_dump(mode="json")}
            for model in (left, right)
        ],
    }

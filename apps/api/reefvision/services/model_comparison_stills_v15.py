"""Paired detector and mask diagnostics on one immutable grouped image test split."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from math import dist, isfinite
from statistics import fmean
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
from reefvision.repositories.jobs import paired_owner_active
from reefvision.schemas.image_adjustments_v18 import ImageAdjustmentPin, ImageAdjustmentRecord
from reefvision.schemas.paired_growth_contrast import Digest
from reefvision.schemas.static_comparison import (
    ReferenceAnnotation,
    StaticLineage,
    StaticReferenceImage,
)
from reefvision.services.image_adjustments_v18 import (
    ImageAdjustmentService,
    adjusted_inference_binding,
    adjusted_input_provenance,
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
    job_id: str
    by_image: dict[str, list[PredictionProposal]]
    invalid_images: set[str]
    digest: str
    child_job_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecordedImageRuns:
    job_ids: tuple[str, str] | None
    read_raster: Callable[[str], bytes]
    original_ids: Mapping[str, str]
    cutoff: datetime
    legacy_digests: tuple[str, str] | None = None
    started_at: datetime | None = None
    adjusted_jobs: tuple[Mapping[str, str], Mapping[str, str]] | None = None
    adjusted_records: Mapping[str, ImageAdjustmentRecord] | None = None


class UnverifiedLegacyInference(ValidationError):
    """An older receipt cannot be linked to a unique pair of frozen worker outputs."""


class ComparisonLineageOverlap(ValidationError):
    """Known training or model selection exposure invalidates a holdout."""


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
    settings: Settings | None,
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
    if settings is not None:
        verify_static_content(
            settings, registration.managed_path, choice.checkpoint_sha256, fresh=True
        )
    labels, mapping = _model_mapping(registration)
    known = {str(value) for value in mapping.values() if value is not None}
    if not known or len(known) != len(labels) or not known.issubset(dataset_classes):
        raise ValidationError("Model classes must map one-to-one to the frozen dataset classes")
    lineage = detector_lineage(
        session, registration, references, selection_jobs, training_task=registration.task
    )
    if lineage.status == "overlap":
        raise ComparisonLineageOverlap(
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
    session: Session, settings: Settings | None, project_id: str, item: DatasetVersionItem
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
    if settings is not None:
        verify_static_content(settings, asset.managed_path, item.image_sha256, fresh=True)


def _box(
    identifier: str, item: DatasetVersionItem, class_id: str, bounds: Sequence[float]
) -> BoxEvidence:
    x0, y0, x1, y1 = bounds
    if not (0 <= x0 < x1 <= item.width_px and 0 <= y0 < y1 <= item.height_px):
        raise ValueError("Box geometry falls outside frozen image bounds")
    return BoxEvidence(identifier, item.image_id, class_id, (x0, y0, x1, y1))


def _mask(
    read_raster: Callable[[str], bytes],
    identifier: str,
    item: DatasetVersionItem,
    class_id: str,
    snapshot: dict[str, Any],
) -> MaskEvidence:
    runs = _verified_runs(
        snapshot,
        width=item.width_px,
        height=item.height_px,
        read_managed_raster=read_raster,
    )
    return MaskEvidence(identifier, item.image_id, class_id, item.width_px, item.height_px, runs)


def _truth(
    session: Session,
    settings: Settings | None,
    project_id: str,
    item: DatasetVersionItem,
    task: str,
    classes: set[str],
    read_raster: Callable[[str], bytes],
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
        masks = [
            _mask(read_raster, row["id"], item, row["label_class_id"], row) for row in snapshots
        ]
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


def _require_active_owner(session: Session, project_id: str, owner_run_id: str | None) -> None:
    if owner_run_id is not None and not paired_owner_active(session, project_id, owner_run_id):
        raise ConflictError("The paired comparison was stopped before its inference completed")


def _inference_child(
    session: Session,
    project_id: str,
    request: dict[str, Any],
    owner_run_id: str | None,
    reference_sha256: str,
) -> Job:
    deduplication_key = None
    if owner_run_id is not None:
        request["paired_owner_run_id"] = owner_run_id
        deduplication_key = canonical_json_sha256(
            {
                "method": "paired-image-inference.v1",
                "project_id": project_id,
                "reference_sha256": reference_sha256,
                "request": request,
            }
        )
        existing = session.scalar(select(Job).where(Job.deduplication_key == deduplication_key))
        if existing is not None:
            return existing
    job = Job(
        project_id=project_id,
        job_type="inference",
        status="queued",
        progress_current=0,
        progress_total=len(request["image_ids"]),
        request_json=request,
        deduplication_key=deduplication_key,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if deduplication_key is not None:
            existing = session.scalar(select(Job).where(Job.deduplication_key == deduplication_key))
            if existing is not None:
                return existing
        raise
    return job


def _run_side(
    session: Session,
    settings: Settings | None,
    project_id: str,
    model: ModelEvidence,
    image_ids: list[str],
    *,
    recorded_job_id: str | None = None,
    original_ids: Mapping[str, str] | None = None,
    owner_run_id: str | None = None,
    reference_sha256: str,
    legacy_digest: bool = False,
    adjustment: ImageAdjustmentPin | None = None,
    archived_adjustment: ImageAdjustmentRecord | None = None,
) -> ModelOutputs:
    choice = model.choice.model_dump(mode="json")
    request = {key: value for key, value in choice.items() if key != "checkpoint_sha256"}
    expected_request = {
        **request,
        "model_task": model.task,
        "image_ids": image_ids,
        "evaluation_only": True,
    }
    expected_input = None
    if adjustment is not None:
        if len(image_ids) != 1:
            raise ValidationError("Each adjusted evaluation job requires one original image")
        if archived_adjustment is None:
            assert settings is not None
            checkpoint = session.get(ModelRegistration, str(model.choice.model_id))
            if checkpoint is None:
                raise NotFoundError("The reviewed adjustment evaluation model is unavailable")
            expected_request.update(
                adjusted_inference_binding(
                    session, settings, project_id, image_ids, adjustment, checkpoint
                )
            )
            record = ImageAdjustmentService(session, settings).get(
                image_ids[0], str(adjustment.recipe_id)
            )
            expected_input = adjusted_input_provenance(record)
        else:
            if not recorded_job_id:
                raise ValidationError("An archived adjustment requires its actual inference job")
            expected_request.update(
                image_adjustment=adjustment.model_dump(mode="json"),
                checkpoint_sha256=choice["checkpoint_sha256"],
            )
            expected_input = adjusted_input_provenance(archived_adjustment)
            expected_input["recipe_id"] = (original_ids or {}).get(
                expected_input["recipe_id"], expected_input["recipe_id"]
            )
    if recorded_job_id is not None:
        job_id = recorded_job_id
    else:
        assert settings is not None
        _require_active_owner(session, project_id, owner_run_id)
        job = _inference_child(
            session, project_id, expected_request, owner_run_id, reference_sha256
        )
        job_id = job.id
        if job.status == "queued":
            process_inference_job(
                settings, sessionmaker(bind=session.get_bind(), expire_on_commit=False), job_id
            )
            session.expire_all()
        _require_active_owner(session, project_id, owner_run_id)
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
        finished.project_id != project_id
        or finished.job_type != "inference"
        or finished.progress_current != len(image_ids)
        or finished.progress_total != len(image_ids)
        or any(
            finished.request_json.get(key) != value
            for key, value in expected_request.items()
            if key != "image_ids"
        )
        or sorted(finished.request_json.get("image_ids", [])) != sorted(image_ids)
        or result.get("proposal_count") != len(rows)
        or ("image_adjustment" in finished.request_json and adjustment is None)
        or result.get("model_input") != expected_input
    ):
        raise ValidationError("Pinned inference output is incomplete")
    archived = original_ids or {}

    def digest_fields(row: PredictionProposal) -> dict[str, Any]:
        fields = _prediction_fields(row)
        # The reviewed model's label map independently binds the class identity.
        if legacy_digest:
            if row.label_class_id is not None:
                fields["class_id"] = archived.get(row.label_class_id, row.label_class_id)
        else:
            fields.pop("class_id")
        fields["image_id"] = archived.get(row.image_id, row.image_id)
        return fields

    ranked = sorted(
        ((canonical_json_sha256(digest_fields(row)), row) for row in rows),
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
            or provenance.get("model_input") != expected_input
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
        job_id,
        dict(by_image),
        invalid,
        canonical_json_sha256(
            {
                "choice": {
                    **choice,
                    **{
                        key: archived.get(choice[key], choice[key])
                        for key in ("model_id", "runtime_selection_id")
                    },
                },
                "predictions": [digest for digest, _ in ranked],
                "invalid_images": sorted(
                    archived.get(identifier, identifier) for identifier in invalid
                ),
                **(
                    {
                        "image_adjustment": {
                            **adjustment.model_dump(mode="json"),
                            "recipe_id": archived.get(
                                str(adjustment.recipe_id), str(adjustment.recipe_id)
                            ),
                        }
                    }
                    if adjustment
                    else {}
                ),
            }
        ),
    )


def _run_adjusted_side(
    session: Session,
    settings: Settings | None,
    project_id: str,
    model: ModelEvidence,
    targets: list[str],
    pins: Mapping[str, ImageAdjustmentPin],
    owner_run_id: str | None,
    reference_sha256: str,
    *,
    archived: RecordedImageRuns | None = None,
    side: int = 0,
) -> ModelOutputs:
    old_ids = archived.original_ids if archived else {}
    archive_jobs = archived.adjusted_jobs[side] if archived and archived.adjusted_jobs else {}
    archive_records = archived.adjusted_records if archived and archived.adjusted_records else {}
    outcomes = [
        _run_side(
            session,
            settings,
            project_id,
            model,
            [image_id],
            owner_run_id=owner_run_id,
            reference_sha256=reference_sha256,
            adjustment=pins[image_id],
            recorded_job_id=archive_jobs.get(image_id),
            original_ids=old_ids,
            archived_adjustment=archive_records.get(image_id),
        )
        for image_id in sorted(targets, key=lambda identifier: old_ids.get(identifier, identifier))
    ]
    return ModelOutputs(
        outcomes[0].job_id,
        {key: rows for outcome in outcomes for key, rows in outcome.by_image.items()},
        set().union(*(item.invalid_images for item in outcomes)),
        canonical_json_sha256({"adjusted_scores": [item.digest for item in outcomes]}),
        tuple(item.job_id for item in outcomes),
    )


def _resolve_legacy_side(
    session: Session,
    project_id: str,
    model: ModelEvidence,
    targets: list[str],
    reference_sha256: str,
    recorded: RecordedImageRuns,
    digest: str,
) -> ModelOutputs:
    query = select(Job).where(
        Job.project_id == project_id,
        Job.job_type == "inference",
        Job.status == "succeeded",
        Job.completed_at <= recorded.cutoff,
        Job.request_json["runtime_selection_id"].as_string()
        == str(model.choice.runtime_selection_id),
    )
    if recorded.started_at is not None:
        query = query.where(Job.created_at >= recorded.started_at)
    matches: list[ModelOutputs] = []
    for job in session.scalars(query):
        try:
            result = _run_side(
                session,
                None,
                project_id,
                model,
                targets,
                recorded_job_id=job.id,
                original_ids=recorded.original_ids,
                legacy_digest=True,
                reference_sha256=reference_sha256,
            )
        except ValidationError:
            continue
        if result.digest == digest:
            matches.append(result)
            if len(matches) > 1:
                break
    if len(matches) != 1:
        raise UnverifiedLegacyInference(
            "Older comparison cannot be verified uniquely. Use the original project "
            "with both evaluation jobs and original media, or create a new comparison."
        )
    return matches[0]


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
    read_raster: Callable[[str], bytes],
    image: ImageTruth,
    predictions: list[PredictionProposal],
    *,
    instances: bool,
) -> dict[str, tuple[str, float | None]]:
    masks = [
        _mask(
            read_raster,
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
    settings: Settings | None,
    project_id: str,
    task: str,
    image: ImageTruth,
    first: ModelOutputs,
    second: ModelOutputs,
    *,
    instances: bool,
    read_raster: Callable[[str], bytes],
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
                read_raster, image, output.by_image.get(identifier, []), instances=instances
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
    settings: Settings | None,
    project_id: str,
    task: str,
    source_ids: Mapping[str, Any],
    selections: Sequence[Mapping[str, Any]],
    *,
    recorded: RecordedImageRuns | None = None,
    owner_run_id: str | None = None,
    adjusted_inputs: Mapping[str, ImageAdjustmentPin] | None = None,
) -> dict[str, Any]:
    _require_active_owner(session, project_id, owner_run_id)
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
    if recorded is None:
        assert settings is not None

        def read_live_raster(path: str) -> bytes:
            return read_comparison_raster(settings, path)

        read_raster: Callable[[str], bytes] = read_live_raster
    else:
        read_raster = recorded.read_raster
    selection_query = select(Job).where(
        Job.project_id == project_id,
        Job.status == "succeeded",
        Job.job_type.in_(("learning_evaluation", "segmentation_learning_evaluation")),
    )
    if recorded is not None:
        selection_query = selection_query.where(Job.completed_at <= recorded.cutoff)
    selection_jobs = list(session.scalars(selection_query))
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
                raise ComparisonLineageOverlap(
                    "Recorded training or model selection has sampling group overlap"
                )
    truth = [
        _truth(session, settings, project_id, item, task, comparison_classes, read_raster)
        for item in items
    ]
    if not any(image.boxes or image.masks for image in truth):
        if recorded is not None and recorded.legacy_digests is not None:
            raise UnverifiedLegacyInference(
                "The legacy comparison's reference originals are unavailable"
            )
        raise ValidationError(
            "The reviewed test split has no usable positive reference for this task"
        )
    targets = [image.item.image_id for image in truth if image.exclusion is None]
    if adjusted_inputs is not None:
        if set(adjusted_inputs) != set(targets):
            raise ValidationError("Select a pinned adjustment for every usable frozen test image")
        if recorded is None:
            assert settings is not None
            service = ImageAdjustmentService(session, settings)
            recipe_records = [
                service.verified_input(project_id, image_id, pin)[1]
                for image_id, pin in adjusted_inputs.items()
            ]
        else:
            if (
                recorded.adjusted_jobs is None
                or recorded.adjusted_records is None
                or any(set(side) != set(targets) for side in recorded.adjusted_jobs)
                or set(recorded.adjusted_records) != set(targets)
            ):
                raise ValidationError(
                    "Archived adjusted scores are missing a required recipe or job"
                )
            recipe_records = list(recorded.adjusted_records.values())
        parameters = {
            canonical_json_sha256(record.receipt.parameters.model_dump())
            for record in recipe_records
        }
        if len(parameters) != 1:
            raise ValidationError("Both acquisition domains must use the same adjustment settings")
    outputs = []
    for index, model in enumerate((left, right)):
        if adjusted_inputs is not None:
            outcome = _run_adjusted_side(
                session,
                settings,
                project_id,
                model,
                targets,
                adjusted_inputs,
                owner_run_id,
                reference_sha256,
                archived=recorded,
                side=index,
            )
        elif recorded is not None and recorded.job_ids is None:
            if recorded.legacy_digests is None:
                raise UnverifiedLegacyInference("Both archived inference jobs are required")
            outcome = _resolve_legacy_side(
                session,
                project_id,
                model,
                targets,
                reference_sha256,
                recorded,
                recorded.legacy_digests[index],
            )
        else:
            outcome = _run_side(
                session,
                settings,
                project_id,
                model,
                targets,
                recorded_job_id=recorded.job_ids[index] if recorded and recorded.job_ids else None,
                original_ids=recorded.original_ids if recorded else None,
                owner_run_id=owner_run_id,
                reference_sha256=reference_sha256,
            )
        outputs.append(outcome)
    first, second = outputs
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
                session,
                settings,
                project_id,
                task,
                image,
                first,
                second,
                instances=instances,
                read_raster=read_raster,
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
        "inference_job_ids": [
            *(first.child_job_ids or (first.job_id,)),
            *(second.child_job_ids or (second.job_id,)),
        ],
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

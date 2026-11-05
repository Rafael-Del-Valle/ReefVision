"""Project-scoped comparison of reviewed annotations and pinned prediction jobs."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import asdict
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Annotation, ImageAsset, MaskAnnotation, PredictionProposal
from reefvision.db.models.computed_metric import ComputedMetricDefinition, ComputedMetricResult
from reefvision.domain.annotation_comparison import (
    BoxComparison,
    BoxEvidence,
    MaskComparison,
    MaskEvidence,
    compare_box_evidence,
    compare_mask_evidence,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.annotation_comparison import (
    AnnotationComparisonCalculateRequest,
    AnnotationComparisonPreviewRequest,
    AnnotationComparisonPreviewResponse,
    AnnotationComparisonSavedResponse,
    AnnotationComparisonSource,
    AnnotationComparisonValidationResponse,
)
from reefvision.services.scientific_data import content_hash
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.segmentation_metric_masks import png_to_runs, polygon_to_runs

MAX_COMPARISON_EVIDENCE = 25_000
DEFINITION_KIND = "annotation_comparison"
BOX_FORMULA_VERSION = "reefvision.annotation-comparison.v1"
MASK_FORMULA_VERSION = "reefvision.annotation-comparison.v2"


class AnnotationComparisonService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _mask_runs(
        self,
        *,
        geometry_kind: str,
        polygon: list[list[float]] | None,
        mask_path: str | None,
        expected_sha256: str | None,
        image: ImageAsset,
        evidence_id: str,
    ) -> tuple[tuple[tuple[int, int, int], ...], str | None]:
        try:
            if geometry_kind in {"polygon", "polygon_mask"}:
                if not polygon:
                    raise ValueError("polygon geometry is missing")
                return (
                    polygon_to_runs(polygon, width=image.width_px, height=image.height_px),
                    None,
                )
            if geometry_kind == "raster_mask":
                if not mask_path:
                    raise ValueError("raster mask content is missing")
                payload = resolve_managed_project_path(self.settings, mask_path).read_bytes()
                digest = hashlib.sha256(payload).hexdigest()
                if expected_sha256 is not None and digest != expected_sha256:
                    raise ValueError("raster mask checksum differs from pinned evidence")
                return (
                    png_to_runs(payload, width=image.width_px, height=image.height_px),
                    digest,
                )
        except (OSError, ValueError) as exc:
            raise ValidationError(f"Mask evidence is unreadable or invalid: {evidence_id}") from exc
        raise ValidationError(f"Mask evidence geometry is unsupported: {evidence_id}")

    def _source_snapshot(
        self,
        *,
        project_id: str,
        image: ImageAsset,
        source: AnnotationComparisonSource,
        geometry_kind: str,
    ) -> list[dict[str, object]]:
        if source.kind == "reviewed_boxes":
            if image.annotation_status != "reviewed":
                return []
            annotation_rows = self.session.scalars(
                select(Annotation)
                .where(Annotation.image_id == image.id, Annotation.deleted_at.is_(None))
                .order_by(Annotation.id)
            ).all()
            return [
                {
                    "evidence_id": row.id,
                    "image_id": row.image_id,
                    "class_id": row.label_class_id,
                    "bounds": [row.x_min, row.y_min, row.x_max, row.y_max],
                    "revision": row.revision,
                    "source_type": row.source_type,
                }
                for row in annotation_rows
            ]
        if source.kind == "verified_masks":
            requested_ids = [str(value) for value in source.mask_annotation_ids]
            mask_rows = self.session.scalars(
                select(MaskAnnotation)
                .where(MaskAnnotation.id.in_(requested_ids))
                .order_by(MaskAnnotation.id)
            ).all()
            if len(mask_rows) != len(requested_ids) or any(
                mask_row.image_id != image.id
                or mask_row.deleted_at is not None
                or mask_row.status != "verified"
                for mask_row in mask_rows
            ):
                raise ValidationError(
                    "All selected masks must be current verified masks on the project image"
                )
            snapshots: list[dict[str, object]] = []
            for mask_row in mask_rows:
                runs, raster_sha256 = self._mask_runs(
                    geometry_kind=mask_row.geometry_kind,
                    polygon=mask_row.polygon_json,
                    mask_path=mask_row.mask_path,
                    expected_sha256=None,
                    image=image,
                    evidence_id=mask_row.id,
                )
                snapshots.append(
                    {
                        "evidence_id": mask_row.id,
                        "image_id": mask_row.image_id,
                        "class_id": mask_row.label_class_id or "unmapped:unlabeled",
                        "width_px": image.width_px,
                        "height_px": image.height_px,
                        "runs": [list(run) for run in runs],
                        "geometry_kind": mask_row.geometry_kind,
                        "raster_content_sha256": raster_sha256,
                        "revision": mask_row.revision,
                        "status": mask_row.status,
                        "source_type": mask_row.source_type,
                        "provenance": mask_row.provenance_json,
                    }
                )
            return snapshots
        prediction_rows = self.session.scalars(
            select(PredictionProposal)
            .where(
                PredictionProposal.project_id == project_id,
                PredictionProposal.image_id == image.id,
                PredictionProposal.inference_job_id == str(source.prediction_job_id),
                (
                    PredictionProposal.geometry_kind == "bounding_box"
                    if geometry_kind == "boxes"
                    else PredictionProposal.geometry_kind.in_(
                        ("polygon", "polygon_mask", "raster_mask")
                    )
                ),
            )
            .order_by(PredictionProposal.id)
        ).all()
        if not prediction_rows:
            raise NotFoundError(
                f"Prediction job has no {geometry_kind} evidence for the project image"
            )
        if geometry_kind == "masks":
            snapshots = []
            for proposal in prediction_rows:
                runs, raster_sha256 = self._mask_runs(
                    geometry_kind=proposal.geometry_kind,
                    polygon=proposal.polygon_json,
                    mask_path=proposal.mask_path,
                    expected_sha256=proposal.mask_content_sha256,
                    image=image,
                    evidence_id=proposal.id,
                )
                snapshots.append(
                    {
                        "evidence_id": proposal.id,
                        "image_id": proposal.image_id,
                        "class_id": (
                            proposal.label_class_id or f"unmapped:{proposal.predicted_label}"
                        ),
                        "width_px": image.width_px,
                        "height_px": image.height_px,
                        "runs": [list(run) for run in runs],
                        "geometry_kind": proposal.geometry_kind,
                        "raster_content_sha256": raster_sha256,
                        "model_id": proposal.model_id,
                        "model_checksum": proposal.model_checksum,
                        "prediction_job_id": proposal.inference_job_id,
                        "confidence": proposal.confidence,
                        "review_status": proposal.review_status,
                        "inference_settings": proposal.inference_settings_json,
                        "provenance": proposal.provenance_json,
                    }
                )
            return snapshots
        return [
            {
                "evidence_id": row.id,
                "image_id": row.image_id,
                "class_id": row.label_class_id or f"unmapped:{row.predicted_label}",
                "bounds": [row.x_min, row.y_min, row.x_max, row.y_max],
                "model_id": row.model_id,
                "model_checksum": row.model_checksum,
                "prediction_job_id": row.inference_job_id,
                "confidence": row.confidence,
                "review_status": row.review_status,
            }
            for row in prediction_rows
        ]

    def preview(
        self, project_id: str, request: AnnotationComparisonPreviewRequest
    ) -> AnnotationComparisonPreviewResponse:
        image = self.session.get(ImageAsset, str(request.image_id))
        if image is None or image.project_id != project_id:
            raise NotFoundError("Project image not found")
        snapshot_a = self._source_snapshot(
            project_id=project_id,
            image=image,
            source=request.source_a,
            geometry_kind=request.geometry_kind,
        )
        snapshot_b = self._source_snapshot(
            project_id=project_id,
            image=image,
            source=request.source_b,
            geometry_kind=request.geometry_kind,
        )
        if len(snapshot_a) + len(snapshot_b) > MAX_COMPARISON_EVIDENCE:
            raise ValidationError("Annotation comparison evidence limit exceeded")

        def evidence(rows: list[dict[str, object]]) -> list[BoxEvidence]:
            values = []
            for row in rows:
                raw_bounds = row["bounds"]
                if not isinstance(raw_bounds, list) or len(raw_bounds) != 4:
                    raise ValidationError("Annotation comparison bounds are invalid")
                bounds = cast(
                    tuple[float, float, float, float],
                    tuple(float(value) for value in raw_bounds),
                )
                values.append(
                    BoxEvidence(
                        evidence_id=str(row["evidence_id"]),
                        image_id=str(row["image_id"]),
                        class_id=str(row["class_id"]),
                        bounds=bounds,
                    )
                )
            return values

        comparison: BoxComparison | MaskComparison
        if request.geometry_kind == "boxes":
            comparison = compare_box_evidence(
                evidence(snapshot_a),
                evidence(snapshot_b),
                iou_threshold=request.iou_threshold,
                reference_side=request.reference_side,
            )
        else:

            def mask_evidence(rows: list[dict[str, object]]) -> list[MaskEvidence]:
                values = []
                for row in rows:
                    raw_runs = row.get("runs")
                    width_px = row.get("width_px")
                    height_px = row.get("height_px")
                    if (
                        not isinstance(raw_runs, list)
                        or not isinstance(width_px, int)
                        or not isinstance(height_px, int)
                    ):
                        raise ValidationError("Annotation comparison mask runs are invalid")
                    try:
                        runs_list: list[tuple[int, int, int]] = []
                        for run in raw_runs:
                            if (
                                not isinstance(run, list)
                                or len(run) != 3
                                or not all(isinstance(value, int) for value in run)
                            ):
                                raise ValueError("invalid pixel run")
                            runs_list.append((run[0], run[1], run[2]))
                        values.append(
                            MaskEvidence(
                                evidence_id=str(row["evidence_id"]),
                                image_id=str(row["image_id"]),
                                class_id=str(row["class_id"]),
                                width_px=width_px,
                                height_px=height_px,
                                runs=tuple(runs_list),
                            )
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ValidationError(
                            "Annotation comparison mask snapshot is invalid"
                        ) from exc
                return values

            comparison = compare_mask_evidence(
                mask_evidence(snapshot_a),
                mask_evidence(snapshot_b),
                iou_threshold=request.iou_threshold,
                reference_side=request.reference_side,
            )
        per_class = {key: asdict(value) for key, value in comparison.per_class.items()}
        for value in per_class.values():
            value["matched_count"] = len(value["matches"])
        payload = {
            "schema_version": "1.1.0",
            "algorithm": comparison.algorithm,
            "project_id": project_id,
            "image_id": image.id,
            "image_sha256": image.sha256,
            "source_a": request.source_a.model_dump(mode="json"),
            "source_b": request.source_b.model_dump(mode="json"),
            "geometry_kind": request.geometry_kind,
            "source_a_snapshot": snapshot_a,
            "source_b_snapshot": snapshot_b,
            "source_a_sha256": content_hash(snapshot_a),
            "source_b_sha256": content_hash(snapshot_b),
            "iou_threshold": request.iou_threshold,
            "reference_side": request.reference_side,
            "per_class": per_class,
            "independent_sampling_unit": comparison.independent_sampling_unit,
            "methodological_notes": [
                "Matching is deterministic, class-aware, image-scoped, and one-to-one.",
                "Images, not individual objects, are the independent sampling units.",
                "Legacy annotations do not establish independent reviewer identity.",
                "False-positive/false-negative terms appear only with an explicit reference side.",
                "A selected reference is a comparison convention, not biological ground truth.",
            ],
        }
        return AnnotationComparisonPreviewResponse(**payload, content_sha256=content_hash(payload))

    def calculate(
        self,
        project_id: str,
        request: AnnotationComparisonCalculateRequest,
        *,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> AnnotationComparisonSavedResponse:
        preview_request = AnnotationComparisonPreviewRequest.model_validate(
            request.model_dump(exclude={"name"})
        )
        comparison = self.preview(project_id, preview_request)
        configuration = preview_request.model_dump(mode="json")
        is_mask = preview_request.geometry_kind == "masks"
        definition = ComputedMetricDefinition(
            id=str(uuid4()),
            project_id=project_id,
            definition_kind=DEFINITION_KIND,
            name=request.name,
            expression=(
                "class_aware_one_to_one_mask_iou(source_a, source_b)"
                if is_mask
                else "class_aware_one_to_one_box_iou(source_a, source_b)"
            ),
            formula_version=MASK_FORMULA_VERSION if is_mask else BOX_FORMULA_VERSION,
            input_spec_json=[],
            configuration_json=configuration,
            output_unit="count",
            definition_sha256="",
        )
        definition.definition_sha256 = content_hash(
            {
                "name": definition.name,
                "expression": definition.expression,
                "formula_version": definition.formula_version,
                "output_unit": definition.output_unit,
                "configuration": configuration,
            }
        )
        self.session.add(definition)
        self.session.flush()
        result_payload = {
            "definition_id": definition.id,
            "definition_name": definition.name,
            "definition_sha256": definition.definition_sha256,
            "formula_version": definition.formula_version,
            "comparison": comparison.model_dump(mode="json"),
        }
        result = ComputedMetricResult(
            id=str(uuid4()),
            project_id=project_id,
            result_kind=DEFINITION_KIND,
            definition_id=definition.id,
            observed_at=datetime.now(UTC),
            payload_json=result_payload,
            content_sha256=content_hash(result_payload),
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
        )
        self.session.add(result)
        self.session.commit()
        return AnnotationComparisonSavedResponse(
            definition_id=definition.id,
            result_id=result.id,
            definition_sha256=definition.definition_sha256,
            result_sha256=result.content_sha256,
            comparison=comparison,
        )

    def _saved_response(self, project_id: str, result_id: str) -> AnnotationComparisonSavedResponse:
        result = self.session.get(ComputedMetricResult, result_id)
        if (
            result is None
            or result.project_id != project_id
            or result.result_kind != DEFINITION_KIND
        ):
            raise NotFoundError("Annotation comparison result not found")
        if content_hash(result.payload_json) != result.content_sha256:
            raise ConflictError("Annotation comparison result checksum mismatch")
        definition = self.session.get(ComputedMetricDefinition, result.definition_id)
        if (
            definition is None
            or definition.project_id != project_id
            or definition.definition_kind != DEFINITION_KIND
        ):
            raise ConflictError("Annotation comparison definition is unavailable")
        definition_payload = {
            "name": definition.name,
            "expression": definition.expression,
            "formula_version": definition.formula_version,
            "output_unit": definition.output_unit,
            "configuration": definition.configuration_json,
        }
        if content_hash(definition_payload) != definition.definition_sha256:
            raise ConflictError("Annotation comparison definition checksum mismatch")
        comparison = AnnotationComparisonPreviewResponse.model_validate(
            result.payload_json.get("comparison")
        )
        return AnnotationComparisonSavedResponse(
            definition_id=definition.id,
            result_id=result.id,
            definition_sha256=definition.definition_sha256,
            result_sha256=result.content_sha256,
            comparison=comparison,
        )

    def get_result(self, project_id: str, result_id: str) -> AnnotationComparisonSavedResponse:
        return self._saved_response(project_id, result_id)

    def validate_result(
        self, project_id: str, result_id: str
    ) -> AnnotationComparisonValidationResponse:
        saved = self._saved_response(project_id, result_id)
        result = self.session.get(ComputedMetricResult, result_id)
        if result is None:
            raise NotFoundError("Annotation comparison result not found")
        definition = self.session.get(ComputedMetricDefinition, result.definition_id)
        if definition is None:
            raise ConflictError("Annotation comparison definition is unavailable")
        reasons: list[str] = []
        current_hash: str | None = None
        try:
            request = AnnotationComparisonPreviewRequest.model_validate(
                definition.configuration_json
            )
            current_hash = self.preview(project_id, request).content_sha256
            if current_hash != saved.comparison.content_sha256:
                reasons.append("source_snapshot_changed")
        except (NotFoundError, ValidationError, ValueError):
            reasons.append("source_evidence_unavailable_or_changed")
        return AnnotationComparisonValidationResponse(
            result_id=result_id,
            is_current=not reasons,
            reasons=reasons,
            stored_comparison_sha256=saved.comparison.content_sha256,
            current_comparison_sha256=current_hash,
            validated_at=datetime.now(UTC),
        )

    def result_csv(self, project_id: str, result_id: str) -> str:
        saved = self._saved_response(project_id, result_id)
        output = io.StringIO(newline="")
        columns = [
            "result_id",
            "image_id",
            "geometry_kind",
            "class_id",
            "reference_side",
            "count_a",
            "count_b",
            "matched_count",
            "unmatched_a_count",
            "unmatched_b_count",
            "mean_matched_iou",
            "union_iou",
            "symmetric_difference_area_pixels",
            "comparison_sha256",
        ]
        writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for class_id, raw in sorted(saved.comparison.per_class.items()):
            value = raw
            writer.writerow(
                {
                    "result_id": result_id,
                    "image_id": saved.comparison.image_id,
                    "geometry_kind": saved.comparison.geometry_kind,
                    "class_id": class_id,
                    "reference_side": saved.comparison.reference_side or "",
                    "count_a": value.get("count_a"),
                    "count_b": value.get("count_b"),
                    "matched_count": value.get("matched_count"),
                    "unmatched_a_count": len(value.get("unmatched_a_ids", [])),
                    "unmatched_b_count": len(value.get("unmatched_b_ids", [])),
                    "mean_matched_iou": value.get("mean_matched_iou"),
                    "union_iou": value.get("union_iou", ""),
                    "symmetric_difference_area_pixels": value.get(
                        "symmetric_difference_area_pixels", ""
                    ),
                    "comparison_sha256": saved.comparison.content_sha256,
                }
            )
        return output.getvalue()

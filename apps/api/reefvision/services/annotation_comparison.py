"""Project-scoped comparison of reviewed annotations and pinned prediction jobs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Annotation, ImageAsset, PredictionProposal
from reefvision.db.models.computed_metric import ComputedMetricDefinition, ComputedMetricResult
from reefvision.domain.annotation_comparison import BoxEvidence, compare_box_evidence
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.annotation_comparison import (
    AnnotationComparisonCalculateRequest,
    AnnotationComparisonPreviewRequest,
    AnnotationComparisonPreviewResponse,
    AnnotationComparisonSavedResponse,
    AnnotationComparisonSource,
)
from reefvision.services.scientific_data import content_hash

MAX_COMPARISON_BOXES = 25_000
DEFINITION_KIND = "annotation_comparison"
FORMULA_VERSION = "reefvision.annotation-comparison.v1"


class AnnotationComparisonService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _source_snapshot(
        self,
        *,
        project_id: str,
        image: ImageAsset,
        source: AnnotationComparisonSource,
    ) -> list[dict[str, object]]:
        if source.kind == "reviewed_boxes":
            if image.annotation_status != "reviewed":
                return []
            rows = self.session.scalars(
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
                for row in rows
            ]
        prediction_rows = self.session.scalars(
            select(PredictionProposal)
            .where(
                PredictionProposal.project_id == project_id,
                PredictionProposal.image_id == image.id,
                PredictionProposal.inference_job_id == str(source.prediction_job_id),
                PredictionProposal.geometry_kind == "bounding_box",
            )
            .order_by(PredictionProposal.id)
        ).all()
        if not prediction_rows:
            raise NotFoundError("Prediction job has no box evidence for the project image")
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
            project_id=project_id, image=image, source=request.source_a
        )
        snapshot_b = self._source_snapshot(
            project_id=project_id, image=image, source=request.source_b
        )
        if len(snapshot_a) + len(snapshot_b) > MAX_COMPARISON_BOXES:
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

        comparison = compare_box_evidence(
            evidence(snapshot_a),
            evidence(snapshot_b),
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
                "Images, not individual boxes, are the independent sampling units.",
                "Legacy annotations do not establish independent reviewer identity.",
                "False-positive/false-negative terms appear only with an explicit reference side.",
            ],
        }
        return AnnotationComparisonPreviewResponse(**payload, content_sha256=content_hash(payload))

    def calculate(
        self, project_id: str, request: AnnotationComparisonCalculateRequest
    ) -> AnnotationComparisonSavedResponse:
        preview_request = AnnotationComparisonPreviewRequest.model_validate(
            request.model_dump(exclude={"name"})
        )
        comparison = self.preview(project_id, preview_request)
        configuration = preview_request.model_dump(mode="json")
        definition = ComputedMetricDefinition(
            id=str(uuid4()),
            project_id=project_id,
            definition_kind=DEFINITION_KIND,
            name=request.name,
            expression="class_aware_one_to_one_box_iou(source_a, source_b)",
            formula_version=FORMULA_VERSION,
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
            workflow_run_id=None,
            workflow_node_run_id=None,
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

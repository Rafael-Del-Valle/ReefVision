"""Classification bulk review, cross-model comparison, and scientific file exports."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ClassificationPrediction, ModelRegistration, Project
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.classification import ClassificationAssignmentAcceptRequest
from reefvision.schemas.classification_assignment_exports import (
    ScientificClassificationExportResponse,
)
from reefvision.schemas.classification_management import (
    BulkClassificationReviewItem,
    BulkClassificationReviewRequest,
    BulkClassificationReviewResponse,
    ClassificationComparisonResponse,
    ClassificationModelPredictionComparison,
    ClassificationTargetComparison,
)
from reefvision.services.classification_assignment_exports import (
    ScientificClassificationExportService,
)
from reefvision.services.generalized_classification_assignments import (
    GeneralizedClassificationAssignmentService,
)


def _json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return _json_text(value)
    return value


class ClassificationManagementService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.assignments = GeneralizedClassificationAssignmentService(session)

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def bulk_review(
        self,
        project_id: str,
        request: BulkClassificationReviewRequest,
    ) -> BulkClassificationReviewResponse:
        self._project(project_id)
        items: list[BulkClassificationReviewItem] = []
        for prediction_id in request.prediction_ids:
            prediction = self.session.get(ClassificationPrediction, prediction_id)
            if prediction is None or prediction.project_id != project_id:
                items.append(
                    BulkClassificationReviewItem(
                        prediction_id=prediction_id,
                        outcome="failed",
                        message="Classification prediction was not found in this project",
                    )
                )
                continue
            try:
                if request.action == "accept":
                    assignment = self.assignments.accept_prediction_assignment(
                        prediction.id,
                        ClassificationAssignmentAcceptRequest(
                            label_set_id=request.label_set_id,
                            label_class_id=request.label_class_id,
                        ),
                    )
                    items.append(
                        BulkClassificationReviewItem(
                            prediction_id=prediction.id,
                            outcome="accepted",
                            assignment_id=assignment.id,
                        )
                    )
                    continue

                if prediction.review_status == "rejected":
                    items.append(
                        BulkClassificationReviewItem(
                            prediction_id=prediction.id,
                            outcome="unchanged",
                            message="Prediction was already rejected",
                        )
                    )
                    continue
                if prediction.review_status == "accepted":
                    raise ConflictError(
                        "Accepted predictions cannot be bulk-rejected; "
                        "supersede their assignment instead"
                    )
                prediction.review_status = "rejected"
                prediction.reviewed_at = datetime.now(UTC)
                self.session.commit()
                items.append(
                    BulkClassificationReviewItem(
                        prediction_id=prediction.id,
                        outcome="rejected",
                    )
                )
            except (ConflictError, NotFoundError, ValidationError) as exc:
                self.session.rollback()
                items.append(
                    BulkClassificationReviewItem(
                        prediction_id=prediction_id,
                        outcome="failed",
                        message=str(exc),
                    )
                )

        return BulkClassificationReviewResponse(
            project_id=project_id,
            requested_count=len(request.prediction_ids),
            accepted_count=sum(item.outcome == "accepted" for item in items),
            rejected_count=sum(item.outcome == "rejected" for item in items),
            unchanged_count=sum(item.outcome == "unchanged" for item in items),
            failed_count=sum(item.outcome == "failed" for item in items),
            items=items,
        )

    def compare_models(
        self,
        project_id: str,
        *,
        label_set: str | None = None,
        target_kind: str | None = None,
        image_id: str | None = None,
        review_status: str | None = None,
        minimum_models: int = 2,
    ) -> ClassificationComparisonResponse:
        self._project(project_id)
        if minimum_models < 1 or minimum_models > 50:
            raise ValidationError("minimum_models must be between 1 and 50")
        query = (
            select(ClassificationPrediction, ModelRegistration)
            .join(
                ModelRegistration,
                ModelRegistration.id == ClassificationPrediction.model_id,
            )
            .where(ClassificationPrediction.project_id == project_id)
        )
        if label_set:
            query = query.where(ClassificationPrediction.label_set == label_set)
        if target_kind:
            query = query.where(ClassificationPrediction.target_kind == target_kind)
        if image_id:
            query = query.where(ClassificationPrediction.image_id == image_id)
        if review_status:
            query = query.where(ClassificationPrediction.review_status == review_status)
        rows = self.session.execute(
            query.order_by(
                ClassificationPrediction.label_set,
                ClassificationPrediction.target_kind,
                ClassificationPrediction.target_key,
                ModelRegistration.display_name,
                ClassificationPrediction.created_at.desc(),
            )
        ).all()

        grouped: dict[
            tuple[str, str, str, str],
            dict[str, tuple[ClassificationPrediction, ModelRegistration]],
        ] = {}
        for prediction, model in rows:
            key = (
                prediction.label_set,
                prediction.target_kind,
                prediction.target_key,
                prediction.image_id,
            )
            per_model = grouped.setdefault(key, {})
            per_model.setdefault(model.id, (prediction, model))

        targets: list[ClassificationTargetComparison] = []
        for (task, kind, target_key, source_image_id), per_model in grouped.items():
            if len(per_model) < minimum_models:
                continue
            predictions: list[ClassificationModelPredictionComparison] = []
            compared_values: list[str] = []
            for prediction, model in per_model.values():
                value = (
                    prediction.label_class_id
                    or prediction.predicted_label.strip().casefold()
                )
                compared_values.append(value)
                predictions.append(
                    ClassificationModelPredictionComparison(
                        prediction_id=prediction.id,
                        model_id=model.id,
                        model_name=model.display_name,
                        predicted_label=prediction.predicted_label,
                        label_class_id=prediction.label_class_id,
                        confidence=prediction.confidence,
                        review_status=prediction.review_status,
                        probabilities={
                            str(key): float(value)
                            for key, value in dict(
                                prediction.probabilities_json or {}
                            ).items()
                        },
                    )
                )
            unique_values = sorted(set(compared_values))
            targets.append(
                ClassificationTargetComparison(
                    target_kind=kind,
                    target_key=target_key,
                    image_id=source_image_id,
                    label_set=task,
                    model_count=len(predictions),
                    agreement=len(unique_values) == 1,
                    compared_values=unique_values,
                    predictions=sorted(
                        predictions,
                        key=lambda item: (item.model_name, item.model_id),
                    ),
                )
            )
        targets.sort(key=lambda item: (item.label_set, item.image_id, item.target_key))
        agreement_count = sum(item.agreement for item in targets)
        return ClassificationComparisonResponse(
            project_id=project_id,
            target_count=len(targets),
            agreement_count=agreement_count,
            disagreement_count=len(targets) - agreement_count,
            minimum_models=minimum_models,
            targets=targets,
        )


class ScientificClassificationFileService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.exporter = ScientificClassificationExportService(session, settings)

    def _document(
        self,
        project_id: str,
        assignment_status: str,
    ) -> ScientificClassificationExportResponse:
        return self.exporter.export(project_id, assignment_status=assignment_status)

    def csv_bytes(self, project_id: str, *, assignment_status: str = "accepted") -> bytes:
        document = self._document(project_id, assignment_status)
        fieldnames = list(type(document.rows[0]).model_fields) if document.rows else [
            "assignment_id",
            "target_kind",
            "target_key",
            "image_id",
            "label_set_key",
            "label_class_id",
            "label_class_name",
            "confidence",
            "measurements",
        ]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in document.rows:
            writer.writerow(
                {
                    key: _csv_value(value)
                    for key, value in row.model_dump(mode="python").items()
                }
            )
        return stream.getvalue().encode("utf-8-sig")

    def npz_bytes(self, project_id: str, *, assignment_status: str = "accepted") -> bytes:
        document = self._document(project_id, assignment_status)
        rows = [row.model_dump(mode="python") for row in document.rows]

        def strings(key: str) -> np.ndarray[Any, Any]:
            return np.asarray(
                [
                    ""
                    if row.get(key) is None
                    else (
                        row[key].isoformat()
                        if isinstance(row.get(key), datetime)
                        else str(row[key])
                    )
                    for row in rows
                ],
                dtype=np.str_,
            )

        def json_strings(key: str) -> np.ndarray[Any, Any]:
            return np.asarray(
                [_json_text(row.get(key)) for row in rows],
                dtype=np.str_,
            )

        bounding_boxes = np.full((len(rows), 4), np.nan, dtype=np.float64)
        for index, row in enumerate(rows):
            values = row.get("bounding_box")
            if isinstance(values, list) and len(values) == 4:
                bounding_boxes[index, :] = np.asarray(values, dtype=np.float64)

        payload: dict[str, Any] = {
            "assignment_id": strings("assignment_id"),
            "assignment_revision": np.asarray(
                [int(row.get("assignment_revision") or 0) for row in rows],
                dtype=np.int64,
            ),
            "assignment_status": strings("assignment_status"),
            "target_kind": strings("target_kind"),
            "target_key": strings("target_key"),
            "image_id": strings("image_id"),
            "image_filename": strings("image_filename"),
            "image_group_key": strings("image_group_key"),
            "capture_timestamp": strings("capture_timestamp"),
            "annotation_id": strings("annotation_id"),
            "mask_annotation_id": strings("mask_annotation_id"),
            "fragment_key": strings("fragment_key"),
            "bounding_box": bounding_boxes,
            "label_set_id": strings("label_set_id"),
            "label_set_key": strings("label_set_key"),
            "label_set_name": strings("label_set_name"),
            "cardinality": strings("cardinality"),
            "label_class_id": strings("label_class_id"),
            "label_class_name": strings("label_class_name"),
            "source_type": strings("source_type"),
            "source_model_id": strings("source_model_id"),
            "source_model_name": strings("source_model_name"),
            "source_prediction_id": strings("source_prediction_id"),
            "confidence": np.asarray(
                [
                    np.nan
                    if row.get("confidence") is None
                    else float(row["confidence"])
                    for row in rows
                ],
                dtype=np.float64,
            ),
            "reviewed_at": strings("reviewed_at"),
            "measurement_join_status": strings("measurement_join_status"),
            "measurement_mask_id": strings("measurement_mask_id"),
            "image_metadata_json": json_strings("image_metadata"),
            "probabilities_json": json_strings("probabilities"),
            "provenance_json": json_strings("provenance"),
            "measurement_candidate_mask_ids_json": json_strings(
                "measurement_candidate_mask_ids"
            ),
            "measurements_json": json_strings("measurements"),
            "manifest_json": np.asarray(
                _json_text(
                    {
                        "project_id": document.project_id,
                        "row_count": document.row_count,
                        "matched_measurement_count": document.matched_measurement_count,
                        "unmatched_measurement_count": document.unmatched_measurement_count,
                        "ambiguous_measurement_count": document.ambiguous_measurement_count,
                        "warnings": document.warnings,
                        "assignment_status": assignment_status,
                    }
                ),
                dtype=np.str_,
            ),
        }
        stream = io.BytesIO()
        np.savez_compressed(stream, **payload)
        return stream.getvalue()

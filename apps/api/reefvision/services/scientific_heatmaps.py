"""Read-only spatial density grids with independent evidence categories.

Counts are based on bounding-rectangle centroids, not mask coverage.
No interpolation, georeferencing or physical area is inferred.
"""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Annotation,
    ImageAsset,
    LabelClass,
    MaskAnnotation,
    PredictionProposal,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.scientific_heatmaps import (
    HeatmapKind,
    HeatmapLayer,
    ScientificHeatmapResponse,
)
from reefvision.services.annotations import (
    annotation_snapshot,
    mask_annotation_snapshot,
)
from reefvision.services.scientific_data import content_hash

ALGORITHM = "reefvision-centroid-grid-1"
MAX_OBJECTS = 25_000


def _center(
    x_min: float | None,
    y_min: float | None,
    x_max: float | None,
    y_max: float | None,
    width: int,
    height: int,
) -> tuple[float, float]:

    if x_min is None or y_min is None or x_max is None or y_max is None:
        raise ValidationError("Heatmap object is missing spatial bounds")

    x0 = float(x_min)
    y0 = float(y_min)
    x1 = float(x_max)
    y1 = float(y_max)

    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        raise ValidationError("Heatmap coordinates must be finite")

    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValidationError("Heatmap bounds exceed the image or have zero area")

    return ((x0 + x1) / 2, (y0 + y1) / 2)


def _layer(
    kind: HeatmapKind,
    points: list[tuple[float, float]],
    *,
    width: int,
    height: int,
    columns: int,
    rows: int,
) -> HeatmapLayer:
    cells = [[0 for _ in range(columns)] for _ in range(rows)]

    for x, y in points:
        column = min(columns - 1, int(x * columns / width))
        row = min(rows - 1, int(y * rows / height))
        cells[row][column] += 1

    maximum = max((max(line) for line in cells), default=0)

    normalized = [
        [round(value / maximum, 8) if maximum else 0.0 for value in line] for line in cells
    ]

    return HeatmapLayer(
        kind=kind,
        counting_method="bounding_rectangle_centroid",
        object_count=len(points),
        max_cell_count=maximum,
        counts=cells,
        normalized=normalized,
    )


class ScientificHeatmapService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def image_heatmaps(
        self,
        project_id: str,
        image_id: str,
        *,
        columns: int,
        rows: int,
        label_class_id: str | None,
    ) -> ScientificHeatmapResponse:
        if not (2 <= columns <= 64 and 2 <= rows <= 64):
            raise ValidationError("Heatmap grid must be between 2 and 64 cells per axis")

        image = self.session.get(ImageAsset, image_id)
        if image is None or image.project_id != project_id:
            raise NotFoundError("Project image not found")

        if image.width_px <= 0 or image.height_px <= 0:
            raise ValidationError("Source image dimensions are invalid")

        if label_class_id is not None:
            label = self.session.get(LabelClass, label_class_id)
            if label is None or label.project_id != project_id:
                raise NotFoundError("Project label class not found")

        boxes = self.session.scalars(
            select(Annotation)
            .where(
                Annotation.image_id == image_id,
                Annotation.deleted_at.is_(None),
            )
            .order_by(Annotation.id)
        ).all()

        masks = self.session.scalars(
            select(MaskAnnotation)
            .where(
                MaskAnnotation.image_id == image_id,
                MaskAnnotation.deleted_at.is_(None),
            )
            .order_by(MaskAnnotation.id)
        ).all()

        predictions = self.session.scalars(
            select(PredictionProposal)
            .where(
                PredictionProposal.project_id == project_id,
                PredictionProposal.image_id == image_id,
                PredictionProposal.review_status == "pending",
            )
            .order_by(PredictionProposal.id)
        ).all()

        if len(boxes) + len(masks) + len(predictions) > MAX_OBJECTS:
            raise ValidationError("Heatmap object limit exceeded")

        if label_class_id is not None:
            boxes = [box for box in boxes if box.label_class_id == label_class_id]
            masks = [mask for mask in masks if mask.label_class_id == label_class_id]
            predictions = [
                prediction
                for prediction in predictions
                if prediction.label_class_id == label_class_id
            ]

        reviewed_boxes = []
        verified_masks = []
        pending_predictions = []

        if image.annotation_status == "reviewed":
            for box in boxes:
                reviewed_boxes.append(
                    _center(
                        box.x_min,
                        box.y_min,
                        box.x_max,
                        box.y_max,
                        image.width_px,
                        image.height_px,
                    )
                )

        for mask in masks:
            if mask.status != "verified":
                continue

            verified_masks.append(
                _center(
                    mask.x_min,
                    mask.y_min,
                    mask.x_max,
                    mask.y_max,
                    image.width_px,
                    image.height_px,
                )
            )

        for prediction in predictions:
            if not (math.isfinite(prediction.confidence) and 0 <= prediction.confidence <= 1):
                raise ValidationError("Invalid model prediction confidence")

            pending_predictions.append(
                _center(
                    prediction.x_min,
                    prediction.y_min,
                    prediction.x_max,
                    prediction.y_max,
                    image.width_px,
                    image.height_px,
                )
            )

        layers = [
            _layer(
                "reviewed_boxes",
                reviewed_boxes,
                width=image.width_px,
                height=image.height_px,
                columns=columns,
                rows=rows,
            ),
            _layer(
                "verified_masks",
                verified_masks,
                width=image.width_px,
                height=image.height_px,
                columns=columns,
                rows=rows,
            ),
            _layer(
                "pending_predictions",
                pending_predictions,
                width=image.width_px,
                height=image.height_px,
                columns=columns,
                rows=rows,
            ),
        ]

        source_snapshot: dict[str, Any] = {
            "algorithm": ALGORITHM,
            "image_id": image.id,
            "image_sha256": image.sha256,
            "annotation_status": image.annotation_status,
            "annotation_revision": image.annotation_revision,
            "label_class_id": label_class_id,
            "boxes": [annotation_snapshot(box) for box in boxes],
            "masks": [mask_annotation_snapshot(mask) for mask in masks],
            "pending_predictions": [
                {
                    "id": proposal.id,
                    "model_id": proposal.model_id,
                    "model_checksum": proposal.model_checksum,
                    "inference_job_id": proposal.inference_job_id,
                    "review_status": proposal.review_status,
                    "confidence": proposal.confidence,
                    "label_class_id": proposal.label_class_id,
                    "x_min": proposal.x_min,
                    "x_max": proposal.x_max,
                    "y_min": proposal.y_min,
                    "y_max": proposal.y_max,
                }
                for proposal in predictions
            ],
        }

        source_sha = content_hash(source_snapshot)

        result = {
            "algorithm": ALGORITHM,
            "project_id": project_id,
            "image_id": image_id,
            "image_sha256": image.sha256,
            "annotation_revision": image.annotation_revision,
            "annotation_status": image.annotation_status,
            "width_px": image.width_px,
            "height_px": image.height_px,
            "columns": columns,
            "rows": rows,
            "label_class_id": label_class_id,
            "layers": [layer.model_dump(mode="json") for layer in layers],
            "source_sha256": source_sha,
        }

        return ScientificHeatmapResponse(
            schema_version="1.1.0",
            algorithm=ALGORITHM,
            project_id=UUID(project_id),
            image_id=UUID(image_id),
            image_sha256=image.sha256,
            annotation_revision=image.annotation_revision,
            annotation_status=image.annotation_status,
            width_px=image.width_px,
            height_px=image.height_px,
            columns=columns,
            rows=rows,
            label_class_id=(UUID(label_class_id) if label_class_id is not None else None),
            layers=layers,
            source_sha256=source_sha,
            content_sha256=content_hash(result),
            methodological_notes=[
                "Each object contributes to exactly one grid cell.",
                "Object location uses bounding rectangle centroid.",
                "Only reviewed image boxes enter the reviewed-box layer.",
                "Only masks marked verified enter the verified-mask layer.",
                "Pending predictions are separate and not verified.",
                "The grid is expressed in source-image pixel coordinates.",
                "Normalized intensity is independently scaled per layer.",
                "This grid is not polygon coverage or union area.",
                "It is not a calibrated physical density measurement.",
                "Rejected and accepted proposals are not pending predictions.",
                "No reviewer disagreement metric is inferred.",
                "This result is computed on demand and is not persisted.",
            ],
        )

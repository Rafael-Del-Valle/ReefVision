"""Join reviewed classifications with image metadata and fragment measurements."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    ClassificationAssignment,
    ClassificationLabelSet,
    ImageAsset,
    LabelClass,
    MaskAnnotation,
    ModelRegistration,
    Project,
)
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.classification_assignment_exports import (
    ScientificClassificationExportResponse,
    ScientificClassificationExportRow,
)
from reefvision.services.mask_measurements import (
    MaskMeasurementService,
    _point_in_polygon,
    _raster_measurements,
    _raster_pixel_active,
)
from reefvision.storage.projects import resolve_managed_project_path


class ScientificClassificationExportService:
    """Build a conservative assignment-to-fragment scientific export."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.measurements = MaskMeasurementService(session, settings)
        self._raster_cache: dict[str, tuple[bytes, int, int]] = {}
        self._measurement_cache: dict[str, dict[str, Any]] = {}

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _mask_contains(self, mask: MaskAnnotation, x: float, y: float) -> bool:
        if None in {mask.x_min, mask.y_min, mask.x_max, mask.y_max}:
            return False
        if not (
            float(mask.x_min) <= x <= float(mask.x_max)
            and float(mask.y_min) <= y <= float(mask.y_max)
        ):
            return False
        if mask.geometry_kind == "polygon":
            if not mask.polygon_json or len(mask.polygon_json) < 3:
                return False
            polygon = [(float(point[0]), float(point[1])) for point in mask.polygon_json]
            return _point_in_polygon((x, y), polygon)
        if mask.geometry_kind == "raster_mask" and mask.mask_path:
            raster = self._raster_cache.get(mask.id)
            if raster is None:
                path = resolve_managed_project_path(self.settings, mask.mask_path)
                _area, _perimeter, _center_x, _center_y, raster = _raster_measurements(path)
                self._raster_cache[mask.id] = raster
            return _raster_pixel_active(raster, int(x), int(y))
        return False

    def _measure(self, mask_id: str) -> dict[str, Any]:
        cached = self._measurement_cache.get(mask_id)
        if cached is not None:
            return cached
        payload = self.measurements.measure(mask_id).model_dump(mode="json")
        self._measurement_cache[mask_id] = payload
        return payload

    def export(
        self,
        project_id: str,
        *,
        assignment_status: str = "accepted",
    ) -> ScientificClassificationExportResponse:
        self._project(project_id)
        assignments = list(
            self.session.scalars(
                select(ClassificationAssignment)
                .where(
                    ClassificationAssignment.project_id == project_id,
                    ClassificationAssignment.status == assignment_status,
                )
                .order_by(
                    ClassificationAssignment.image_id,
                    ClassificationAssignment.target_key,
                    ClassificationAssignment.created_at,
                    ClassificationAssignment.id,
                )
            )
        )
        image_ids = sorted({assignment.image_id for assignment in assignments})
        masks_by_image: dict[str, list[MaskAnnotation]] = defaultdict(list)
        if image_ids:
            masks = list(
                self.session.scalars(
                    select(MaskAnnotation)
                    .where(
                        MaskAnnotation.image_id.in_(image_ids),
                        MaskAnnotation.deleted_at.is_(None),
                        MaskAnnotation.status == "verified",
                    )
                    .order_by(MaskAnnotation.created_at, MaskAnnotation.id)
                )
            )
            for mask in masks:
                masks_by_image[mask.image_id].append(mask)

        rows: list[ScientificClassificationExportRow] = []
        warnings: list[str] = []
        matched = 0
        unmatched = 0
        ambiguous = 0
        for assignment in assignments:
            image = self.session.get(ImageAsset, assignment.image_id)
            label_set = self.session.get(ClassificationLabelSet, assignment.label_set_id)
            label_class = self.session.get(LabelClass, assignment.label_class_id)
            if image is None or label_set is None or label_class is None:
                warnings.append(
                    f"Assignment {assignment.id} was skipped because required metadata is missing."
                )
                continue
            model = (
                self.session.get(ModelRegistration, assignment.source_model_id)
                if assignment.source_model_id
                else None
            )
            annotation = (
                self.session.get(Annotation, assignment.annotation_id)
                if assignment.annotation_id
                else None
            )
            bounding_box: list[float] | None = None
            candidate_masks: list[MaskAnnotation] = []
            direct_mask = (
                self.session.get(MaskAnnotation, assignment.mask_annotation_id)
                if assignment.mask_annotation_id
                else None
            )
            if direct_mask is not None and direct_mask.deleted_at is None:
                candidate_masks = [direct_mask]
                if None not in {
                    direct_mask.x_min,
                    direct_mask.y_min,
                    direct_mask.x_max,
                    direct_mask.y_max,
                }:
                    bounding_box = [
                        float(direct_mask.x_min),
                        float(direct_mask.y_min),
                        float(direct_mask.x_max),
                        float(direct_mask.y_max),
                    ]
            elif annotation is not None and annotation.deleted_at is None:
                bounding_box = [
                    annotation.x_min,
                    annotation.y_min,
                    annotation.x_max,
                    annotation.y_max,
                ]
                center_x = (annotation.x_min + annotation.x_max) / 2.0
                center_y = (annotation.y_min + annotation.y_max) / 2.0
                candidate_masks = [
                    mask
                    for mask in masks_by_image.get(image.id, [])
                    if self._mask_contains(mask, center_x, center_y)
                ]

            measurement_join_status = "unmatched"
            measurement_mask_id: str | None = None
            measurement_payload: dict[str, Any] = {}
            if len(candidate_masks) == 1:
                measurement_mask_id = candidate_masks[0].id
                try:
                    measurement_payload = self._measure(measurement_mask_id)
                    measurement_join_status = "matched"
                    matched += 1
                except Exception as exc:
                    measurement_join_status = "measurement_error"
                    unmatched += 1
                    warnings.append(
                        f"Assignment {assignment.id} matched mask {measurement_mask_id}, "
                        f"but measurement failed: {exc}"
                    )
            elif len(candidate_masks) > 1:
                measurement_join_status = "ambiguous"
                ambiguous += 1
                warnings.append(
                    f"Assignment {assignment.id} falls inside multiple verified masks and was "
                    "not assigned fragment measurements."
                )
            else:
                unmatched += 1

            rows.append(
                ScientificClassificationExportRow(
                    assignment_id=assignment.id,
                    assignment_revision=assignment.revision,
                    assignment_status=assignment.status,
                    target_kind=assignment.target_kind,
                    target_key=assignment.target_key,
                    image_id=image.id,
                    image_filename=image.original_filename,
                    image_group_key=image.group_key,
                    capture_timestamp=image.capture_timestamp,
                    image_metadata=dict(image.metadata_json or {}),
                    annotation_id=assignment.annotation_id,
                    mask_annotation_id=assignment.mask_annotation_id,
                    fragment_key=assignment.fragment_key,
                    bounding_box=bounding_box,
                    label_set_id=label_set.id,
                    label_set_key=label_set.key,
                    label_set_name=label_set.name,
                    cardinality=label_set.cardinality,
                    label_class_id=label_class.id,
                    label_class_name=label_class.name,
                    source_type=assignment.source_type,
                    source_model_id=assignment.source_model_id,
                    source_model_name=model.display_name if model else None,
                    source_prediction_id=assignment.source_prediction_id,
                    confidence=assignment.confidence,
                    probabilities=dict(assignment.probabilities_json or {}),
                    reviewed_at=assignment.reviewed_at,
                    provenance=dict(assignment.provenance_json or {}),
                    measurement_join_status=measurement_join_status,
                    measurement_mask_id=measurement_mask_id,
                    measurement_candidate_mask_ids=[mask.id for mask in candidate_masks],
                    measurements=measurement_payload,
                )
            )
        return ScientificClassificationExportResponse(
            project_id=project_id,
            row_count=len(rows),
            matched_measurement_count=matched,
            unmatched_measurement_count=unmatched,
            ambiguous_measurement_count=ambiguous,
            warnings=warnings,
            rows=rows,
        )

"""Annotation editor services."""

from __future__ import annotations

from collections import Counter
from math import isclose

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    ImageAsset,
    MaskAnnotation,
    MaskAnnotationEvent,
    Project,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.repositories.annotations import AnnotationRepository
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.mask_annotations import MaskAnnotationRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.annotations import (
    AnnotationBatchSaveRequest,
    AnnotationBatchSaveResponse,
    AnnotationCountResponse,
    AnnotationDraft,
    AnnotationResponse,
    AnnotationSessionResponse,
    MaskAnnotationDraft,
    MaskAnnotationResponse,
)
from reefvision.schemas.images import ImageResponse
from reefvision.schemas.projects import LabelClassResponse

Point = tuple[float, float]


def annotation_snapshot(annotation: Annotation) -> dict[str, object | None]:
    return {
        "id": annotation.id,
        "image_id": annotation.image_id,
        "label_class_id": annotation.label_class_id,
        "x_min": annotation.x_min,
        "y_min": annotation.y_min,
        "x_max": annotation.x_max,
        "y_max": annotation.y_max,
        "source_type": annotation.source_type,
        "source_model_id": annotation.source_model_id,
        "source_prediction_id": annotation.source_prediction_id,
        "provenance_json": annotation.provenance_json,
        "created_by": annotation.created_by,
        "deleted_at": annotation.deleted_at.isoformat() if annotation.deleted_at else None,
        "revision": annotation.revision,
    }


def mask_annotation_snapshot(annotation: MaskAnnotation) -> dict[str, object | None]:
    return {
        "id": annotation.id,
        "image_id": annotation.image_id,
        "label_class_id": annotation.label_class_id,
        "geometry_kind": annotation.geometry_kind,
        "mask_path": annotation.mask_path,
        "polygon_json": annotation.polygon_json,
        "x_min": annotation.x_min,
        "y_min": annotation.y_min,
        "x_max": annotation.x_max,
        "y_max": annotation.y_max,
        "area_pixels": annotation.area_pixels,
        "source_type": annotation.source_type,
        "provenance_json": annotation.provenance_json,
        "status": annotation.status,
        "created_by": annotation.created_by,
        "deleted_at": annotation.deleted_at.isoformat() if annotation.deleted_at else None,
        "revision": annotation.revision,
    }


def _cross(first: Point, second: Point, third: Point) -> float:
    return (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (
        third[0] - first[0]
    )


def _point_on_segment(first: Point, second: Point, point: Point) -> bool:
    return (
        min(first[0], second[0]) <= point[0] <= max(first[0], second[0])
        and min(first[1], second[1]) <= point[1] <= max(first[1], second[1])
        and isclose(_cross(first, second, point), 0.0, abs_tol=1e-9)
    )


def _segments_intersect(
    first_a: Point,
    first_b: Point,
    second_a: Point,
    second_b: Point,
) -> bool:
    cross_1 = _cross(first_a, first_b, second_a)
    cross_2 = _cross(first_a, first_b, second_b)
    cross_3 = _cross(second_a, second_b, first_a)
    cross_4 = _cross(second_a, second_b, first_b)

    if (cross_1 > 0 > cross_2 or cross_1 < 0 < cross_2) and (
        cross_3 > 0 > cross_4 or cross_3 < 0 < cross_4
    ):
        return True

    return any(
        (isclose(cross_value, 0.0, abs_tol=1e-9) and _point_on_segment(segment_a, segment_b, point))
        for cross_value, segment_a, segment_b, point in (
            (cross_1, first_a, first_b, second_a),
            (cross_2, first_a, first_b, second_b),
            (cross_3, second_a, second_b, first_a),
            (cross_4, second_a, second_b, first_b),
        )
    )


def _polygon_self_intersects(points: list[Point]) -> bool:
    edge_count = len(points)
    for first_index in range(edge_count):
        first_a = points[first_index]
        first_b = points[(first_index + 1) % edge_count]
        for second_index in range(first_index + 1, edge_count):
            if second_index == first_index:
                continue
            if second_index == (first_index + 1) % edge_count:
                continue
            if first_index == (second_index + 1) % edge_count:
                continue
            second_a = points[second_index]
            second_b = points[(second_index + 1) % edge_count]
            if _segments_intersect(first_a, first_b, second_a, second_b):
                return True
    return False


def _polygon_area(points: list[Point]) -> float:
    return (
        abs(
            sum(
                points[index][0] * points[(index + 1) % len(points)][1]
                - points[(index + 1) % len(points)][0] * points[index][1]
                for index in range(len(points))
            )
        )
        / 2.0
    )


class AnnotationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.annotations = AnnotationRepository(session)
        self.mask_annotations = MaskAnnotationRepository(session)
        self.images = ImageRepository(session)
        self.projects = ProjectRepository(session)

    def _image(self, image_id: str) -> ImageAsset:
        image = self.images.get(image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def _project_with_classes(self, image: ImageAsset) -> Project:
        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _neighbor_ids(self, image: ImageAsset) -> tuple[str | None, str | None]:
        return self.images.neighbor_ids_for_image(image)

    def _counts_by_class(self, annotations: list[Annotation]) -> list[AnnotationCountResponse]:
        counts = Counter(
            annotation.label_class_id for annotation in annotations if annotation.deleted_at is None
        )
        return [
            AnnotationCountResponse(label_class_id=label_class_id, count=count)
            for label_class_id, count in sorted(counts.items())
        ]

    def _mask_counts_by_class(
        self, annotations: list[MaskAnnotation]
    ) -> list[AnnotationCountResponse]:
        counts = Counter(
            annotation.label_class_id
            for annotation in annotations
            if annotation.deleted_at is None and annotation.label_class_id is not None
        )
        return [
            AnnotationCountResponse(label_class_id=label_class_id, count=count)
            for label_class_id, count in sorted(counts.items())
        ]

    def get_session(self, image_id: str) -> AnnotationSessionResponse:
        image = self._image(image_id)
        project = self._project_with_classes(image)
        annotations = self.annotations.list_for_image(image_id)
        masks = self.mask_annotations.list_for_image(image_id)
        previous_image_id, next_image_id = self._neighbor_ids(image)
        return AnnotationSessionResponse(
            image=ImageResponse.model_validate(image),
            label_classes=[
                LabelClassResponse.model_validate(label_class)
                for label_class in sorted(
                    project.label_classes,
                    key=lambda item: (item.display_order, item.class_index),
                )
            ],
            annotations=[
                AnnotationResponse.model_validate(annotation) for annotation in annotations
            ],
            mask_annotations=[
                MaskAnnotationResponse.model_validate(annotation) for annotation in masks
            ],
            counts_by_class=self._counts_by_class(annotations),
            mask_counts_by_class=self._mask_counts_by_class(masks),
            previous_image_id=previous_image_id,
            next_image_id=next_image_id,
        )

    @staticmethod
    def _validate_annotation_box(draft: AnnotationDraft, image: ImageAsset) -> None:
        if draft.x_min < 0 or draft.y_min < 0:
            raise ValidationError("Annotation coordinates cannot be negative")
        if draft.x_max > image.width_px or draft.y_max > image.height_px:
            raise ValidationError("Annotation coordinates cannot exceed image bounds")
        if draft.x_max <= draft.x_min or draft.y_max <= draft.y_min:
            raise ValidationError("Annotation boxes must have positive area")

    @staticmethod
    def _validated_polygon(
        draft: MaskAnnotationDraft,
        image: ImageAsset,
    ) -> tuple[list[list[float]], float, float, float, float, int]:
        if draft.geometry_kind not in {"polygon", "rotated_box"}:
            raise ValidationError("Unsupported editable mask geometry")
        points = [(float(point.x), float(point.y)) for point in draft.points]
        if len(points) < 3:
            raise ValidationError("Editable mask geometry requires at least three points")
        if draft.geometry_kind == "rotated_box" and len(points) != 4:
            raise ValidationError("Rotated boxes require exactly four corner points")
        if len(set(points)) < 3:
            raise ValidationError("Polygon masks require at least three unique points")
        if any(points[index] == points[(index + 1) % len(points)] for index in range(len(points))):
            raise ValidationError("Polygon masks cannot contain consecutive duplicate points")
        if any(x < 0 or y < 0 or x > image.width_px or y > image.height_px for x, y in points):
            raise ValidationError("Polygon masks cannot extend outside the image bounds")
        if _polygon_self_intersects(points):
            raise ValidationError("Polygon masks cannot self-intersect")
        area = _polygon_area(points)
        if area < 1.0:
            raise ValidationError("Polygon masks must cover at least one square pixel")
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        return (
            [[x, y] for x, y in points],
            min(x_values),
            min(y_values),
            max(x_values),
            max(y_values),
            max(1, round(area)),
        )

    def _event(
        self,
        *,
        annotation: Annotation,
        image_id: str,
        event_type: str,
        before_json: dict[str, object | None] | None,
        after_json: dict[str, object | None] | None,
    ) -> AnnotationEvent:
        return AnnotationEvent(
            annotation_id=annotation.id,
            image_id=image_id,
            event_type=event_type,
            before_json=before_json,
            after_json=after_json,
            actor="local_user",
        )

    def _mask_event(
        self,
        *,
        annotation: MaskAnnotation,
        image_id: str,
        event_type: str,
        before_json: dict[str, object | None] | None,
        after_json: dict[str, object | None] | None,
    ) -> MaskAnnotationEvent:
        return MaskAnnotationEvent(
            mask_annotation_id=annotation.id,
            image_id=image_id,
            event_type=event_type,
            before_json=before_json,
            after_json=after_json,
            actor="local_user",
        )

    def save_annotations(
        self,
        image_id: str,
        payload: AnnotationBatchSaveRequest,
    ) -> AnnotationBatchSaveResponse:
        image = self._image(image_id)
        if image.annotation_revision != payload.base_revision:
            raise ConflictError("Annotation revision conflict")

        project = self._project_with_classes(image)
        project_classes = {label_class.id: label_class for label_class in project.label_classes}
        existing_annotations = self.annotations.list_for_image(
            image_id,
            include_deleted=True,
        )
        existing_by_id = {annotation.id: annotation for annotation in existing_annotations}
        desired_ids = {annotation.id for annotation in payload.annotations}
        changed = False

        for draft in payload.annotations:
            self._validate_annotation_box(draft, image)
            label_class = project_classes.get(draft.label_class_id)
            if label_class is None:
                raise ValidationError("Annotation class does not belong to this image's project")

            existing = existing_by_id.get(draft.id)
            if existing is None:
                conflicting_annotation = self.annotations.get(draft.id)
                if conflicting_annotation is not None:
                    raise ValidationError(
                        "Annotations may only be saved back to their source image"
                    )
                annotation = Annotation(
                    id=draft.id,
                    image_id=image_id,
                    label_class_id=draft.label_class_id,
                    x_min=draft.x_min,
                    y_min=draft.y_min,
                    x_max=draft.x_max,
                    y_max=draft.y_max,
                )
                self.annotations.add(annotation)
                self.annotations.add_event(
                    self._event(
                        annotation=annotation,
                        image_id=image_id,
                        event_type="created",
                        before_json=None,
                        after_json=annotation_snapshot(annotation),
                    )
                )
                changed = True
                continue

            if existing.image_id != image_id:
                raise ValidationError("Annotations may only be saved back to their source image")

            before = annotation_snapshot(existing)
            class_changed = existing.label_class_id != draft.label_class_id
            geometry_changed = (
                existing.x_min != draft.x_min
                or existing.y_min != draft.y_min
                or existing.x_max != draft.x_max
                or existing.y_max != draft.y_max
            )
            restored = existing.deleted_at is not None

            if class_changed or geometry_changed or restored:
                existing.label_class_id = draft.label_class_id
                existing.x_min = draft.x_min
                existing.y_min = draft.y_min
                existing.x_max = draft.x_max
                existing.y_max = draft.y_max
                if restored:
                    existing.deleted_at = None
                existing.revision += 1
                event_type = (
                    "restored" if restored else "class_changed" if class_changed else "updated"
                )
                self.annotations.add_event(
                    self._event(
                        annotation=existing,
                        image_id=image_id,
                        event_type=event_type,
                        before_json=before,
                        after_json=annotation_snapshot(existing),
                    )
                )
                changed = True

        for annotation in existing_annotations:
            if annotation.deleted_at is None and annotation.id not in desired_ids:
                before = annotation_snapshot(annotation)
                annotation.deleted_at = utc_now()
                annotation.revision += 1
                self.annotations.add_event(
                    self._event(
                        annotation=annotation,
                        image_id=image_id,
                        event_type="deleted",
                        before_json=before,
                        after_json=annotation_snapshot(annotation),
                    )
                )
                changed = True

        existing_masks = self.mask_annotations.list_for_image(
            image_id,
            include_deleted=True,
        )
        existing_masks_by_id = {annotation.id: annotation for annotation in existing_masks}

        for mask_draft in payload.mask_annotations:
            if mask_draft.label_class_id not in project_classes:
                raise ValidationError("Mask class does not belong to this image's project")
            polygon, x_min, y_min, x_max, y_max, area_pixels = self._validated_polygon(
                mask_draft, image
            )
            existing_mask = existing_masks_by_id.get(mask_draft.id)
            if existing_mask is None:
                conflicting_mask = self.mask_annotations.get(mask_draft.id)
                if conflicting_mask is not None:
                    raise ValidationError(
                        "Mask annotations may only be saved to their source image"
                    )
                mask_annotation = MaskAnnotation(
                    id=mask_draft.id,
                    image_id=image_id,
                    label_class_id=mask_draft.label_class_id,
                    geometry_kind=mask_draft.geometry_kind,
                    polygon_json=polygon,
                    x_min=x_min,
                    y_min=y_min,
                    x_max=x_max,
                    y_max=y_max,
                    area_pixels=area_pixels,
                    source_type="human",
                    status=mask_draft.status or "verified",
                    created_by="local_user",
                    revision=1,
                )
                self.mask_annotations.add(mask_annotation)
                self.mask_annotations.add_event(
                    self._mask_event(
                        annotation=mask_annotation,
                        image_id=image_id,
                        event_type="created",
                        before_json=None,
                        after_json=mask_annotation_snapshot(mask_annotation),
                    )
                )
                changed = True
                continue

            before = mask_annotation_snapshot(existing_mask)
            class_changed = existing_mask.label_class_id != mask_draft.label_class_id
            geometry_changed = (
                existing_mask.geometry_kind != mask_draft.geometry_kind
                or existing_mask.mask_path is not None
                or existing_mask.polygon_json != polygon
                or existing_mask.x_min != x_min
                or existing_mask.y_min != y_min
                or existing_mask.x_max != x_max
                or existing_mask.y_max != y_max
                or existing_mask.area_pixels != area_pixels
            )
            restored = existing_mask.deleted_at is not None
            if class_changed or geometry_changed or restored:
                existing_mask.label_class_id = mask_draft.label_class_id
                existing_mask.geometry_kind = mask_draft.geometry_kind
                existing_mask.mask_path = None
                existing_mask.polygon_json = polygon
                existing_mask.x_min = x_min
                existing_mask.y_min = y_min
                existing_mask.x_max = x_max
                existing_mask.y_max = y_max
                existing_mask.area_pixels = area_pixels
                existing_mask.status = "verified"
                if restored:
                    existing_mask.deleted_at = None
                existing_mask.revision += 1
                event_type = (
                    "restored" if restored else "class_changed" if class_changed else "updated"
                )
                self.mask_annotations.add_event(
                    self._mask_event(
                        annotation=existing_mask,
                        image_id=image_id,
                        event_type=event_type,
                        before_json=before,
                        after_json=mask_annotation_snapshot(existing_mask),
                    )
                )
                changed = True

        requested_deletions = set(payload.deleted_mask_annotation_ids)
        for mask_id in requested_deletions:
            existing_mask = existing_masks_by_id.get(mask_id)
            if existing_mask is None or existing_mask.deleted_at is not None:
                continue
            before = mask_annotation_snapshot(existing_mask)
            existing_mask.deleted_at = utc_now()
            existing_mask.revision += 1
            self.mask_annotations.add_event(
                self._mask_event(
                    annotation=existing_mask,
                    image_id=image_id,
                    event_type="deleted",
                    before_json=before,
                    after_json=mask_annotation_snapshot(existing_mask),
                )
            )
            changed = True

        if image.annotation_status != payload.annotation_status:
            image.annotation_status = payload.annotation_status
            changed = True

        if changed:
            image.annotation_revision += 1

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(image)
        active_annotations = self.annotations.list_for_image(image_id)
        active_masks = self.mask_annotations.list_for_image(image_id)
        return AnnotationBatchSaveResponse(
            image=ImageResponse.model_validate(image),
            annotations=[
                AnnotationResponse.model_validate(annotation) for annotation in active_annotations
            ],
            mask_annotations=[
                MaskAnnotationResponse.model_validate(annotation) for annotation in active_masks
            ],
            counts_by_class=self._counts_by_class(active_annotations),
            mask_counts_by_class=self._mask_counts_by_class(active_masks),
        )

"""Transactional raster mask brush and eraser services."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import MaskAnnotation, MaskAnnotationEvent
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.mask_annotations import MaskAnnotationRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.annotations import MaskAnnotationResponse
from reefvision.schemas.images import ImageResponse
from reefvision.schemas.raster_edits import (
    RasterMaskClassUpdateRequest,
    RasterMaskDuplicateRequest,
    RasterMaskEditRequest,
    RasterMaskEditResponse,
)
from reefvision.services.annotations import mask_annotation_snapshot
from reefvision.storage.raster_edits import (
    duplicate_raster_mask_revision,
    write_raster_mask_revision,
)


class RasterMaskEditService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.images = ImageRepository(session)
        self.projects = ProjectRepository(session)
        self.masks = MaskAnnotationRepository(session)

    def duplicate(
        self,
        image_id: str,
        mask_annotation_id: str,
        payload: RasterMaskDuplicateRequest,
    ) -> RasterMaskEditResponse:
        image = self.images.get(image_id)
        if image is None:
            raise NotFoundError("Image not found")
        if image.annotation_revision != payload.base_revision:
            raise ConflictError("Annotation revision conflict")
        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        source = self.masks.get(mask_annotation_id)
        if source is None or source.deleted_at is not None:
            raise NotFoundError("Mask annotation not found")
        if source.image_id != image.id:
            raise ValidationError("Raster masks may only be copied on their source image")
        if source.geometry_kind != "raster_mask" or source.mask_path is None:
            raise ValidationError("Only persisted raster masks can be copied")

        duplicate_id = str(uuid4())
        destination_path: Path | None = None
        try:
            relative_path, destination_path = duplicate_raster_mask_revision(
                self.settings,
                project_storage_root=project.storage_root,
                image_id=image.id,
                source_relative_path=source.mask_path,
                mask_annotation_id=duplicate_id,
                expected_width=image.width_px,
                expected_height=image.height_px,
            )
            duplicate = MaskAnnotation(
                id=duplicate_id,
                image_id=image.id,
                label_class_id=source.label_class_id,
                geometry_kind="raster_mask",
                mask_path=relative_path,
                polygon_json=None,
                x_min=source.x_min,
                y_min=source.y_min,
                x_max=source.x_max,
                y_max=source.y_max,
                area_pixels=source.area_pixels,
                source_type="human_copy",
                provenance_json=None,
                status="draft",
                created_by="local_user",
                revision=1,
            )
            self.masks.add(duplicate)
            self.masks.add_event(
                MaskAnnotationEvent(
                    mask_annotation_id=duplicate.id,
                    image_id=image.id,
                    event_type="created",
                    before_json=None,
                    after_json=mask_annotation_snapshot(duplicate),
                    actor="local_user",
                )
            )
            image.annotation_revision += 1
            if image.annotation_status in {"unannotated", "reviewed"}:
                # A new draft copy invalidates image-level review completion.
                image.annotation_status = "in_progress"
            self.session.commit()
        except Exception:
            self.session.rollback()
            if destination_path is not None:
                destination_path.unlink(missing_ok=True)
            raise

        self.session.refresh(image)
        self.session.refresh(duplicate)
        return RasterMaskEditResponse(
            image=ImageResponse.model_validate(image),
            mask_annotation=MaskAnnotationResponse.model_validate(duplicate),
        )

    def reclassify(
        self,
        image_id: str,
        mask_annotation_id: str,
        payload: RasterMaskClassUpdateRequest,
    ) -> RasterMaskEditResponse:
        image = self.images.get(image_id)
        if image is None:
            raise NotFoundError("Image not found")
        if image.annotation_revision != payload.base_revision:
            raise ConflictError("Annotation revision conflict")

        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        if payload.label_class_id not in {label_class.id for label_class in project.label_classes}:
            raise ValidationError("Mask class does not belong to this image's project")

        mask = self.masks.get(mask_annotation_id)
        if mask is None or mask.deleted_at is not None:
            raise NotFoundError("Mask annotation not found")
        if mask.image_id != image.id:
            raise ValidationError("Raster masks may only be edited on their source image")
        if mask.geometry_kind != "raster_mask":
            raise ValidationError("Class reassignment requires a raster mask")

        if mask.label_class_id == payload.label_class_id:
            return RasterMaskEditResponse(
                image=ImageResponse.model_validate(image),
                mask_annotation=MaskAnnotationResponse.model_validate(mask),
            )

        before = mask_annotation_snapshot(mask)
        mask.label_class_id = payload.label_class_id
        mask.revision += 1
        self.masks.add_event(
            MaskAnnotationEvent(
                mask_annotation_id=mask.id,
                image_id=image.id,
                event_type="class_changed",
                before_json=before,
                after_json=mask_annotation_snapshot(mask),
                actor="local_user",
            )
        )
        image.annotation_revision += 1
        if image.annotation_status in {"unannotated", "reviewed"}:
            image.annotation_status = "in_progress"
        self.session.commit()
        self.session.refresh(image)
        self.session.refresh(mask)
        return RasterMaskEditResponse(
            image=ImageResponse.model_validate(image),
            mask_annotation=MaskAnnotationResponse.model_validate(mask),
        )

    def edit(
        self,
        image_id: str,
        payload: RasterMaskEditRequest,
    ) -> RasterMaskEditResponse:
        image = self.images.get(image_id)
        if image is None:
            raise NotFoundError("Image not found")
        if image.annotation_revision != payload.base_revision:
            raise ConflictError("Annotation revision conflict")
        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        if payload.label_class_id not in {label_class.id for label_class in project.label_classes}:
            raise ValidationError("Mask class does not belong to this image's project")

        existing: MaskAnnotation | None = None
        mask_id = payload.mask_annotation_id or str(uuid4())
        if payload.mask_annotation_id is not None:
            existing = self.masks.get(payload.mask_annotation_id)
            if existing is None or existing.deleted_at is not None:
                raise NotFoundError("Mask annotation not found")
            if existing.image_id != image.id:
                raise ValidationError("Raster masks may only be edited on their source image")
            if existing.geometry_kind != "raster_mask":
                raise ValidationError("Brush editing requires a raster mask")

        next_revision = existing.revision + 1 if existing is not None else 1
        source_path = existing.mask_path if existing is not None else None
        destination_path: Path | None = None
        before = mask_annotation_snapshot(existing) if existing is not None else None
        try:
            relative_path, destination_path, area_pixels, bounds = write_raster_mask_revision(
                self.settings,
                project_storage_root=project.storage_root,
                image_id=image.id,
                mask_annotation_id=mask_id,
                revision=next_revision,
                source_relative_path=source_path,
                expected_width=image.width_px,
                source_image_relative_path=image.managed_path,
                expected_height=image.height_px,
                strokes=payload.strokes,
                brush_radius=float(payload.brush_radius),
                mode=payload.mode,
                fill_tolerance=payload.fill_tolerance,
            )

            if bounds is None:
                if existing is None or payload.mode != "erase":
                    raise ValidationError("Only an existing raster mask may be erased completely")
                mask = existing
                mask.deleted_at = utc_now()
                mask.revision = next_revision
                mask.provenance_json = {
                    **(mask.provenance_json or {}),
                    "last_edit_mode": payload.mode,
                    "last_brush_radius": float(payload.brush_radius),
                    "last_stroke_count": len(payload.strokes),
                    "previous_mask_path": source_path,
                    "deleted_by_full_erase": True,
                }
                self.masks.add_event(
                    MaskAnnotationEvent(
                        mask_annotation_id=mask.id,
                        image_id=image.id,
                        event_type="deleted",
                        before_json=before,
                        after_json=mask_annotation_snapshot(mask),
                        actor="local_user",
                    )
                )
                image.annotation_revision += 1
                if image.annotation_status in {"unannotated", "reviewed"}:
                    image.annotation_status = "in_progress"
                self.session.commit()
                self.session.refresh(image)
                self.session.refresh(mask)
                return RasterMaskEditResponse(
                    image=ImageResponse.model_validate(image),
                    mask_annotation=MaskAnnotationResponse.model_validate(mask),
                )

            x_min, y_min, x_max, y_max = bounds
            if relative_path is None:
                raise ValidationError("Raster mask revision path is missing")
            if existing is None:
                mask = MaskAnnotation(
                    id=mask_id,
                    image_id=image.id,
                    label_class_id=payload.label_class_id,
                    geometry_kind="raster_mask",
                    mask_path=relative_path,
                    polygon_json=None,
                    x_min=x_min,
                    y_min=y_min,
                    x_max=x_max,
                    y_max=y_max,
                    area_pixels=area_pixels,
                    source_type="human_brush",
                    provenance_json={
                        "edit_mode": payload.mode,
                        "brush_radius": float(payload.brush_radius),
                        "stroke_count": len(payload.strokes),
                        "fill_tolerance": (
                            payload.fill_tolerance if payload.mode == "fill" else None
                        ),
                    },
                    status="verified",
                    created_by="local_user",
                    revision=1,
                )
                self.masks.add(mask)
                event_type = "created"
            else:
                mask = existing
                mask.label_class_id = payload.label_class_id
                mask.mask_path = relative_path
                mask.polygon_json = None
                mask.x_min = x_min
                mask.y_min = y_min
                mask.x_max = x_max
                mask.y_max = y_max
                mask.area_pixels = area_pixels
                mask.source_type = "human_brush"
                mask.provenance_json = {
                    **(mask.provenance_json or {}),
                    "last_edit_mode": payload.mode,
                    "last_brush_radius": float(payload.brush_radius),
                    "last_stroke_count": len(payload.strokes),
                    "last_fill_tolerance": (
                        payload.fill_tolerance if payload.mode == "fill" else None
                    ),
                    "previous_mask_path": source_path,
                }
                mask.status = "verified"
                mask.revision = next_revision
                event_type = "updated"

            self.masks.add_event(
                MaskAnnotationEvent(
                    mask_annotation_id=mask.id,
                    image_id=image.id,
                    event_type=event_type,
                    before_json=before,
                    after_json=mask_annotation_snapshot(mask),
                    actor="local_user",
                )
            )
            image.annotation_revision += 1
            if image.annotation_status in {"unannotated", "reviewed"}:
                image.annotation_status = "in_progress"
            self.session.commit()
        except Exception:
            self.session.rollback()
            if destination_path is not None:
                destination_path.unlink(missing_ok=True)
            raise

        self.session.refresh(image)
        self.session.refresh(mask)
        return RasterMaskEditResponse(
            image=ImageResponse.model_validate(image),
            mask_annotation=MaskAnnotationResponse.model_validate(mask),
        )

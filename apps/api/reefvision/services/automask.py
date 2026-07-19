"""Transactional Lightroom-style Auto Mask editing."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from reefvision.db.models import MaskAnnotation, MaskAnnotationEvent
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.annotations import MaskAnnotationResponse
from reefvision.schemas.images import ImageResponse
from reefvision.schemas.raster_edits import RasterMaskEditRequest, RasterMaskEditResponse
from reefvision.services.annotations import mask_annotation_snapshot
from reefvision.services.raster_edits import RasterMaskEditService
from reefvision.storage.automask import write_raster_automask_revision


class AutoMaskEditService(RasterMaskEditService):
    """Use the stable brush service unless Auto Mask is explicitly enabled."""

    def edit(
        self,
        image_id: str,
        payload: RasterMaskEditRequest,
    ) -> RasterMaskEditResponse:
        if not payload.auto_mask_enabled:
            return super().edit(image_id, payload)

        image = self.images.get(image_id)
        if image is None:
            raise NotFoundError("Image not found")
        if image.annotation_revision != payload.base_revision:
            raise ConflictError("Annotation revision conflict")
        project = self.projects.get(image.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        if payload.label_class_id not in {
            label_class.id for label_class in project.label_classes
        }:
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
                raise ValidationError("Auto Mask editing requires a raster mask")

        next_revision = existing.revision + 1 if existing is not None else 1
        source_path = existing.mask_path if existing is not None else None
        destination_path: Path | None = None
        before = mask_annotation_snapshot(existing) if existing is not None else None
        automask_settings = {
            "color_tolerance": float(payload.auto_mask_color_tolerance),
            "luminance_tolerance": float(payload.auto_mask_luminance_tolerance),
            "edge_sensitivity": float(payload.auto_mask_edge_sensitivity),
            "contiguous": payload.auto_mask_contiguous,
            "sample_radius": payload.auto_mask_sample_radius,
        }
        try:
            relative_path, destination_path, area_pixels, bounds = (
                write_raster_automask_revision(
                    self.settings,
                    project_storage_root=project.storage_root,
                    source_image_relative_path=image.managed_path,
                    image_id=image.id,
                    mask_annotation_id=mask_id,
                    revision=next_revision,
                    source_mask_relative_path=source_path,
                    expected_width=image.width_px,
                    expected_height=image.height_px,
                    strokes=payload.strokes,
                    brush_radius=float(payload.brush_radius),
                    mode=payload.mode,
                    color_tolerance=float(payload.auto_mask_color_tolerance),
                    luminance_tolerance=float(payload.auto_mask_luminance_tolerance),
                    edge_sensitivity=float(payload.auto_mask_edge_sensitivity),
                    contiguous=payload.auto_mask_contiguous,
                    sample_radius=payload.auto_mask_sample_radius,
                )
            )
            x_min, y_min, x_max, y_max = bounds
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
                    source_type="human_automask",
                    provenance_json={
                        "edit_mode": payload.mode,
                        "brush_radius": float(payload.brush_radius),
                        "stroke_count": len(payload.strokes),
                        "automask": automask_settings,
                    },
                    status="verified",
                    created_by="local_user",
                    revision=1,
                )
                self.masks.add(mask)
                event_type = "automask_created"
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
                mask.source_type = "human_automask"
                mask.provenance_json = {
                    **(mask.provenance_json or {}),
                    "last_edit_mode": payload.mode,
                    "last_brush_radius": float(payload.brush_radius),
                    "last_stroke_count": len(payload.strokes),
                    "last_automask": automask_settings,
                    "previous_mask_path": source_path,
                }
                mask.status = "verified"
                mask.revision = next_revision
                event_type = "automask_updated"

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
            if image.annotation_status == "unannotated":
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

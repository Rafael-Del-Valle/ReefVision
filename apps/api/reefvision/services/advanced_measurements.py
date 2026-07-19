"""Advanced coral morphology and multi-reference calibration services."""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image, ImageDraw, UnidentifiedImageError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, MaskAnnotation
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.measurement_geometry import (
    calibrate_references,
    shape_measurements,
    skeleton_measurements,
    surface_area_estimate,
)
from reefvision.schemas.advanced_measurements import (
    AdvancedMeasurementRequest,
    AdvancedMeasurementResponse,
    AdvancedShapeResponse,
    AdvancedSkeletonResponse,
    AdvancedSurfaceResponse,
    MultiReferenceCalibrationRequest,
    MultiReferenceCalibrationResponse,
)
from reefvision.storage.projects import resolve_managed_project_path

MEASUREMENT_CALIBRATION_KEY = "measurement_calibration"


def _points(payload: object) -> list[tuple[float, float]]:
    raw = payload
    if isinstance(raw, dict):
        raw = raw.get("outer", raw.get("points", raw.get("polygon", [])))
    if not isinstance(raw, list):
        return []
    points: list[tuple[float, float]] = []
    for item in raw:
        if isinstance(item, dict):
            x, y = item.get("x"), item.get("y")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            x, y = item[0], item[1]
        else:
            continue
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            points.append((float(x), float(y)))
    return points


def _holes(payload: object) -> list[list[tuple[float, float]]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("holes", [])
    if not isinstance(raw, list):
        return []
    return [points for item in raw if len(points := _points(item)) >= 3]


class AdvancedMeasurementService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _image(self, image_id: str) -> ImageAsset:
        image = self.session.get(ImageAsset, image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def _mask(self, mask_id: str) -> MaskAnnotation:
        mask = self.session.get(MaskAnnotation, mask_id)
        if mask is None or mask.deleted_at is not None:
            raise NotFoundError("Mask annotation not found")
        return mask

    def _mask_array(self, mask: MaskAnnotation, image: ImageAsset) -> np.ndarray:
        if mask.geometry_kind == "raster_mask" and mask.mask_path:
            path = resolve_managed_project_path(self.settings, mask.mask_path)
            if not path.is_file():
                raise ValidationError("Raster mask content is missing")
            try:
                with Image.open(path) as source:
                    source.load()
                    if source.size != (image.width_px, image.height_px):
                        raise ValidationError(
                            "Raster mask dimensions do not match the image"
                        )
                    return np.asarray(source.convert("L"), dtype=np.uint8) > 0
            except (OSError, UnidentifiedImageError) as exc:
                raise ValidationError("Raster mask content could not be read") from exc
        if mask.geometry_kind == "polygon" and mask.polygon_json:
            outer = _points(mask.polygon_json)
            if len(outer) < 3:
                raise ValidationError("Polygon mask has fewer than three valid points")
            raster = Image.new("L", (image.width_px, image.height_px), 0)
            draw = ImageDraw.Draw(raster)
            draw.polygon(outer, fill=255)
            for hole in _holes(mask.polygon_json):
                draw.polygon(hole, fill=0)
            return np.asarray(raster, dtype=np.uint8) > 0
        raise ValidationError("Advanced measurements require polygon or raster geometry")

    def update_multi_reference_calibration(
        self,
        image_id: str,
        request: MultiReferenceCalibrationRequest,
    ) -> MultiReferenceCalibrationResponse:
        image = self._image(image_id)
        estimate = calibrate_references(
            [
                (float(reference.pixel_distance), float(reference.physical_distance))
                for reference in request.references
            ],
            unit=request.unit,
        )
        calibration = {
            "distance_per_pixel": estimate.distance_per_pixel,
            "unit": estimate.unit,
            "source": request.source,
            "reference_length": None,
            "reference_pixel_length": None,
            "default_depth": None,
            "notes": request.notes,
            "multi_reference": {
                "references": [reference.model_dump(mode="json") for reference in request.references],
                "reference_count": estimate.reference_count,
                "residual_standard_error": estimate.residual_standard_error,
                "lower_95": estimate.lower_95,
                "upper_95": estimate.upper_95,
                "method": "least_squares_through_origin",
            },
        }
        metadata = dict(image.metadata_json or {})
        metadata[MEASUREMENT_CALIBRATION_KEY] = calibration
        image.metadata_json = metadata
        self.session.commit()
        self.session.refresh(image)
        return MultiReferenceCalibrationResponse(
            image_id=image.id,
            distance_per_pixel=estimate.distance_per_pixel,
            unit=estimate.unit,
            reference_count=estimate.reference_count,
            residual_standard_error=estimate.residual_standard_error,
            lower_95=estimate.lower_95,
            upper_95=estimate.upper_95,
            source=request.source,
            notes=request.notes,
        )

    def _calibration(self, image: ImageAsset) -> tuple[float | None, str | None, dict[str, Any]]:
        raw = dict(image.metadata_json or {}).get(MEASUREMENT_CALIBRATION_KEY)
        if not isinstance(raw, dict):
            return None, None, {}
        scale = raw.get("distance_per_pixel")
        unit = raw.get("unit")
        if not isinstance(scale, (int, float)) or scale <= 0 or not isinstance(unit, str):
            return None, None, raw
        return float(scale), unit, raw

    def measure(
        self,
        mask_annotation_id: str,
        request: AdvancedMeasurementRequest,
    ) -> AdvancedMeasurementResponse:
        mask = self._mask(mask_annotation_id)
        image = self._image(mask.image_id)
        values = self._mask_array(mask, image)
        shape = shape_measurements(values)
        _, skeleton = skeleton_measurements(
            values,
            prune_spurs_pixels=float(request.prune_spurs_pixels),
            bridge_gaps_pixels=float(request.bridge_gaps_pixels),
        )
        scale, unit, calibration = self._calibration(image)
        projected_area = float(shape.area_pixels)
        perimeter = shape.perimeter_pixels
        centerline = skeleton.total_length_pixels
        surface_unit = "pixels"
        if scale is not None:
            projected_area *= scale * scale
            perimeter *= scale
            centerline *= scale
            surface_unit = unit or "unit"
        surface = surface_area_estimate(
            method=request.surface_method,
            projected_area=projected_area,
            perimeter=perimeter,
            centerline_length=centerline,
            depth=float(request.depth_value) if request.depth_value is not None else None,
            diameter_major=(
                float(request.diameter_major) if request.diameter_major is not None else None
            ),
            diameter_minor=(
                float(request.diameter_minor) if request.diameter_minor is not None else None
            ),
            pixel_area_scale=(
                float(request.pixel_area_scale) if request.pixel_area_scale is not None else None
            ),
            uncertainty_fraction=(
                float(request.uncertainty_fraction)
                if request.uncertainty_fraction is not None
                else None
            ),
            unit=surface_unit,
        )
        warnings: list[str] = []
        if scale is None:
            warnings.append(
                "No image calibration is available; physical lengths are omitted and "
                "surface inputs are interpreted in pixel units."
            )
        multi_reference = calibration.get("multi_reference")
        if isinstance(multi_reference, dict) and multi_reference.get(
            "residual_standard_error"
        ) is not None:
            warnings.append(
                "Calibration uncertainty is stored with the image and should be included "
                "when reporting physical measurements."
            )
        return AdvancedMeasurementResponse(
            mask_annotation_id=mask.id,
            image_id=image.id,
            revision=mask.revision,
            calibrated=scale is not None,
            distance_per_pixel=scale,
            physical_unit=unit,
            shape=AdvancedShapeResponse(**shape.__dict__),
            skeleton=AdvancedSkeletonResponse(
                **{
                    **skeleton.__dict__,
                    "branch_lengths_pixels": list(skeleton.branch_lengths_pixels),
                }
            ),
            surface=AdvancedSurfaceResponse(
                method=surface.method,
                area=surface.area,
                unit_squared=surface.unit_squared,
                standard_uncertainty=surface.standard_uncertainty,
                lower_95=surface.lower_95,
                upper_95=surface.upper_95,
                assumptions=list(surface.assumptions),
            ),
            total_length_physical=(
                skeleton.total_length_pixels * scale if scale is not None else None
            ),
            longest_path_physical=(
                skeleton.longest_path_pixels * scale if scale is not None else None
            ),
            feret_max_physical=(
                shape.feret_max_pixels * scale if scale is not None else None
            ),
            feret_min_physical=(
                shape.feret_min_pixels * scale if scale is not None else None
            ),
            warnings=warnings,
        )

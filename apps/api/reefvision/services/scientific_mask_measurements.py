"""Public scientific measurement behavior for calibrated masks."""

from __future__ import annotations

from reefvision.schemas.measurements import MaskMeasurementResponse
from reefvision.services.mask_measurements import (
    MaskMeasurementService as BaseMaskMeasurementService,
)


class ScientificMaskMeasurementService(BaseMaskMeasurementService):
    """Apply conservative calibration semantics on top of the legacy service.

    Polygon masks may use a validated pixel-to-reference-plane homography. Raster masks
    are not resampled by the measurement service, so all of their physical outputs must
    remain on the scalar ``distance_per_pixel`` model even when the image also carries a
    view-specific homography.
    """

    def measure(
        self,
        mask_annotation_id: str,
        *,
        label_class_ids: list[str] | None = None,
        scientific_names: list[str] | None = None,
        state_names: list[str] | None = None,
    ) -> MaskMeasurementResponse:
        result = super().measure(
            mask_annotation_id,
            label_class_ids=label_class_ids,
            scientific_names=scientific_names,
            state_names=state_names,
        )
        scale = result.distance_per_pixel
        if (
            result.geometry_kind == "raster_mask"
            and result.calibrated
            and not result.perspective_corrected
            and scale is not None
        ):
            return result.model_copy(
                update={
                    "centroid_x_physical": result.centroid_x * scale,
                    "centroid_y_physical": result.centroid_y * scale,
                }
            )
        return result

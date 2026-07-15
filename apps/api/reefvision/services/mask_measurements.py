"""Scientific measurements for polygon and raster mask annotations."""

from __future__ import annotations

from math import hypot

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.repositories.annotations import AnnotationRepository
from reefvision.repositories.mask_annotations import MaskAnnotationRepository
from reefvision.schemas.measurements import MaskMeasurementResponse
from reefvision.storage.projects import resolve_managed_project_path

Point = tuple[float, float]


def _point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        current_x, current_y = current
        previous_x, previous_y = previous
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            intersection_x = (
                (previous_x - current_x)
                * (y - current_y)
                / (previous_y - current_y)
                + current_x
            )
            if x < intersection_x:
                inside = not inside
        previous = current
    return inside


def _polygon_measurements(points: list[Point]) -> tuple[int, float, float, float]:
    signed_double_area = sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )
    if abs(signed_double_area) < 1e-9:
        raise ValidationError("Polygon mask has zero area")
    area = abs(signed_double_area) / 2.0
    centroid_x = sum(
        (points[index][0] + points[(index + 1) % len(points)][0])
        * (
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
        )
        for index in range(len(points))
    ) / (3.0 * signed_double_area)
    centroid_y = sum(
        (points[index][1] + points[(index + 1) % len(points)][1])
        * (
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
        )
        for index in range(len(points))
    ) / (3.0 * signed_double_area)
    perimeter = sum(
        hypot(
            points[index][0] - points[(index + 1) % len(points)][0],
            points[index][1] - points[(index + 1) % len(points)][1],
        )
        for index in range(len(points))
    )
    return max(1, round(area)), perimeter, centroid_x, centroid_y


def _raster_measurements(
    path: str,
) -> tuple[int, float, float, float, set[tuple[int, int]]]:
    try:
        with Image.open(path) as image:
            grayscale = image.convert("L")
            width, height = grayscale.size
            pixels = grayscale.load()
            active = {
                (x, y)
                for y in range(height)
                for x in range(width)
                if pixels[x, y] > 0
            }
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Raster mask content could not be read") from exc
    if not active:
        raise ValidationError("Raster mask is empty")
    area = len(active)
    centroid_x = sum(x + 0.5 for x, _ in active) / area
    centroid_y = sum(y + 0.5 for _, y in active) / area
    perimeter = float(
        sum(
            neighbor not in active
            for x, y in active
            for neighbor in (
                (x - 1, y),
                (x + 1, y),
                (x, y - 1),
                (x, y + 1),
            )
        )
    )
    return area, perimeter, centroid_x, centroid_y, active


class MaskMeasurementService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.settings = settings
        self.masks = MaskAnnotationRepository(session)
        self.annotations = AnnotationRepository(session)

    def measure(self, mask_annotation_id: str) -> MaskMeasurementResponse:
        mask = self.masks.get(mask_annotation_id)
        if mask is None or mask.deleted_at is not None:
            raise NotFoundError("Mask annotation not found")
        if None in (mask.x_min, mask.y_min, mask.x_max, mask.y_max):
            raise ValidationError("Mask annotation does not have valid bounds")

        polygon: list[Point] | None = None
        raster_active: set[tuple[int, int]] | None = None
        if mask.geometry_kind == "polygon":
            if not mask.polygon_json or len(mask.polygon_json) < 3:
                raise ValidationError("Polygon mask does not have valid geometry")
            polygon = [
                (float(point[0]), float(point[1])) for point in mask.polygon_json
            ]
            area, perimeter, centroid_x, centroid_y = _polygon_measurements(polygon)
        elif mask.geometry_kind == "raster_mask":
            if not mask.mask_path:
                raise ValidationError("Raster mask content is missing")
            managed_path = resolve_managed_project_path(self.settings, mask.mask_path)
            area, perimeter, centroid_x, centroid_y, raster_active = (
                _raster_measurements(str(managed_path))
            )
        else:
            raise ValidationError(
                f"Measurements are not supported for {mask.geometry_kind} masks"
            )

        contained_box_count = 0
        for annotation in self.annotations.list_for_image(mask.image_id):
            center = (
                (annotation.x_min + annotation.x_max) / 2.0,
                (annotation.y_min + annotation.y_max) / 2.0,
            )
            if polygon is not None and _point_in_polygon(center, polygon):
                contained_box_count += 1
            elif raster_active is not None:
                pixel = (int(center[0]), int(center[1]))
                if pixel in raster_active:
                    contained_box_count += 1

        return MaskMeasurementResponse(
            mask_annotation_id=mask.id,
            image_id=mask.image_id,
            label_class_id=mask.label_class_id,
            geometry_kind=mask.geometry_kind,
            area_pixels=area,
            perimeter_pixels=perimeter,
            centroid_x=centroid_x,
            centroid_y=centroid_y,
            x_min=float(mask.x_min),
            y_min=float(mask.y_min),
            x_max=float(mask.x_max),
            y_max=float(mask.y_max),
            contained_box_count=contained_box_count,
            contained_box_density_per_1000_pixels=(
                contained_box_count / area * 1000.0
            ),
        )

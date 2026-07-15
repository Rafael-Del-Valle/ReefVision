"""Scientific measurements for polygon and raster mask annotations."""

from __future__ import annotations

from math import hypot
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.repositories.annotations import AnnotationRepository
from reefvision.repositories.mask_annotations import MaskAnnotationRepository
from reefvision.schemas.measurements import MaskMeasurementResponse
from reefvision.storage.projects import resolve_managed_project_path

Point = tuple[float, float]
RasterMask = tuple[bytes, int, int]


def _point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        current_x, current_y = current
        previous_x, previous_y = previous
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            intersection_x = (previous_x - current_x) * (y - current_y) / (
                previous_y - current_y
            ) + current_x
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


def _raster_pixel_active(raster: RasterMask, x: int, y: int) -> bool:
    data, width, height = raster
    if x < 0 or y < 0 or x >= width or y >= height:
        return False
    return data[y * width + x] > 0


def _raster_measurements(
    path: str | Path,
) -> tuple[int, float, float, float, RasterMask]:
    try:
        with Image.open(path) as image:
            grayscale = image.convert("L")
            width, height = grayscale.size
            data = grayscale.tobytes()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Raster mask content could not be read") from exc

    area = 0
    x_sum = 0.0
    y_sum = 0.0
    perimeter = 0
    raster = (data, width, height)
    for y in range(height):
        row_offset = y * width
        for x in range(width):
            if data[row_offset + x] == 0:
                continue
            area += 1
            x_sum += x + 0.5
            y_sum += y + 0.5
            perimeter += int(not _raster_pixel_active(raster, x - 1, y))
            perimeter += int(not _raster_pixel_active(raster, x + 1, y))
            perimeter += int(not _raster_pixel_active(raster, x, y - 1))
            perimeter += int(not _raster_pixel_active(raster, x, y + 1))

    if area == 0:
        raise ValidationError("Raster mask is empty")
    return area, float(perimeter), x_sum / area, y_sum / area, raster


class MaskMeasurementService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.settings = settings
        self.masks = MaskAnnotationRepository(session)
        self.annotations = AnnotationRepository(session)

    def measure(self, mask_annotation_id: str) -> MaskMeasurementResponse:
        mask = self.masks.get(mask_annotation_id)
        if mask is None or mask.deleted_at is not None:
            raise NotFoundError("Mask annotation not found")
        x_min = mask.x_min
        y_min = mask.y_min
        x_max = mask.x_max
        y_max = mask.y_max
        if x_min is None or y_min is None or x_max is None or y_max is None:
            raise ValidationError("Mask annotation does not have valid bounds")

        polygon: list[Point] | None = None
        raster: RasterMask | None = None
        if mask.geometry_kind == "polygon":
            if not mask.polygon_json or len(mask.polygon_json) < 3:
                raise ValidationError("Polygon mask does not have valid geometry")
            polygon = [(float(point[0]), float(point[1])) for point in mask.polygon_json]
            area, perimeter, centroid_x, centroid_y = _polygon_measurements(polygon)
        elif mask.geometry_kind == "raster_mask":
            if not mask.mask_path:
                raise ValidationError("Raster mask content is missing")
            managed_path = resolve_managed_project_path(self.settings, mask.mask_path)
            area, perimeter, centroid_x, centroid_y, raster = _raster_measurements(managed_path)
        else:
            raise ValidationError(f"Measurements are not supported for {mask.geometry_kind} masks")

        contained_box_count = 0
        for annotation in self.annotations.list_for_image(mask.image_id):
            center = (
                (annotation.x_min + annotation.x_max) / 2.0,
                (annotation.y_min + annotation.y_max) / 2.0,
            )
            inside_polygon = polygon is not None and _point_in_polygon(center, polygon)
            inside_raster = raster is not None and _raster_pixel_active(
                raster,
                int(center[0]),
                int(center[1]),
            )
            if inside_polygon or inside_raster:
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
            x_min=float(x_min),
            y_min=float(y_min),
            x_max=float(x_max),
            y_max=float(y_max),
            contained_box_count=contained_box_count,
            contained_box_density_per_1000_pixels=(contained_box_count / area * 1000.0),
        )

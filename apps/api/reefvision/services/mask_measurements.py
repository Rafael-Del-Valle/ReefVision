"""Scientific measurements for polygon and raster mask annotations."""

from __future__ import annotations

import csv
import io
import itertools
import json
import struct
import zipfile
from math import hypot, nan, pi
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    ImageAsset,
    MaskAnnotation,
    MaskAnnotationEvent,
    Project,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.repositories.mask_annotations import MaskAnnotationRepository
from reefvision.schemas.measurements import (
    MaskMeasurementProfileResponse,
    MaskMeasurementProfileUpdate,
    MaskMeasurementResponse,
    MeasurementCalibrationResponse,
    MeasurementCalibrationUpdate,
    MeasurementFilterResponse,
    MeasurementPoint,
)
from reefvision.storage.projects import resolve_managed_project_path

Point = tuple[float, float]
RasterMask = tuple[bytes, int, int]
MEASUREMENT_CALIBRATION_KEY = "measurement_calibration"
NUMPY_COLUMNS = [
    "area_pixels",
    "perimeter_pixels",
    "centroid_x",
    "centroid_y",
    "x_min",
    "y_min",
    "x_max",
    "y_max",
    "contained_box_count",
    "density_per_1000_pixels",
    "area_physical",
    "perimeter_physical",
    "total_linear_extension_pixels",
    "total_linear_extension_physical",
    "surface_area_physical",
]


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


def _centerline_length(points: list[MeasurementPoint]) -> float:
    return sum(
        hypot(second.x - first.x, second.y - first.y)
        for first, second in itertools.pairwise(points)
    )


def _normalized(values: list[str] | None) -> list[str]:
    return sorted({value.strip().casefold() for value in values or [] if value.strip()})


def _npy_float64_matrix(rows: list[list[float]]) -> bytes:
    column_count = len(NUMPY_COLUMNS)
    if any(len(row) != column_count for row in rows):
        raise ValidationError("NumPy measurement rows have inconsistent column counts")
    header_text = repr(
        {
            "descr": "<f8",
            "fortran_order": False,
            "shape": (len(rows), column_count),
        }
    )
    header = header_text.encode("latin-1")
    padding = (16 - ((10 + len(header) + 1) % 16)) % 16
    header += b" " * padding + b"\n"
    output = io.BytesIO()
    output.write(b"\x93NUMPY")
    output.write(bytes((1, 0)))
    output.write(struct.pack("<H", len(header)))
    output.write(header)
    for row in rows:
        output.write(struct.pack(f"<{column_count}d", *row))
    return output.getvalue()


class MaskMeasurementService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.masks = MaskAnnotationRepository(session)

    def _mask(self, mask_annotation_id: str) -> MaskAnnotation:
        mask = self.masks.get(mask_annotation_id)
        if mask is None or mask.deleted_at is not None:
            raise NotFoundError("Mask annotation not found")
        return mask

    def _image(self, image_id: str) -> ImageAsset:
        image = self.session.get(ImageAsset, image_id)
        if image is None:
            raise NotFoundError("Image not found")
        return image

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _calibration_payload(
        self,
        image: ImageAsset,
    ) -> MeasurementCalibrationUpdate | None:
        raw = dict(image.metadata_json or {}).get(MEASUREMENT_CALIBRATION_KEY)
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValidationError("Image measurement calibration metadata is invalid")
        try:
            return MeasurementCalibrationUpdate.model_validate(raw)
        except ValueError as exc:
            raise ValidationError("Image measurement calibration metadata is invalid") from exc

    def get_calibration(self, image_id: str) -> MeasurementCalibrationResponse | None:
        image = self._image(image_id)
        calibration = self._calibration_payload(image)
        if calibration is None:
            return None
        return MeasurementCalibrationResponse(
            image_id=image.id,
            **calibration.model_dump(),
        )

    def update_calibration(
        self,
        image_id: str,
        payload: MeasurementCalibrationUpdate,
    ) -> MeasurementCalibrationResponse:
        image = self._image(image_id)
        metadata = dict(image.metadata_json or {})
        metadata[MEASUREMENT_CALIBRATION_KEY] = payload.model_dump(mode="json")
        image.metadata_json = metadata
        self.session.commit()
        self.session.refresh(image)
        return MeasurementCalibrationResponse(image_id=image.id, **payload.model_dump())

    def clear_calibration(self, image_id: str) -> None:
        image = self._image(image_id)
        metadata = dict(image.metadata_json or {})
        metadata.pop(MEASUREMENT_CALIBRATION_KEY, None)
        image.metadata_json = metadata
        self.session.commit()

    def _profile(self, mask: MaskAnnotation) -> MaskMeasurementProfileResponse:
        payload = dict(mask.measurement_json or {})
        raw_points = payload.get("centerline_points", [])
        if not isinstance(raw_points, list):
            raise ValidationError("Mask centerline metadata is invalid")
        try:
            points = [MeasurementPoint.model_validate(point) for point in raw_points]
        except ValueError as exc:
            raise ValidationError("Mask centerline metadata is invalid") from exc
        surface_model = str(payload.get("surface_model", "none"))
        if surface_model not in {"none", "extruded", "cylindrical_centerline"}:
            raise ValidationError("Mask surface-area model is invalid")
        depth_value = payload.get("depth_value")
        diameter_value = payload.get("diameter_value")
        notes = payload.get("notes")
        return MaskMeasurementProfileResponse(
            mask_annotation_id=mask.id,
            image_id=mask.image_id,
            revision=mask.revision,
            centerline_points=points,
            centerline_length_pixels=_centerline_length(points),
            surface_model=surface_model,
            depth_value=float(depth_value) if isinstance(depth_value, (int, float)) else None,
            diameter_value=(
                float(diameter_value) if isinstance(diameter_value, (int, float)) else None
            ),
            notes=str(notes) if isinstance(notes, str) else None,
        )

    def get_profile(self, mask_annotation_id: str) -> MaskMeasurementProfileResponse:
        return self._profile(self._mask(mask_annotation_id))

    def update_profile(
        self,
        mask_annotation_id: str,
        payload: MaskMeasurementProfileUpdate,
    ) -> MaskMeasurementProfileResponse:
        mask = self._mask(mask_annotation_id)
        image = self._image(mask.image_id)
        if mask.revision != payload.base_revision:
            raise ConflictError("Mask measurement revision conflict")
        points = payload.centerline_points
        if any(point.x > image.width_px or point.y > image.height_px for point in points):
            raise ValidationError("Centerline points cannot extend outside the image bounds")
        if any(
            first.x == second.x and first.y == second.y
            for first, second in itertools.pairwise(points)
        ):
            raise ValidationError("Centerlines cannot contain consecutive duplicate points")

        new_measurement = {
            "centerline_points": [point.model_dump() for point in points],
            "surface_model": payload.surface_model,
            "depth_value": payload.depth_value,
            "diameter_value": payload.diameter_value,
            "notes": payload.notes,
        }
        before = {
            "measurement_json": dict(mask.measurement_json or {}),
            "revision": mask.revision,
        }
        if dict(mask.measurement_json or {}) == new_measurement:
            return self._profile(mask)
        mask.measurement_json = new_measurement
        mask.revision += 1
        image.annotation_revision += 1
        after = {
            "measurement_json": dict(mask.measurement_json),
            "revision": mask.revision,
        }
        self.masks.add_event(
            MaskAnnotationEvent(
                mask_annotation_id=mask.id,
                image_id=mask.image_id,
                event_type="measurement_updated",
                before_json=before,
                after_json=after,
                actor="local_user",
            )
        )
        self.session.commit()
        self.session.refresh(mask)
        return self._profile(mask)

    @staticmethod
    def _matches_filters(
        annotation: Annotation,
        *,
        label_class_ids: set[str],
        scientific_names: set[str],
        state_names: set[str],
    ) -> bool:
        label_class = annotation.label_class
        if label_class_ids and annotation.label_class_id not in label_class_ids:
            return False
        scientific_name = (label_class.scientific_name or "").strip().casefold()
        if scientific_names and scientific_name not in scientific_names:
            return False
        state_name = (label_class.state_name or "").strip().casefold()
        return not state_names or state_name in state_names

    def measure(
        self,
        mask_annotation_id: str,
        *,
        label_class_ids: list[str] | None = None,
        scientific_names: list[str] | None = None,
        state_names: list[str] | None = None,
    ) -> MaskMeasurementResponse:
        mask = self._mask(mask_annotation_id)
        image = self._image(mask.image_id)
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

        normalized_label_ids = set(_normalized(label_class_ids))
        normalized_scientific = set(_normalized(scientific_names))
        normalized_states = set(_normalized(state_names))
        statement = (
            select(Annotation)
            .options(selectinload(Annotation.label_class))
            .where(Annotation.image_id == mask.image_id, Annotation.deleted_at.is_(None))
            .order_by(Annotation.created_at, Annotation.id)
        )
        contained_box_count = 0
        for annotation in self.session.scalars(statement):
            if not self._matches_filters(
                annotation,
                label_class_ids=normalized_label_ids,
                scientific_names=normalized_scientific,
                state_names=normalized_states,
            ):
                continue
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

        profile = self._profile(mask)
        calibration = self._calibration_payload(image)
        scale = calibration.distance_per_pixel if calibration is not None else None
        area_physical = area * scale * scale if scale is not None else None
        perimeter_physical = perimeter * scale if scale is not None else None
        tle_pixels = profile.centerline_length_pixels
        tle_physical = tle_pixels * scale if scale is not None else None
        surface_area: float | None = None
        assumptions: list[str] = []
        if calibration is not None and profile.surface_model == "extruded":
            depth = profile.depth_value or calibration.default_depth
            if depth is not None and area_physical is not None and perimeter_physical is not None:
                surface_area = 2.0 * area_physical + perimeter_physical * depth
                assumptions = [
                    "Mask is treated as a closed planar extrusion",
                    f"Extrusion depth is {depth:g} {calibration.unit}",
                ]
            else:
                assumptions = ["Extruded surface area requires a positive depth value"]
        elif calibration is not None and profile.surface_model == "cylindrical_centerline":
            if tle_physical is not None and tle_physical > 0 and area_physical is not None:
                diameter = profile.diameter_value or area_physical / tle_physical
                surface_area = pi * diameter * tle_physical
                assumptions = [
                    "Centerline is treated as the axis of an equivalent cylinder",
                    (
                        f"Diameter is {diameter:g} {calibration.unit}"
                        if profile.diameter_value is not None
                        else "Diameter is estimated as projected area divided by centerline length"
                    ),
                ]
            else:
                assumptions = [
                    "Cylindrical surface area requires calibration and a nonzero centerline"
                ]

        density_square_unit = (
            contained_box_count / area_physical
            if area_physical is not None and area_physical > 0
            else None
        )
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
            filters=MeasurementFilterResponse(
                label_class_ids=sorted(normalized_label_ids),
                scientific_names=sorted(normalized_scientific),
                state_names=sorted(normalized_states),
            ),
            calibrated=calibration is not None,
            physical_unit=calibration.unit if calibration is not None else None,
            distance_per_pixel=scale,
            area_physical=area_physical,
            perimeter_physical=perimeter_physical,
            centroid_x_physical=centroid_x * scale if scale is not None else None,
            centroid_y_physical=centroid_y * scale if scale is not None else None,
            contained_box_density_per_square_unit=density_square_unit,
            centerline_points=profile.centerline_points,
            total_linear_extension_pixels=tle_pixels,
            total_linear_extension_physical=tle_physical,
            surface_area_model=profile.surface_model,
            surface_area_physical=surface_area,
            surface_area_assumptions=assumptions,
        )

    def measure_project(
        self,
        project_id: str,
        *,
        label_class_ids: list[str] | None = None,
        scientific_names: list[str] | None = None,
        state_names: list[str] | None = None,
    ) -> list[MaskMeasurementResponse]:
        self._project(project_id)
        statement = (
            select(MaskAnnotation.id)
            .join(ImageAsset, ImageAsset.id == MaskAnnotation.image_id)
            .where(
                ImageAsset.project_id == project_id,
                MaskAnnotation.deleted_at.is_(None),
                MaskAnnotation.status == "verified",
            )
            .order_by(ImageAsset.created_at, MaskAnnotation.created_at, MaskAnnotation.id)
        )
        return [
            self.measure(
                mask_id,
                label_class_ids=label_class_ids,
                scientific_names=scientific_names,
                state_names=state_names,
            )
            for mask_id in self.session.scalars(statement)
        ]

    @staticmethod
    def _flat_row(item: MaskMeasurementResponse) -> dict[str, Any]:
        return {
            "mask_annotation_id": item.mask_annotation_id,
            "image_id": item.image_id,
            "label_class_id": item.label_class_id or "",
            "geometry_kind": item.geometry_kind,
            "area_pixels": item.area_pixels,
            "perimeter_pixels": item.perimeter_pixels,
            "centroid_x": item.centroid_x,
            "centroid_y": item.centroid_y,
            "x_min": item.x_min,
            "y_min": item.y_min,
            "x_max": item.x_max,
            "y_max": item.y_max,
            "contained_box_count": item.contained_box_count,
            "density_per_1000_pixels": item.contained_box_density_per_1000_pixels,
            "calibrated": item.calibrated,
            "physical_unit": item.physical_unit or "",
            "distance_per_pixel": item.distance_per_pixel,
            "area_physical": item.area_physical,
            "perimeter_physical": item.perimeter_physical,
            "density_per_square_unit": item.contained_box_density_per_square_unit,
            "total_linear_extension_pixels": item.total_linear_extension_pixels,
            "total_linear_extension_physical": item.total_linear_extension_physical,
            "surface_area_model": item.surface_area_model,
            "surface_area_physical": item.surface_area_physical,
        }

    def csv_export(self, project_id: str) -> bytes:
        rows = [self._flat_row(item) for item in self.measure_project(project_id)]
        stream = io.StringIO(newline="")
        fieldnames = list(rows[0]) if rows else list(self._flat_row.__annotations__)
        if not rows:
            fieldnames = [
                "mask_annotation_id",
                "image_id",
                "label_class_id",
                "geometry_kind",
                *NUMPY_COLUMNS,
                "calibrated",
                "physical_unit",
                "distance_per_pixel",
                "density_per_square_unit",
                "surface_area_model",
            ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode("utf-8-sig")

    def numpy_export(self, project_id: str) -> bytes:
        measurements = self.measure_project(project_id)
        numeric_rows: list[list[float]] = []
        row_metadata: list[dict[str, Any]] = []
        for item in measurements:
            numeric_rows.append(
                [
                    float(item.area_pixels),
                    item.perimeter_pixels,
                    item.centroid_x,
                    item.centroid_y,
                    item.x_min,
                    item.y_min,
                    item.x_max,
                    item.y_max,
                    float(item.contained_box_count),
                    item.contained_box_density_per_1000_pixels,
                    item.area_physical if item.area_physical is not None else nan,
                    item.perimeter_physical if item.perimeter_physical is not None else nan,
                    item.total_linear_extension_pixels,
                    (
                        item.total_linear_extension_physical
                        if item.total_linear_extension_physical is not None
                        else nan
                    ),
                    item.surface_area_physical if item.surface_area_physical is not None else nan,
                ]
            )
            row_metadata.append(
                {
                    "mask_annotation_id": item.mask_annotation_id,
                    "image_id": item.image_id,
                    "label_class_id": item.label_class_id,
                    "geometry_kind": item.geometry_kind,
                    "physical_unit": item.physical_unit,
                    "surface_area_model": item.surface_area_model,
                }
            )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("measurements.npy", _npy_float64_matrix(numeric_rows))
            archive.writestr(
                "columns.json",
                json.dumps(NUMPY_COLUMNS, indent=2, sort_keys=False),
            )
            archive.writestr(
                "rows.json",
                json.dumps(row_metadata, indent=2, sort_keys=True),
            )
        return output.getvalue()

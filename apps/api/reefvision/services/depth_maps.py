"""Depth-map generation queues, imports, and mask-level 3D measurements."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import DepthMap, ImageAsset, Job, MaskAnnotation, Project
from reefvision.domain.errors import ArtifactMissingError, NotFoundError, ValidationError
from reefvision.schemas.depth import (
    CameraIntrinsics,
    DepthAwareMaskMeasurementResponse,
    DepthMapGenerateRequest,
    DepthMapImportRequest,
    DepthMapJobResponse,
    DepthMapResponse,
    DepthValueSummary,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.storage.depth_maps import load_depth_map, write_depth_map
from reefvision.storage.projects import resolve_managed_project_path


def _polygon_points(payload: object) -> list[tuple[float, float]]:
    raw = payload
    if isinstance(raw, dict):
        raw = raw.get("points", raw.get("polygon", raw.get("vertices", [])))
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


def _mask_array(
    settings: Settings,
    mask: MaskAnnotation,
    image: ImageAsset,
) -> NDArray[Any]:
    if mask.geometry_kind == "raster_mask" and mask.mask_path:
        path = resolve_managed_project_path(settings, mask.mask_path)
        if not path.is_file():
            raise ValidationError("Raster mask content is missing")
        try:
            with Image.open(path) as source:
                source.load()
                if source.size != (image.width_px, image.height_px):
                    raise ValidationError("Raster mask dimensions do not match the image")
                return np.asarray(source.convert("L"), dtype=np.uint8) > 0
        except (OSError, UnidentifiedImageError) as exc:
            raise ValidationError("Raster mask content could not be read") from exc
    if mask.geometry_kind == "polygon":
        points = _polygon_points(mask.polygon_json)
        if len(points) < 3:
            raise ValidationError("Polygon mask has fewer than three valid points")
        raster = Image.new("L", (image.width_px, image.height_px), 0)
        ImageDraw.Draw(raster).polygon(points, fill=255)
        return np.asarray(raster, dtype=np.uint8) > 0
    raise ValidationError("Depth-aware measurement requires polygon or raster geometry")


def _intrinsics(metadata: dict[str, Any]) -> CameraIntrinsics | None:
    raw = metadata.get("camera_intrinsics")
    if not isinstance(raw, dict):
        return None
    try:
        return CameraIntrinsics.model_validate(raw)
    except ValueError:
        return None


def _depth_source_kind(depth_map: DepthMap) -> str:
    metadata = dict(depth_map.metadata_json or {})
    explicit = metadata.get("depth_source_kind")
    if isinstance(explicit, str) and explicit:
        return explicit
    if depth_map.provider_id == "luminance_relative":
        return "relative_fixture"
    if depth_map.provider_id == "depth_anything_v2_relative":
        return "relative_monocular"
    if depth_map.provider_id == "depth_anything_v2_metric":
        return "metric_monocular_estimate"
    return "relative_imported" if depth_map.depth_kind == "relative" else "imported_metric"


def _point_row(
    columns: NDArray[Any],
    row_center: float,
    depth: NDArray[Any],
    intrinsics: CameraIntrinsics,
) -> NDArray[Any]:
    z = depth.astype(np.float64, copy=False)
    x = (columns - float(intrinsics.cx_px)) * z / float(intrinsics.fx_px)
    y = (row_center - float(intrinsics.cy_px)) * z / float(intrinsics.fy_px)
    return np.stack((x, y, z), axis=-1)


def _triangle_areas(
    first: NDArray[Any],
    second: NDArray[Any],
    third: NDArray[Any],
) -> NDArray[Any]:
    return 0.5 * np.linalg.norm(np.cross(second - first, third - first), axis=-1)


def _visible_surface_area(
    values: NDArray[Any],
    valid: NDArray[Any],
    intrinsics: CameraIntrinsics,
) -> tuple[float | None, int]:
    """Triangulate the visible metric-depth surface inside the mask.

    Only local triangles whose three vertices are finite, positive metric-depth mask pixels
    are included. This estimates camera-visible surface geometry; it does not reconstruct
    occluded or back-facing coral surfaces.
    """

    height, width = values.shape
    if height < 2 or width < 2:
        return None, 0
    columns = np.arange(width, dtype=np.float64) + 0.5
    area_sum = 0.0
    triangle_count = 0
    for row in range(height - 1):
        top_valid = valid[row]
        bottom_valid = valid[row + 1]
        first_mask = top_valid[:-1] & top_valid[1:] & bottom_valid[:-1]
        second_mask = bottom_valid[1:] & bottom_valid[:-1] & top_valid[1:]
        if not np.any(first_mask) and not np.any(second_mask):
            continue

        top_depth = values[row].astype(np.float64, copy=False)
        bottom_depth = values[row + 1].astype(np.float64, copy=False)
        top_points = _point_row(columns, row + 0.5, top_depth, intrinsics)
        bottom_points = _point_row(columns, row + 1.5, bottom_depth, intrinsics)

        if np.any(first_mask):
            areas = _triangle_areas(
                top_points[:-1],
                top_points[1:],
                bottom_points[:-1],
            )
            selected = areas[first_mask]
            area_sum += float(np.sum(selected))
            triangle_count += int(selected.size)
        if np.any(second_mask):
            areas = _triangle_areas(
                bottom_points[1:],
                bottom_points[:-1],
                top_points[1:],
            )
            selected = areas[second_mask]
            area_sum += float(np.sum(selected))
            triangle_count += int(selected.size)

    return (area_sum if triangle_count else None), triangle_count


class DepthMapService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

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

    def _depth_map(self, depth_map_id: str) -> DepthMap:
        depth_map = self.session.get(DepthMap, depth_map_id)
        if depth_map is None:
            raise NotFoundError("Depth map not found")
        return depth_map

    def _matching(
        self,
        image_id: str,
        *,
        provider_id: str,
        model_id: str,
        depth_kind: str,
    ) -> DepthMap | None:
        return self.session.scalar(
            select(DepthMap).where(
                DepthMap.image_id == image_id,
                DepthMap.provider_id == provider_id,
                DepthMap.model_id == model_id,
                DepthMap.depth_kind == depth_kind,
            )
        )

    def list_for_image(self, image_id: str) -> list[DepthMapResponse]:
        self._image(image_id)
        maps = list(
            self.session.scalars(
                select(DepthMap)
                .where(DepthMap.image_id == image_id)
                .order_by(DepthMap.created_at.desc(), DepthMap.id)
            )
        )
        return [DepthMapResponse.model_validate(item) for item in maps]

    def get(self, depth_map_id: str) -> DepthMapResponse:
        return DepthMapResponse.model_validate(self._depth_map(depth_map_id))

    def queue_generation(
        self,
        image_id: str,
        request: DepthMapGenerateRequest,
    ) -> DepthMapJobResponse:
        image = self._image(image_id)
        self._project(image.project_id)
        existing = self._matching(
            image.id,
            provider_id=request.provider_id,
            model_id=request.model_id,
            depth_kind=request.depth_kind,
        )
        depth_map_id = existing.id if existing is not None else str(uuid4())
        job = Job(
            project_id=image.project_id,
            job_type="depth_map",
            status="queued",
            progress_total=1,
            request_json={
                "depth_map_id": depth_map_id,
                "image_id": image.id,
                **request.model_dump(mode="json"),
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return DepthMapJobResponse(
            depth_map_id=depth_map_id,
            job=JobResponse.model_validate(job),
        )

    def import_values(
        self,
        image_id: str,
        request: DepthMapImportRequest,
    ) -> DepthMapResponse:
        image = self._image(image_id)
        project = self._project(image.project_id)
        values = np.asarray(request.values, dtype=np.float32)
        depth_map = self._matching(
            image.id,
            provider_id=request.provider_id,
            model_id=request.model_id,
            depth_kind=request.depth_kind,
        )
        if depth_map is None:
            depth_map = DepthMap(
                id=str(uuid4()),
                project_id=project.id,
                image_id=image.id,
                provider_id=request.provider_id,
                model_id=request.model_id,
                depth_kind=request.depth_kind,
                unit=request.unit,
                managed_path="",
                preview_path="",
                sha256="",
                width_px=image.width_px,
                height_px=image.height_px,
                minimum_depth=0,
                maximum_depth=0,
                median_depth=0,
                valid_pixel_count=0,
            )
        old_paths = (depth_map.managed_path, depth_map.preview_path)
        relative, preview, digest, stats = write_depth_map(
            self.settings,
            project_storage_root=project.storage_root,
            image_id=image.id,
            depth_map_id=f"{depth_map.id}-{uuid4().hex[:8]}",
            values=values,
            expected_width=image.width_px,
            expected_height=image.height_px,
            depth_kind=request.depth_kind,
        )
        metadata = dict(request.metadata)
        if request.camera_intrinsics is not None:
            metadata["camera_intrinsics"] = request.camera_intrinsics.model_dump(mode="json")
        metadata["source"] = "imported_values"
        metadata["depth_source_kind"] = request.source_kind
        depth_map.model_checksum = request.model_checksum
        depth_map.unit = request.unit
        depth_map.managed_path = relative
        depth_map.preview_path = preview
        depth_map.sha256 = digest
        depth_map.width_px = image.width_px
        depth_map.height_px = image.height_px
        depth_map.minimum_depth = float(stats["minimum_depth"])
        depth_map.maximum_depth = float(stats["maximum_depth"])
        depth_map.median_depth = float(stats["median_depth"])
        depth_map.valid_pixel_count = int(stats["valid_pixel_count"])
        depth_map.metadata_json = metadata
        self.session.add(depth_map)
        self.session.commit()
        for old in old_paths:
            if old and old not in {relative, preview}:
                resolve_managed_project_path(self.settings, old).unlink(missing_ok=True)
        self.session.refresh(depth_map)
        return DepthMapResponse.model_validate(depth_map)

    def content_path(self, depth_map_id: str, *, preview: bool) -> Path:
        depth_map = self._depth_map(depth_map_id)
        managed = depth_map.preview_path if preview else depth_map.managed_path
        path = resolve_managed_project_path(self.settings, managed)
        if not path.is_file():
            artifact = "preview" if preview else "content"
            raise ArtifactMissingError(f"The depth map {artifact} artifact is missing")
        return path

    def measure_mask(
        self,
        mask_annotation_id: str,
        *,
        depth_map_id: str | None = None,
    ) -> DepthAwareMaskMeasurementResponse:
        mask = self.session.get(MaskAnnotation, mask_annotation_id)
        if mask is None or mask.deleted_at is not None:
            raise NotFoundError("Mask annotation not found")
        image = self._image(mask.image_id)
        if depth_map_id is None:
            depth_map = self.session.scalar(
                select(DepthMap)
                .where(DepthMap.image_id == image.id)
                .order_by(DepthMap.depth_kind.desc(), DepthMap.created_at.desc())
            )
        else:
            depth_map = self._depth_map(depth_map_id)
        if depth_map is None or depth_map.image_id != image.id:
            raise ValidationError("Choose a depth map aligned to the mask image")
        values = load_depth_map(
            self.settings,
            depth_map.managed_path,
            expected_width=image.width_px,
            expected_height=image.height_px,
        )
        region = _mask_array(self.settings, mask, image)
        finite = np.isfinite(values)
        if depth_map.depth_kind == "metric":
            valid = region & finite & (values > 0)
        else:
            valid = region & finite
        selected = values[valid]
        if selected.size == 0:
            raise ValidationError("The mask contains no valid depth pixels")
        pixel_area = int(np.count_nonzero(region))
        depth_summary = DepthValueSummary(
            valid_pixel_count=int(selected.size),
            minimum=float(np.min(selected)),
            percentile_05=float(np.percentile(selected, 5)),
            median=float(np.median(selected)),
            mean=float(np.mean(selected)),
            percentile_95=float(np.percentile(selected, 95)),
            maximum=float(np.max(selected)),
        )
        median = float(np.median(selected))
        relative_index = (
            float(np.sum((selected / median) ** 2)) if median != 0 and np.isfinite(median) else None
        )
        warnings: list[str] = []
        metadata = dict(depth_map.metadata_json or {})
        source_kind = _depth_source_kind(depth_map)
        intrinsics = _intrinsics(metadata)
        metric_area = metric_width = metric_height = None
        visible_surface_area_3d = None
        surface_triangle_count = 0
        centroid_x = centroid_y = centroid_z = None
        area_unit = None
        physical_measurements_valid = False
        method = "relative_depth_region_statistics"
        if depth_map.depth_kind == "metric":
            if not depth_map.unit:
                warnings.append(
                    "Metric depth lacks a physical unit, so physical dimensions and areas are "
                    "suppressed until the depth source is assigned a valid unit."
                )
            elif intrinsics is None:
                warnings.append(
                    "Metric depth is available, but physical area and dimensions require "
                    "camera intrinsics (fx, fy, cx, cy)."
                )
            else:
                rows, columns = np.nonzero(valid)
                z = values[valid].astype(np.float64)
                x = (columns.astype(np.float64) + 0.5 - intrinsics.cx_px) * z / intrinsics.fx_px
                y = (rows.astype(np.float64) + 0.5 - intrinsics.cy_px) * z / intrinsics.fy_px
                metric_area = float(np.sum((z**2) / (intrinsics.fx_px * intrinsics.fy_px)))
                metric_width = float(np.max(x) - np.min(x))
                metric_height = float(np.max(y) - np.min(y))
                centroid_x = float(np.mean(x))
                centroid_y = float(np.mean(y))
                centroid_z = float(np.mean(z))
                visible_surface_area_3d, surface_triangle_count = _visible_surface_area(
                    values,
                    valid,
                    intrinsics,
                )
                area_unit = f"{depth_map.unit}^2"
                physical_measurements_valid = True
                method = "metric_depth_pinhole_projection_and_visible_surface_triangulation"
                warnings.append(
                    "Projected area is the camera-facing pinhole projection of valid mask "
                    "pixels; it is not surface area on a strongly angled or curved coral."
                )
                if visible_surface_area_3d is None:
                    warnings.append(
                        "The mask did not contain enough adjacent valid metric-depth pixels to "
                        "triangulate a visible 3D surface."
                    )
                else:
                    warnings.append(
                        "Visible 3D surface area triangulates only the camera-visible depth "
                        "surface. Occluded and back-facing coral surfaces are not reconstructed."
                    )
            if source_kind == "metric_monocular_estimate":
                warnings.append(
                    "Metric monocular depth is model-estimated. Validate scale and error against "
                    "an independent physical reference before treating measurements as ground truth."
                )
            elif source_kind == "imported_metric":
                warnings.append(
                    "Imported metric depth has no sensor class beyond its supplied provenance; "
                    "confirm the source calibration before quantitative scientific use."
                )
        else:
            if source_kind == "relative_fixture":
                warnings.append(
                    "This relative depth map is a deterministic fixture for workflow testing and "
                    "must not be interpreted as scientific scene depth."
                )
            warnings.append(
                "Relative monocular depth supports ordering and normalized indices only; it "
                "cannot produce absolute object dimensions or physical area without metric depth."
            )
        if selected.size < pixel_area:
            warnings.append(
                f"{pixel_area - selected.size} mask pixels lacked valid depth and were excluded."
            )
        return DepthAwareMaskMeasurementResponse(
            mask_annotation_id=mask.id,
            image_id=image.id,
            depth_map_id=depth_map.id,
            depth_kind=depth_map.depth_kind,
            source_kind=source_kind,
            unit=depth_map.unit,
            area_unit=area_unit,
            depth=depth_summary,
            pixel_area=pixel_area,
            depth_weighted_area_index=relative_index,
            metric_area=metric_area,
            metric_projected_area=metric_area,
            visible_surface_area_3d=visible_surface_area_3d,
            surface_triangle_count=surface_triangle_count,
            metric_width=metric_width,
            metric_height=metric_height,
            centroid_x=centroid_x,
            centroid_y=centroid_y,
            centroid_z=centroid_z,
            camera_intrinsics=intrinsics,
            physical_measurements_valid=physical_measurements_valid,
            method=method,
            warnings=warnings,
        )

"""Depth-map generation queues, imports, and mask-level 3D measurements."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import DepthMap, ImageAsset, Job, MaskAnnotation, Project
from reefvision.domain.errors import NotFoundError, ValidationError
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
) -> np.ndarray:
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
            raise NotFoundError("Depth map content is missing")
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
        valid = region & np.isfinite(values)
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
        intrinsics = _intrinsics(dict(depth_map.metadata_json or {}))
        metric_area = metric_width = metric_height = None
        centroid_x = centroid_y = centroid_z = None
        method = "relative_depth_region_statistics"
        if depth_map.depth_kind == "metric":
            if intrinsics is None:
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
                method = "metric_depth_pinhole_fronto_parallel_projection"
                warnings.append(
                    "Projected area assumes locally fronto-parallel pixels; strongly angled "
                    "or curved surfaces require multi-view reconstruction for true surface area."
                )
        else:
            warnings.append(
                "Relative monocular depth supports ordering and normalized indices only; it "
                "cannot produce absolute object dimensions without metric calibration."
            )
        if selected.size < pixel_area:
            warnings.append(
                f"{pixel_area - selected.size} mask pixels lacked finite depth and were excluded."
            )
        return DepthAwareMaskMeasurementResponse(
            mask_annotation_id=mask.id,
            image_id=image.id,
            depth_map_id=depth_map.id,
            depth_kind=depth_map.depth_kind,
            unit=depth_map.unit,
            depth=depth_summary,
            pixel_area=pixel_area,
            depth_weighted_area_index=relative_index,
            metric_area=metric_area,
            metric_width=metric_width,
            metric_height=metric_height,
            centroid_x=centroid_x,
            centroid_y=centroid_y,
            centroid_z=centroid_z,
            camera_intrinsics=intrinsics,
            method=method,
            warnings=warnings,
        )

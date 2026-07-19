"""Background image-depth generation jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import DepthMap, ImageAsset, Job, Project
from reefvision.ml.depth_runtime import generate_depth_map
from reefvision.storage.depth_maps import write_depth_map
from reefvision.storage.projects import resolve_managed_project_path


def process_depth_map_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "depth_map" or job.status != "queued":
            return False
        request = dict(job.request_json)
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        job.result_json = {"stage": "loading_depth_provider"}
        session.commit()

    try:
        image_id = str(request["image_id"])
        provider_id = str(request["provider_id"])
        model_id = str(request["model_id"])
        depth_kind = str(request["depth_kind"])
        with factory() as session:
            image = session.get(ImageAsset, image_id)
            project = session.get(Project, image.project_id) if image is not None else None
            if image is None or project is None:
                raise RuntimeError("Depth job references a missing image or project")
            image_path = resolve_managed_project_path(settings, image.managed_path)
            width, height = image.width_px, image.height_px
            project_storage_root = project.storage_root

        values, runtime_metadata = generate_depth_map(
            image_path,
            provider_id=provider_id,
            model_id=model_id,
            device=str(request.get("device", "auto")),
            local_files_only=bool(request.get("local_files_only", True)),
            maximum_metric_depth=(
                float(request["maximum_metric_depth"])
                if request.get("maximum_metric_depth") is not None
                else None
            ),
        )
        requested_id = str(request["depth_map_id"])
        artifact_id = f"{requested_id}-{uuid4().hex[:8]}"
        relative, preview, digest, stats = write_depth_map(
            settings,
            project_storage_root=project_storage_root,
            image_id=image_id,
            depth_map_id=artifact_id,
            values=values,
            expected_width=width,
            expected_height=height,
            depth_kind=depth_kind,
        )

        old_paths: tuple[str, str] = ("", "")
        with factory() as session:
            job = session.get(Job, job_id)
            image = session.get(ImageAsset, image_id)
            if job is None or image is None:
                raise RuntimeError("Depth job records disappeared during generation")
            depth_map = session.scalar(
                select(DepthMap).where(
                    DepthMap.image_id == image_id,
                    DepthMap.provider_id == provider_id,
                    DepthMap.model_id == model_id,
                    DepthMap.depth_kind == depth_kind,
                )
            )
            if depth_map is None:
                depth_map = DepthMap(
                    id=requested_id,
                    project_id=image.project_id,
                    image_id=image.id,
                    provider_id=provider_id,
                    model_id=model_id,
                    depth_kind=depth_kind,
                    unit=request.get("unit"),
                    managed_path=relative,
                    preview_path=preview,
                    sha256=digest,
                    width_px=width,
                    height_px=height,
                    minimum_depth=float(stats["minimum_depth"]),
                    maximum_depth=float(stats["maximum_depth"]),
                    median_depth=float(stats["median_depth"]),
                    valid_pixel_count=int(stats["valid_pixel_count"]),
                )
                session.add(depth_map)
            else:
                old_paths = (depth_map.managed_path, depth_map.preview_path)
                depth_map.managed_path = relative
                depth_map.preview_path = preview
                depth_map.sha256 = digest
                depth_map.width_px = width
                depth_map.height_px = height
                depth_map.minimum_depth = float(stats["minimum_depth"])
                depth_map.maximum_depth = float(stats["maximum_depth"])
                depth_map.median_depth = float(stats["median_depth"])
                depth_map.valid_pixel_count = int(stats["valid_pixel_count"])
            metadata = {
                **runtime_metadata,
                "source_image_sha256": image.sha256,
                "generation_request": request,
            }
            camera_intrinsics = request.get("camera_intrinsics")
            if isinstance(camera_intrinsics, dict):
                metadata["camera_intrinsics"] = camera_intrinsics
            depth_map.model_checksum = request.get("model_checksum")
            depth_map.unit = request.get("unit")
            depth_map.metadata_json = metadata
            job.status = "succeeded"
            job.progress_current = 1
            job.result_json = {
                "stage": "completed",
                "depth_map_id": depth_map.id,
                "depth_kind": depth_kind,
                "minimum_depth": depth_map.minimum_depth,
                "maximum_depth": depth_map.maximum_depth,
                "median_depth": depth_map.median_depth,
                "preview_path": preview,
            }
            job.completed_at = datetime.now(UTC)
            session.commit()
        for old in old_paths:
            if old and old not in {relative, preview}:
                resolve_managed_project_path(settings, old).unlink(missing_ok=True)
        return True
    except Exception as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
                session.commit()
        return False

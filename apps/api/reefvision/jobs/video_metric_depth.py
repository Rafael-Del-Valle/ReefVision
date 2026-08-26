"""Background Metric Video Depth Anything → fish-track → XYZ Scientific 3D job."""

from __future__ import annotations

import hashlib
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, Project, VideoAsset, VideoTrack
from reefvision.domain.errors import ValidationError
from reefvision.ml.video_depth_anything import (
    MetricVideoDepthAnythingProvider,
    VideoMetricDepthInference,
)
from reefvision.schemas.video_science import VideoDepthTrackAnalyticsRequest
from reefvision.services.scientific_3d import group_3d_frame_metrics, robust_track_depth
from reefvision.services.video_metric_depth_preview import (
    PREVIEW_SCALING,
    metric_depth_display_range,
)
from reefvision.services.video_science import VideoScienceService
from reefvision.services.video_tracks import VideoTrackService
from reefvision.storage.projects import resolve_managed_project_path

JOB_TYPE = "video_metric_depth_3d"
DEPTH_TIER = "model_estimated_metric"


def metric_video_depth_provider(settings: Settings) -> MetricVideoDepthAnythingProvider:
    return MetricVideoDepthAnythingProvider(settings)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fail(factory: sessionmaker[Session], job_id: str, message: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = message
        job.completed_at = datetime.now(UTC)
        session.commit()


def _scaled_bbox(
    bbox: tuple[float, float, float, float],
    *,
    source_width: int,
    source_height: int,
    depth_width: int,
    depth_height: int,
) -> tuple[float, float, float, float]:
    x, y, width, height = bbox
    scale_x = depth_width / source_width
    scale_y = depth_height / source_height
    return (
        x * scale_x,
        y * scale_y,
        (x + width) * scale_x,
        (y + height) * scale_y,
    )


def _group_metrics(analytics: Any, fps: float) -> list[dict[str, Any]]:
    xyz_by_frame: dict[int, list[list[float]]] = defaultdict(list)
    for track in analytics.tracks:
        for point in track.points:
            xyz_by_frame[point.frame].append([point.x, point.y, point.z])
    result: list[dict[str, Any]] = []
    for frame in sorted(xyz_by_frame):
        points = xyz_by_frame[frame]
        if len(points) < 2:
            continue
        metrics = group_3d_frame_metrics(points)
        result.append(
            {
                "frame": frame,
                "timestamp_seconds": frame / fps,
                "individual_count": metrics.individual_count,
                "centroid_x": metrics.centroid_x,
                "centroid_y": metrics.centroid_y,
                "centroid_z": metrics.centroid_z,
                "mean_nearest_neighbor_distance": metrics.mean_nearest_neighbor_distance,
                "mean_pairwise_distance": metrics.mean_pairwise_distance,
                "bounding_box_volume": metrics.bounding_box_volume,
            }
        )
    return result


def process_video_metric_depth_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    output_directory: Path | None = None
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != JOB_TYPE or job.status != "queued":
            return False
        request = dict(job.request_json or {})
        video = session.get(VideoAsset, str(request.get("video_id", "")))
        if video is None:
            job.status = "failed"
            job.error_message = "Scientific 3D video was not found"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        project = session.get(Project, video.project_id)
        if project is None:
            job.status = "failed"
            job.error_message = "Scientific 3D project was not found"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        track_ids = [str(value) for value in request.get("track_ids", [])]
        tracks = list(
            session.scalars(
                select(VideoTrack).where(
                    VideoTrack.id.in_(track_ids),
                    VideoTrack.video_id == video.id,
                    VideoTrack.deleted_at.is_(None),
                )
            )
        )
        if len(tracks) != len(track_ids):
            job.status = "failed"
            job.error_message = (
                "Scientific 3D tracks must be active and belong to the selected video"
            )
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        try:
            VideoScienceService(session).get_camera_intrinsics(video.id)
        except Exception as exc:
            job.status = "failed"
            job.error_message = f"Scientific 3D requires camera intrinsics: {exc}"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False

        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.progress_current = 0
        job.progress_total = video.frame_count
        job.error_message = None
        job.result_json = {
            "stage": "metric_depth_inference",
            "video_id": video.id,
            "depth_tier": DEPTH_TIER,
            "physical_measurement_claim_allowed": False,
        }
        session.commit()

        video_id = video.id
        video_path = video.managed_path
        project_storage_root = project.storage_root
        expected_frame_count = video.frame_count
        expected_fps = video.fps
        source_width = video.width_px
        source_height = video.height_px

    try:
        provider = metric_video_depth_provider(settings)
        inference: VideoMetricDepthInference = provider.infer(
            resolve_managed_project_path(settings, video_path),
            expected_frame_count=expected_frame_count,
            expected_fps=expected_fps,
            input_size=int(request.get("input_size", 518)),
            max_res=int(request.get("max_res", 1280)),
            device=str(request.get("device", "auto")),
            allow_model_download=bool(request.get("allow_model_download", False)),
            allow_resolution_fallback=bool(request.get("allow_resolution_fallback", True)),
        )
        depths = np.asarray(inference.depths, dtype=np.float32)
        if depths.ndim != 3 or depths.shape[0] < 1:
            raise ValidationError("Metric Video Depth Anything returned an invalid depth stack")

        relative_output = f"{project_storage_root}/derived/video-depth-3d/{job_id}"
        output_directory = resolve_managed_project_path(settings, relative_output)
        output_directory.mkdir(parents=True, exist_ok=True)
        depth_path = output_directory / "metric_depths.npz"
        np.savez_compressed(depth_path, depths=depths)
        depth_checksum = _sha256(depth_path)
        display_depth_min_m, display_depth_max_m = metric_depth_display_range(depths)

        with factory() as session:
            job = session.get(Job, job_id)
            video = session.get(VideoAsset, video_id)
            if job is None or video is None:
                raise RuntimeError("Scientific 3D database records disappeared")
            if job.status == "cancel_requested":
                job.status = "cancelled"
                job.completed_at = datetime.now(UTC)
                session.commit()
                shutil.rmtree(output_directory, ignore_errors=True)
                return True

            track_service = VideoTrackService(session)
            samples: list[dict[str, Any]] = []
            skipped_observations = 0
            warnings = list(inference.warnings)
            accepted_track_ids: list[str] = []
            depth_height, depth_width = depths.shape[1:]
            core_fraction = float(request.get("core_fraction", 0.6))
            minimum_valid_fraction = float(request.get("minimum_valid_fraction", 0.25))

            for track_id in [str(value) for value in request.get("track_ids", [])]:
                interpolation = track_service.interpolate(track_id)
                track_samples: list[dict[str, Any]] = []
                for frame in interpolation.frames:
                    if frame.frame >= depths.shape[0]:
                        skipped_observations += 1
                        continue
                    scaled = _scaled_bbox(
                        frame.bbox,
                        source_width=source_width,
                        source_height=source_height,
                        depth_width=depth_width,
                        depth_height=depth_height,
                    )
                    try:
                        estimate = robust_track_depth(
                            depths[frame.frame],
                            scaled,
                            core_fraction=core_fraction,
                            minimum_valid_fraction=minimum_valid_fraction,
                        )
                    except ValueError:
                        skipped_observations += 1
                        continue
                    track_samples.append(
                        {
                            "track_id": track_id,
                            "frame": frame.frame,
                            "depth": estimate.depth,
                            "confidence": estimate.confidence,
                        }
                    )
                if len(track_samples) < 2:
                    warnings.append(
                        f"Track {track_id} had fewer than two valid metric-depth observations "
                        "and was excluded from 3D trajectory metrics."
                    )
                    continue
                accepted_track_ids.append(track_id)
                samples.extend(track_samples)

            if not samples:
                raise ValidationError(
                    "Scientific 3D found no tracks with at least two valid "
                    "metric-depth observations"
                )

            analytics_request = VideoDepthTrackAnalyticsRequest.model_validate(
                {
                    "unit": "m",
                    "samples": samples,
                    "maximum_frame_gap": request.get("maximum_frame_gap"),
                }
            )
            analytics = VideoScienceService(session).depth_track_analytics(
                video_id,
                analytics_request,
            )
            group_frames = _group_metrics(analytics, video.fps)

            result = {
                "schema_version": "video-metric-depth-3d-job-0001",
                "stage": "complete",
                "project_id": video.project_id,
                "video_id": video_id,
                "provider_id": provider.provider_id,
                "provider_version": provider.provider_version,
                "model_repo": inference.model_repo,
                "model_revision": inference.model_revision,
                "model_sha256": inference.model_sha256,
                "source_commit": inference.source_commit,
                "device": inference.device,
                "input_size_requested": int(request.get("input_size", 518)),
                "input_size_used": inference.input_size_used,
                "max_res": int(request.get("max_res", 1280)),
                "depth_tier": DEPTH_TIER,
                "physical_measurement_claim_allowed": False,
                "underwater_validation_required": True,
                "depth_stack_path": f"{relative_output}/metric_depths.npz",
                "depth_stack_sha256": depth_checksum,
                "depth_stack_shape": list(depths.shape),
                "depth_preview": {
                    "display_min_m": display_depth_min_m,
                    "display_max_m": display_depth_max_m,
                    "scaling": PREVIEW_SCALING,
                    "invalid_pixels": "finite_positive_depth_only",
                    "colorization_only": True,
                },
                "decoded_frame_count": inference.decoded_frame_count,
                "metric_depth_sample_count": len(samples),
                "skipped_depth_observations": skipped_observations,
                "source_track_ids": [str(value) for value in request.get("track_ids", [])],
                "analyzed_track_ids": accepted_track_ids,
                "analytics": analytics.model_dump(mode="json"),
                "group_3d_frames": group_frames,
                "warnings": warnings,
                "scientific_provenance": {
                    "depth_source": "Metric Video Depth Anything Small",
                    "depth_interpretation": "model_estimated_metric",
                    "track_depth_statistic": "central_bbox_median",
                    "track_depth_dispersion": "MAD-derived robust relative spread",
                    "physical_measurement_claim_allowed": False,
                    "reason": (
                        "Monocular metric depth has not yet been independently validated "
                        "for this underwater camera/scene geometry."
                    ),
                },
            }
            job.status = "succeeded"
            job.progress_current = video.frame_count
            job.result_json = result
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        if output_directory is not None:
            shutil.rmtree(output_directory, ignore_errors=True)
        _fail(factory, job_id, str(exc))
        return False

"""Background rendering for annotated, trajectory, and heatmap video exports."""

from __future__ import annotations

import hashlib
import shutil
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import ArtifactRecord, Job, LabelClass, Project, VideoAsset, VideoTrack
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_bytes
from reefvision.storage.projects import resolve_managed_project_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _color(track_id: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(track_id.encode("utf-8")).digest()
    return (
        64 + int(digest[0]) % 192,
        64 + int(digest[1]) % 192,
        64 + int(digest[2]) % 192,
    )


@dataclass(frozen=True, slots=True)
class BoxState:
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    confidence: float | None

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x_min + self.x_max) / 2.0, (self.y_min + self.y_max) / 2.0)


class TrackInterpolator:
    def __init__(self, track: VideoTrack) -> None:
        self.track = track
        self.keyframes = sorted(
            [
                item
                for item in track.keyframes_json
                if isinstance(item, dict) and "frame_index" in item
            ],
            key=lambda item: int(item["frame_index"]),
        )
        self.frames = [int(item["frame_index"]) for item in self.keyframes]

    def state(self, frame_index: int) -> BoxState | None:
        if not self.keyframes or frame_index < self.frames[0] or frame_index > self.frames[-1]:
            return None
        import bisect

        position = bisect.bisect_left(self.frames, frame_index)
        if position < len(self.frames) and self.frames[position] == frame_index:
            return self._from_keyframe(self.keyframes[position])
        if position == 0 or position >= len(self.frames):
            return None
        left = self.keyframes[position - 1]
        right = self.keyframes[position]
        left_frame = int(left["frame_index"])
        right_frame = int(right["frame_index"])
        if right_frame <= left_frame:
            return self._from_keyframe(left)
        alpha = (frame_index - left_frame) / (right_frame - left_frame)
        confidence_left = left.get("confidence")
        confidence_right = right.get("confidence")
        confidence = None
        if confidence_left is not None and confidence_right is not None:
            confidence = float(confidence_left) + alpha * (
                float(confidence_right) - float(confidence_left)
            )
        elif confidence_left is not None:
            confidence = float(confidence_left)
        elif confidence_right is not None:
            confidence = float(confidence_right)
        return BoxState(
            x_min=float(left["x_min"]) + alpha * (float(right["x_min"]) - float(left["x_min"])),
            y_min=float(left["y_min"]) + alpha * (float(right["y_min"]) - float(left["y_min"])),
            x_max=float(left["x_max"]) + alpha * (float(right["x_max"]) - float(left["x_max"])),
            y_max=float(left["y_max"]) + alpha * (float(right["y_max"]) - float(left["y_max"])),
            confidence=confidence,
        )

    @staticmethod
    def _from_keyframe(item: dict[str, Any]) -> BoxState:
        return BoxState(
            x_min=float(item["x_min"]),
            y_min=float(item["y_min"]),
            x_max=float(item["x_max"]),
            y_max=float(item["y_max"]),
            confidence=(float(item["confidence"]) if item.get("confidence") is not None else None),
        )


def _clip_box(state: BoxState, width: int, height: int) -> tuple[int, int, int, int]:
    return (
        max(0, min(width - 1, round(state.x_min))),
        max(0, min(height - 1, round(state.y_min))),
        max(0, min(width - 1, round(state.x_max))),
        max(0, min(height - 1, round(state.y_max))),
    )


def _build_heatmap(
    interpolators: list[TrackInterpolator],
    *,
    width: int,
    height: int,
    maximum_frames: int,
    radius: int,
) -> NDArray[Any]:
    try:
        import cv2
    except Exception as exc:
        raise ValidationError(f"Video rendering requires OpenCV: {exc}") from exc
    density = np.zeros((height, width), dtype=np.float32)
    for frame_index in range(maximum_frames):
        for interpolator in interpolators:
            state = interpolator.state(frame_index)
            if state is None:
                continue
            center_x, center_y = state.center
            x = max(0, min(width - 1, round(center_x)))
            y = max(0, min(height - 1, round(center_y)))
            density[y, x] += 1.0
    if not np.any(density):
        return np.zeros((height, width, 3), dtype=np.uint8)
    blurred = cv2.GaussianBlur(
        density,
        (0, 0),
        sigmaX=max(1.0, radius / 3.0),
        sigmaY=max(1.0, radius / 3.0),
    )
    normalized_float = np.empty_like(blurred)
    cv2.normalize(
        blurred,
        normalized_float,
        0,
        255,
        cv2.NORM_MINMAX,
    )
    normalized = normalized_float.astype(np.uint8)
    return np.asarray(
        cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO),
        dtype=np.uint8,
    )


def _label_for_track(
    track: VideoTrack,
    class_names: dict[str, str],
) -> str:
    class_name = class_names.get(str(track.label_class_id)) if track.label_class_id else None
    return class_name or f"Track {track.track_number}"


def process_video_render_export_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "video_render_export" or job.status != "queued":
            return False
        request = dict(job.request_json)
        video = session.get(VideoAsset, str(request.get("video_id", "")))
        project = session.get(Project, video.project_id) if video is not None else None
        if video is None or project is None:
            job.status = "failed"
            job.error_message = "Video export references a missing video or project"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        tracks = list(
            session.scalars(
                select(VideoTrack).where(
                    VideoTrack.id.in_([str(item) for item in request.get("resolved_track_ids", [])])
                )
            )
        )
        class_names = {
            item.id: item.name
            for item in session.scalars(
                select(LabelClass).where(LabelClass.project_id == video.project_id)
            )
        }
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.heartbeat_at = job.started_at
        job.error_message = None
        job.result_json = {"stage": "preparing"}
        session.commit()
        source_path = resolve_managed_project_path(settings, video.managed_path)
        export_kind = str(request["export_kind"])
        relative_root = f"{project.storage_root}/video-exports/{job.id}"
        output_root = resolve_managed_project_path(settings, relative_root)

    temporary_root = output_root.with_name(f".{output_root.name}.{uuid4().hex[:8]}.tmp")
    try:
        import cv2
    except Exception as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = f"Video rendering requires OpenCV: {exc}"
                job.completed_at = datetime.now(UTC)
                session.commit()
        return False

    capture = None
    writer = None
    try:
        if not source_path.is_file():
            raise ValidationError("The managed source video is missing")
        temporary_root.mkdir(parents=True, exist_ok=False)
        output_path = temporary_root / f"{export_kind}.mp4"
        capture = cv2.VideoCapture(str(source_path))
        if not capture.isOpened():
            raise ValidationError("The managed source video could not be opened")
        source_fps = float(capture.get(cv2.CAP_PROP_FPS)) or video.fps
        output_fps = float(request.get("output_fps") or source_fps)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or video.width_px
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or video.height_px
        maximum_frames = min(
            video.frame_count,
            int(request.get("maximum_frames") or video.frame_count),
        )
        codec = str(request.get("codec", "mp4v"))
        writer = cv2.VideoWriter(
            str(output_path),
            cv2.VideoWriter_fourcc(*codec),  # type: ignore[attr-defined]
            output_fps,
            (width, height),
        )
        if not writer.isOpened() and codec != "mp4v":
            writer.release()
            writer = cv2.VideoWriter(
                str(output_path),
                cv2.VideoWriter_fourcc(*"mp4v"),  # type: ignore[attr-defined]
                output_fps,
                (width, height),
            )
            codec = "mp4v"
        if not writer.isOpened():
            raise ValidationError("No supported video writer could create the export")

        interpolators = [TrackInterpolator(track) for track in tracks]
        heatmap = (
            _build_heatmap(
                interpolators,
                width=width,
                height=height,
                maximum_frames=maximum_frames,
                radius=int(request.get("heatmap_radius_px", 40)),
            )
            if export_kind == "heatmap"
            else None
        )
        histories: dict[str, deque[tuple[int, int]]] = {
            item.track.id: deque(maxlen=int(request.get("trail_length_frames", 150)))
            for item in interpolators
        }
        include_labels = bool(request.get("include_labels", True))
        include_confidence = bool(request.get("include_confidence", True))
        thickness = int(request.get("line_thickness", 2))
        opacity = float(request.get("heatmap_opacity", 0.45))
        frame_index = 0
        rendered_frames = 0
        while frame_index < maximum_frames:
            ok, frame = capture.read()
            if not ok:
                break
            with factory() as session:
                current_job = session.get(Job, job_id)
                if current_job is None:
                    return False
                if current_job.status == "cancel_requested":
                    current_job.status = "cancelled"
                    current_job.completed_at = datetime.now(UTC)
                    current_job.result_json = {"stage": "cancelled"}
                    session.commit()
                    shutil.rmtree(temporary_root, ignore_errors=True)
                    return True

            if heatmap is not None:
                frame = cv2.addWeighted(frame, 1.0 - opacity, heatmap, opacity, 0.0)
            for interpolator in interpolators:
                state = interpolator.state(frame_index)
                if state is None:
                    continue
                track = interpolator.track
                color = _color(track.id)
                x_min, y_min, x_max, y_max = _clip_box(state, width, height)
                center = (round((x_min + x_max) / 2), round((y_min + y_max) / 2))
                histories[track.id].append(center)
                if export_kind == "annotated":
                    cv2.rectangle(frame, (x_min, y_min), (x_max, y_max), color, thickness)
                elif export_kind == "trajectory":
                    points = list(histories[track.id])
                    if len(points) >= 2:
                        cv2.polylines(
                            frame,
                            [np.asarray(points, dtype=np.int32)],
                            False,
                            color,
                            thickness,
                            cv2.LINE_AA,
                        )
                    cv2.circle(frame, center, max(2, thickness + 1), color, -1, cv2.LINE_AA)
                elif export_kind == "heatmap":
                    cv2.circle(frame, center, max(2, thickness), color, -1, cv2.LINE_AA)
                if include_labels:
                    label = _label_for_track(track, class_names)
                    if include_confidence and state.confidence is not None:
                        label = f"{label} {state.confidence:.2f}"
                    text_y = max(14, y_min - 5)
                    cv2.putText(
                        frame,
                        label,
                        (x_min, text_y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        color,
                        max(1, thickness),
                        cv2.LINE_AA,
                    )
            writer.write(frame)
            frame_index += 1
            rendered_frames += 1
            if rendered_frames == 1 or rendered_frames % 15 == 0:
                with factory() as session:
                    current_job = session.get(Job, job_id)
                    if current_job is not None:
                        current_job.progress_current = rendered_frames
                        current_job.progress_total = maximum_frames
                        current_job.heartbeat_at = datetime.now(UTC)
                        current_job.checkpoint_json = {
                            "last_rendered_frame": frame_index - 1,
                            "rendered_frames": rendered_frames,
                        }
                        current_job.result_json = {
                            "stage": "rendering",
                            "export_kind": export_kind,
                            "rendered_frames": rendered_frames,
                        }
                        session.commit()

        capture.release()
        capture = None
        writer.release()
        writer = None
        if rendered_frames == 0 or not output_path.is_file():
            raise ValidationError("The video renderer produced no output frames")
        manifest = {
            "format": "reefvision-rendered-video",
            "format_version": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
            "job_id": job_id,
            "video_id": video.id,
            "video_sha256": video.sha256,
            "export_kind": export_kind,
            "track_ids": [track.id for track in tracks],
            "rendered_frames": rendered_frames,
            "source_fps": source_fps,
            "output_fps": output_fps,
            "width_px": width,
            "height_px": height,
            "codec": codec,
            "parameters": request,
        }
        manifest_path = temporary_root / "manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest))
        output_root.parent.mkdir(parents=True, exist_ok=True)
        if output_root.exists():
            shutil.rmtree(output_root)
        temporary_root.replace(output_root)
        final_video = output_root / f"{export_kind}.mp4"
        video_relative = f"{relative_root}/{export_kind}.mp4"
        manifest_relative = f"{relative_root}/manifest.json"
        checksum = _sha256(final_video)
        with factory() as session:
            artifact = ArtifactRecord(
                project_id=video.project_id,
                artifact_type=f"video_{export_kind}",
                created_by="video_render_export",
                reefvision_version=__version__,
                source_kind="video",
                source_id=video.id,
                source_checksum=video.sha256,
                parameters_json=request,
                postprocessing_json={
                    "codec": codec,
                    "output_fps": output_fps,
                    "rendered_frames": rendered_frames,
                },
                review_status="unreviewed",
                managed_path=video_relative,
                checksum=checksum,
                size_bytes=final_video.stat().st_size,
                metadata_json={
                    "manifest_path": manifest_relative,
                    "track_count": len(tracks),
                    "width_px": width,
                    "height_px": height,
                },
            )
            session.add(artifact)
            session.flush()
            current_job = session.get(Job, job_id)
            if current_job is None:
                raise ValidationError("Video export job disappeared before finalization")
            current_job.status = "succeeded"
            current_job.progress_current = rendered_frames
            current_job.progress_total = rendered_frames
            current_job.completed_at = datetime.now(UTC)
            current_job.heartbeat_at = current_job.completed_at
            current_job.result_json = {
                "stage": "completed",
                "artifact_id": artifact.id,
                "video_path": video_relative,
                "video_sha256": checksum,
                "video_size_bytes": final_video.stat().st_size,
                "manifest_path": manifest_relative,
                "rendered_frames": rendered_frames,
                "export_kind": export_kind,
            }
            session.commit()
        return True
    except Exception as exc:
        if capture is not None:
            capture.release()
        if writer is not None:
            writer.release()
        shutil.rmtree(temporary_root, ignore_errors=True)
        with factory() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
                job.heartbeat_at = job.completed_at
                job.result_json = {"stage": "failed", "error": str(exc)}
                session.commit()
        return False

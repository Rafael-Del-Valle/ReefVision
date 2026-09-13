"""Background annotated-video export from persisted tracking observations."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, LabelClass, Project, VideoAsset, VideoTrack
from reefvision.services.video_annotated_export import (
    AnnotatedVideoExportCancelled,
    AnnotatedVideoPreset,
    RenderObservation,
    render_annotated_video,
    resolve_overlay_options,
)
from reefvision.storage.projects import resolve_managed_project_path

PROGRESS_WRITE_INTERVAL_SECONDS = 0.5
CANCELLATION_CHECK_INTERVAL_SECONDS = 0.25


def _safe_stem(filename: str) -> str:
    stem = Path(filename).stem.strip() or "video"
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    return cleaned or "video"


def _fail(factory: sessionmaker[Session], job_id: str, message: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = message
        job.completed_at = datetime.now(UTC)
        job.result_json = {**dict(job.result_json or {}), "stage": "failed"}
        session.commit()


def _cancel(factory: sessionmaker[Session], job_id: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "cancelled"
        job.error_message = None
        job.completed_at = datetime.now(UTC)
        job.result_json = {**dict(job.result_json or {}), "stage": "cancelled"}
        session.commit()


def _render_observations(
    tracks: list[VideoTrack],
    labels: dict[str, LabelClass],
) -> list[RenderObservation]:
    observations: list[RenderObservation] = []
    for track in tracks:
        label = labels.get(track.label_class_id)
        label_name = label.name if label is not None else track.label_class_id
        display_color = label.display_color if label is not None else "#00aaff"
        for raw in list(track.keyframes_json or []):
            frame = raw.get("frame")
            bbox = raw.get("bbox")
            confidence = raw.get("confidence")
            if not isinstance(frame, int):
                continue
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            try:
                parsed_bbox = cast(
                    tuple[float, float, float, float],
                    tuple(float(value) for value in bbox),
                )
            except (TypeError, ValueError):
                continue
            parsed_confidence = (
                float(confidence)
                if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
                else None
            )
            observations.append(
                RenderObservation(
                    frame=frame,
                    track_key=track.id,
                    track_number=track.track_number,
                    label=label_name,
                    confidence=parsed_confidence,
                    bbox=parsed_bbox,
                    display_color=display_color,
                )
            )
    return observations


def process_video_annotated_export_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "video_annotated_export" or job.status != "queued":
            return False

        request = dict(job.request_json or {})
        video_id = str(request.get("video_id") or "")
        source_tracking_job_id = str(request.get("source_tracking_job_id") or "")
        video = session.get(VideoAsset, video_id)
        source_tracking_job = session.get(Job, source_tracking_job_id)

        if video is None:
            job.status = "failed"
            job.error_message = "Video not found for annotated export"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        if (
            source_tracking_job is None
            or source_tracking_job.job_type != "video_tracking"
            or source_tracking_job.status != "succeeded"
            or str((source_tracking_job.request_json or {}).get("video_id") or "") != video.id
        ):
            job.status = "failed"
            job.error_message = (
                "Annotated export requires a succeeded tracking run for the selected video"
            )
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False

        project = session.get(Project, video.project_id)
        if project is None:
            job.status = "failed"
            job.error_message = "Video project not found"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False

        tracks = list(
            session.scalars(
                select(VideoTrack)
                .where(
                    VideoTrack.video_id == video.id,
                    VideoTrack.source_job_id == source_tracking_job_id,
                    VideoTrack.deleted_at.is_(None),
                )
                .order_by(VideoTrack.track_number, VideoTrack.id)
            )
        )
        label_ids = {track.label_class_id for track in tracks}
        labels = (
            {
                label.id: label
                for label in session.scalars(select(LabelClass).where(LabelClass.id.in_(label_ids)))
            }
            if label_ids
            else {}
        )

        preset_value = str(request.get("preset") or "clean_tracking")
        if preset_value not in {"clean_tracking", "full_review"}:
            job.status = "failed"
            job.error_message = f"Unsupported annotated-video preset: {preset_value}"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        preset = cast(AnnotatedVideoPreset, preset_value)

        overlays_raw = request.get("overlays")
        overlays = dict(overlays_raw) if isinstance(overlays_raw, dict) else {}
        options = resolve_overlay_options(preset, overlays)
        trail_length = max(2, min(1000, int(request.get("trail_length", 60))))

        output_relative = (
            f"{project.storage_root}/videos/annotated/{video.id}/{job.id}-{preset}.mp4"
        )
        filename = f"{_safe_stem(video.original_filename)}-{preset.replace('_', '-')}.mp4"

        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.progress_current = 0
        job.progress_total = video.frame_count
        job.error_message = None
        job.result_json = {
            "stage": "rendering",
            "video_id": video.id,
            "source_tracking_job_id": source_tracking_job_id,
            "preset": preset,
            "overlays": options.as_dict(),
            "trail_length": trail_length,
            "frames_rendered": 0,
        }
        session.commit()

        source_path = resolve_managed_project_path(settings, video.managed_path)
        output_path = resolve_managed_project_path(settings, output_relative)
        width_px = video.width_px
        height_px = video.height_px
        fps = video.fps
        frame_count = video.frame_count

    observations = _render_observations(tracks, labels)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{job_id}.part{output_path.suffix}")
    temporary_path.unlink(missing_ok=True)

    last_progress_write = 0.0
    last_cancel_check = 0.0
    cancel_cached = False

    def should_cancel() -> bool:
        nonlocal last_cancel_check, cancel_cached
        now = monotonic()
        if now - last_cancel_check < CANCELLATION_CHECK_INTERVAL_SECONDS:
            return cancel_cached
        last_cancel_check = now
        with factory() as session:
            current = session.get(Job, job_id)
            cancel_cached = current is None or current.status == "cancel_requested"
        return cancel_cached

    def on_progress(frames_rendered: int) -> None:
        nonlocal last_progress_write
        now = monotonic()
        if (
            frames_rendered < frame_count
            and now - last_progress_write < PROGRESS_WRITE_INTERVAL_SECONDS
        ):
            return
        last_progress_write = now
        with factory() as session:
            current = session.get(Job, job_id)
            if current is None:
                return
            current.progress_current = min(frames_rendered, frame_count)
            current.result_json = {
                **dict(current.result_json or {}),
                "stage": "rendering",
                "frames_rendered": min(frames_rendered, frame_count),
                "heartbeat_at": datetime.now(UTC).isoformat(),
            }
            session.commit()

    try:
        frames_rendered = render_annotated_video(
            source_path,
            temporary_path,
            width_px=width_px,
            height_px=height_px,
            fps=fps,
            frame_count=frame_count,
            observations=observations,
            options=options,
            trail_length=trail_length,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        os.replace(temporary_path, output_path)

        with factory() as session:
            current = session.get(Job, job_id)
            if current is None:
                output_path.unlink(missing_ok=True)
                raise RuntimeError("Annotated-video export job disappeared")
            if current.status == "cancel_requested":
                output_path.unlink(missing_ok=True)
                _cancel(factory, job_id)
                return True

            current.status = "succeeded"
            current.progress_current = frame_count
            current.error_message = None
            current.completed_at = datetime.now(UTC)
            current.result_json = {
                **dict(current.result_json or {}),
                "stage": "completed",
                "frames_rendered": frames_rendered,
                "output_path": output_relative,
                "filename": filename,
                "file_size_bytes": output_path.stat().st_size,
                "codec": "mp4v",
                "audio_preserved": False,
                "track_count": len(tracks),
                "observation_count": len(observations),
                "heartbeat_at": datetime.now(UTC).isoformat(),
            }
            session.commit()
        return True
    except AnnotatedVideoExportCancelled:
        temporary_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        _cancel(factory, job_id)
        return True
    except Exception as exc:
        temporary_path.unlink(missing_ok=True)
        _fail(factory, job_id, str(exc))
        return False

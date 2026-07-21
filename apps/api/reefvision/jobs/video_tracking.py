"""Transactional detector-to-tracker execution for managed videos."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    ModelRegistration,
    Project,
    VideoAsset,
    VideoTrack,
    VideoTrackEvent,
)
from reefvision.ml.video_tracking import build_video_tracking_adapter
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.videos import tracker_config_workspace


def _mapped_label_class_id(class_map_json: dict[str, Any], label: str) -> str | None:
    mapping = class_map_json.get("mapping", {})
    if not isinstance(mapping, dict):
        return None
    value = mapping.get(label)
    return str(value) if value else None


def _fail_job(
    factory: sessionmaker[Session],
    job_id: str,
    message: str,
    *,
    provenance: dict[str, Any] | None = None,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.status == "cancelled":
            return
        job.status = "failed"
        job.error_message = message
        job.completed_at = datetime.now(UTC)
        job.heartbeat_at = job.completed_at
        job.result_json = {
            "stage": "failed",
            "error": message,
            **(provenance or {}),
        }
        session.commit()


def _cancel_requested(factory: sessionmaker[Session], job_id: str) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return True
        if job.status != "cancel_requested":
            return False
        job.status = "cancelled"
        job.completed_at = datetime.now(UTC)
        job.heartbeat_at = job.completed_at
        job.result_json = {"stage": "cancelled"}
        session.commit()
        return True


def _normalized_detection(
    detection: Any,
    *,
    width: int,
    height: int,
) -> dict[str, Any] | None:
    confidence = float(detection.confidence)
    coordinates = (
        float(detection.x_min),
        float(detection.y_min),
        float(detection.x_max),
        float(detection.y_max),
    )
    if (
        not all(math.isfinite(value) for value in coordinates)
        or not math.isfinite(confidence)
        or not 0.0 <= confidence <= 1.0
        or int(detection.tracker_id) < 0
    ):
        return None
    x_min = min(float(width), max(0.0, coordinates[0]))
    y_min = min(float(height), max(0.0, coordinates[1]))
    x_max = min(float(width), max(0.0, coordinates[2]))
    y_max = min(float(height), max(0.0, coordinates[3]))
    if x_max <= x_min or y_max <= y_min:
        return None
    return {
        "id": str(uuid4()),
        "x_min": x_min,
        "y_min": y_min,
        "x_max": x_max,
        "y_max": y_max,
        "centroid_x": (x_min + x_max) / 2.0,
        "centroid_y": (y_min + y_max) / 2.0,
        "confidence": confidence,
        "source": "generated",
        "manual_edit": False,
        "automated_provenance": None,
        "deleted_at": None,
        "revision": 1,
    }


def process_video_tracking_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    provenance: dict[str, Any] = {}
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "video_track" or job.status != "queued":
            return False
        request = dict(job.request_json or {})
        video = session.get(VideoAsset, str(request.get("video_id", "")))
        model = session.get(ModelRegistration, str(request.get("model_id", "")))
        project = session.get(Project, video.project_id) if video is not None else None
        if video is None or model is None or project is None:
            job.status = "failed"
            job.error_message = "Video tracking references missing data"
            job.completed_at = datetime.now(UTC)
            job.result_json = {"stage": "failed", "error": job.error_message}
            session.commit()
            return False
        if (
            model.project_id != video.project_id
            or model.purpose != "detector"
            or model.task != "detect"
            or model.provider_name != "ultralytics"
            or model.framework != "ultralytics"
        ):
            job.status = "failed"
            job.error_message = (
                "Video tracking requires a compatible detector from the same project"
            )
            job.completed_at = datetime.now(UTC)
            job.result_json = {"stage": "failed", "error": job.error_message}
            session.commit()
            return False
        if request.get("source_video_sha256") not in {None, video.sha256}:
            job.status = "failed"
            job.error_message = "The source video changed after the tracking request was queued"
            job.completed_at = datetime.now(UTC)
            job.result_json = {"stage": "failed", "error": job.error_message}
            session.commit()
            return False
        if request.get("model_sha256") not in {None, model.sha256}:
            job.status = "failed"
            job.error_message = "The detector changed after the tracking request was queued"
            job.completed_at = datetime.now(UTC)
            job.result_json = {"stage": "failed", "error": job.error_message}
            session.commit()
            return False
        existing = list(
            session.scalars(select(VideoTrack).where(VideoTrack.origin_job_id == job.id))
        )
        if existing:
            job.status = "succeeded"
            job.progress_current = job.progress_total
            job.completed_at = datetime.now(UTC)
            job.result_json = {
                "stage": "completed",
                "track_ids": [track.id for track in existing],
                "track_count": len(existing),
                "replayed": True,
            }
            session.commit()
            return True
        tracker_kind = str(request.get("tracker", "bytetrack"))
        if tracker_kind not in {"bytetrack", "botsort"}:
            job.status = "failed"
            job.error_message = "Supported video trackers are ByteTrack and BoT-SORT"
            job.completed_at = datetime.now(UTC)
            job.result_json = {"stage": "failed", "error": job.error_message}
            session.commit()
            return False
        requested_device = str(request.get("requested_device", request.get("device", "auto")))
        resource_device = str((job.resource_assignment_json or {}).get("device", ""))
        execution_device = (
            resource_device
            if requested_device == "cuda" and resource_device.startswith("cuda")
            else requested_device
        )
        every_n_frames = max(1, int(request.get("every_n_frames", 1)))
        replace_generated = bool(request.get("replace_generated_tracks", True))
        confidence = float(request.get("confidence_threshold", 0.25))
        iou = float(request.get("iou_threshold", 0.45))
        tracker_options = dict(request.get("tracker_options") or {})
        provenance = {
            "video_id": video.id,
            "source_video_sha256": video.sha256,
            "model_id": model.id,
            "model_sha256": model.sha256,
            "provider_name": model.provider_name,
            "provider_version": model.provider_version,
            "tracker": tracker_kind,
            "tracker_options": tracker_options,
            "confidence_threshold": confidence,
            "iou_threshold": iou,
            "every_n_frames": every_n_frames,
            "requested_device": requested_device,
            "idempotency_key": request.get("idempotency_key"),
        }
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.heartbeat_at = job.started_at
        job.error_message = None
        job.result_json = {"stage": "loading", **provenance}
        session.commit()
        video_path = resolve_managed_project_path(settings, video.managed_path)
        model_path = resolve_managed_project_path(settings, model.managed_path)
        video_id = video.id
        video_width = video.width_px
        video_height = video.height_px
        video_frame_count = video.frame_count
        video_fps = video.fps
        project_storage_root = project.storage_root
        class_map = dict(model.class_map_json or {})

    adapter = None
    try:
        adapter = build_video_tracking_adapter(
            str(provenance["provider_name"]),
            str(provenance["provider_version"]),
        )
        if not video_path.is_file():
            raise FileNotFoundError("The managed source video is missing")
        if not model_path.is_file():
            raise FileNotFoundError("The managed detector checkpoint is missing")
        keyframes_by_tracker: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
        label_counts_by_tracker: dict[int, Counter[str]] = defaultdict(Counter)
        processed_frames = 0
        skipped_detections = 0
        with tracker_config_workspace(
            settings,
            project_storage_root=project_storage_root,
            job_id=job_id,
            tracker=tracker_kind,
            options=tracker_options,
        ) as tracker_config_path:
            frames, resolved_device = adapter.track(
                model_path=model_path,
                video_path=video_path,
                tracker_config_path=tracker_config_path,
                confidence_threshold=confidence,
                iou_threshold=iou,
                requested_device=execution_device,
                every_n_frames=every_n_frames,
            )
            provenance["resolved_device"] = resolved_device
            for frame in frames:
                if _cancel_requested(factory, job_id):
                    return True
                processed_frames += 1
                for detection in frame.detections:
                    normalized = _normalized_detection(
                        detection,
                        width=video_width,
                        height=video_height,
                    )
                    if normalized is None or frame.frame_index < 0:
                        skipped_detections += 1
                        continue
                    if frame.frame_index >= video_frame_count:
                        skipped_detections += 1
                        continue
                    normalized["frame_index"] = frame.frame_index
                    normalized["timestamp_seconds"] = frame.frame_index / video_fps
                    previous = keyframes_by_tracker[detection.tracker_id].get(frame.frame_index)
                    if previous is None or float(normalized["confidence"]) > float(
                        previous["confidence"]
                    ):
                        keyframes_by_tracker[detection.tracker_id][frame.frame_index] = normalized
                    label_counts_by_tracker[detection.tracker_id][detection.label] += 1
                with factory() as session:
                    current_job = session.get(Job, job_id)
                    if current_job is None:
                        return False
                    current_job.progress_current = min(
                        processed_frames,
                        max(current_job.progress_total, processed_frames),
                    )
                    current_job.heartbeat_at = datetime.now(UTC)
                    current_job.result_json = {
                        "stage": "tracking",
                        "processed_frames": processed_frames,
                        "active_track_count": len(keyframes_by_tracker),
                        "skipped_detection_count": skipped_detections,
                        **provenance,
                    }
                    session.commit()

        if _cancel_requested(factory, job_id):
            return True
        with factory() as session:
            job = session.get(Job, job_id)
            video = session.get(VideoAsset, video_id)
            model = session.get(ModelRegistration, str(provenance["model_id"]))
            if job is None or video is None or model is None:
                raise RuntimeError("Video tracking job disappeared before finalization")
            existing = list(
                session.scalars(select(VideoTrack).where(VideoTrack.origin_job_id == job.id))
            )
            if existing:
                job.status = "succeeded"
                job.progress_current = job.progress_total
                job.completed_at = datetime.now(UTC)
                job.result_json = {
                    "stage": "completed",
                    "track_ids": [track.id for track in existing],
                    "track_count": len(existing),
                    "replayed": True,
                    **provenance,
                }
                session.commit()
                return True
            if replace_generated:
                superseded = list(
                    session.scalars(
                        select(VideoTrack).where(
                            VideoTrack.video_id == video_id,
                            VideoTrack.source_type == "generated",
                            VideoTrack.deleted_at.is_(None),
                        )
                    )
                )
                now = datetime.now(UTC)
                for track in superseded:
                    before = {
                        "status": track.status,
                        "deleted_at": None,
                        "revision": track.revision,
                    }
                    track.status = "archived"
                    track.deleted_at = now
                    track.is_ground_truth = False
                    track.updated_by = "video_tracking_worker"
                    track.revision += 1
                    session.add(
                        VideoTrackEvent(
                            video_track_id=track.id,
                            video_id=track.video_id,
                            event_type="tracking_run_superseded",
                            before_json=before,
                            after_json={
                                "status": track.status,
                                "deleted_at": now.isoformat(),
                                "revision": track.revision,
                            },
                            result_json={
                                "track_ids": [track.id],
                                "deleted_track_ids": [track.id],
                                "warnings": [],
                            },
                            actor="video_tracking_worker",
                        )
                    )
            maximum_track_number = session.scalar(
                select(func.max(VideoTrack.track_number)).where(VideoTrack.video_id == video_id)
            )
            next_track_number = int(maximum_track_number or 0) + 1
            created_tracks: list[VideoTrack] = []
            unresolved_class_count = 0
            for raw_tracker_id, frames_by_index in sorted(keyframes_by_tracker.items()):
                if not frames_by_index:
                    continue
                predicted_label = label_counts_by_tracker[raw_tracker_id].most_common(1)[0][0]
                label_class_id = _mapped_label_class_id(class_map, predicted_label)
                if label_class_id is None:
                    unresolved_class_count += 1
                track = VideoTrack(
                    video_id=video_id,
                    label_class_id=label_class_id,
                    origin_job_id=job.id,
                    track_number=next_track_number,
                    name=f"{tracker_kind} {raw_tracker_id}",
                    geometry_kind="bounding_box",
                    keyframes_json=[frames_by_index[index] for index in sorted(frames_by_index)],
                    interpolation="linear",
                    status="generated",
                    source_type="generated",
                    is_ground_truth=False,
                    metadata_json={
                        **provenance,
                        "raw_tracker_id": raw_tracker_id,
                        "predicted_label": predicted_label,
                        "predicted_labels": dict(label_counts_by_tracker[raw_tracker_id]),
                        "automated_provenance_preserved": True,
                    },
                    created_by="video_tracking_worker",
                    updated_by="video_tracking_worker",
                )
                next_track_number += 1
                session.add(track)
                session.flush()
                session.add(
                    VideoTrackEvent(
                        video_track_id=track.id,
                        video_id=track.video_id,
                        operation_id=f"{job.id}:{track.id}",
                        event_type="tracking_generated",
                        before_json=None,
                        after_json={
                            "track_id": track.id,
                            "revision": track.revision,
                            "observation_count": len(track.keyframes_json),
                            "provenance": dict(track.metadata_json),
                        },
                        result_json={
                            "track_ids": [track.id],
                            "deleted_track_ids": [],
                            "warnings": [],
                        },
                        actor="video_tracking_worker",
                    )
                )
                created_tracks.append(track)
            job.status = "succeeded"
            job.progress_current = processed_frames
            job.progress_total = max(processed_frames, job.progress_total)
            job.completed_at = datetime.now(UTC)
            job.heartbeat_at = job.completed_at
            job.result_json = {
                "stage": "completed",
                "processed_frames": processed_frames,
                "track_count": len(created_tracks),
                "track_ids": [track.id for track in created_tracks],
                "unresolved_class_count": unresolved_class_count,
                "skipped_detection_count": skipped_detections,
                **provenance,
            }
            session.commit()
        return True
    except Exception as exc:
        _fail_job(factory, job_id, str(exc), provenance=provenance)
        return False
    finally:
        if adapter is not None:
            adapter.unload()

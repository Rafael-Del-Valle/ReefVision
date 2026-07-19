"""Background detector-to-tracker execution for managed videos."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, VideoAsset, VideoTrack
from reefvision.ml.providers import resolve_torch_device
from reefvision.storage.projects import resolve_managed_project_path

TRACKER_CONFIGS = {
    "bytetrack": "bytetrack.yaml",
    "botsort": "botsort.yaml",
}


def _mapped_label_class_id(
    class_map_json: dict[str, Any],
    label: str,
) -> str | None:
    mapping = class_map_json.get("mapping", {})
    if not isinstance(mapping, dict):
        return None
    value = mapping.get(label)
    return str(value) if value else None


def process_video_tracking_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "video_track" or job.status != "queued":
            return False
        request = dict(job.request_json)
        video = session.get(VideoAsset, str(request.get("video_id", "")))
        model = session.get(ModelRegistration, str(request.get("model_id", "")))
        if video is None or model is None:
            job.status = "failed"
            job.error_message = "Video tracking references missing data"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        if (
            model.project_id != video.project_id
            or model.purpose != "detector"
            or model.task != "detect"
        ):
            job.status = "failed"
            job.error_message = "Video tracking requires a detector from the same project"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        tracker_kind = str(request.get("tracker", "bytetrack"))
        tracker_config = TRACKER_CONFIGS.get(tracker_kind)
        if tracker_config is None:
            job.status = "failed"
            job.error_message = "Supported video trackers are ByteTrack and BoT-SORT"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.error_message = None
        session.commit()
        video_path = resolve_managed_project_path(settings, video.managed_path)
        model_path = resolve_managed_project_path(settings, model.managed_path)
        video_id = video.id
        video_checksum = video.sha256
        model_id = model.id
        model_checksum = model.sha256
        provider_version = model.provider_version
        class_map = dict(model.class_map_json or {})
        every_n_frames = int(request.get("every_n_frames", 1))
        replace_generated = bool(request.get("replace_generated_tracks", True))
        confidence = float(request.get("confidence_threshold", 0.25))
        iou = float(request.get("iou_threshold", 0.45))
        device = str(request.get("device", "auto"))

    try:
        if not video_path.is_file() or not model_path.is_file():
            raise FileNotFoundError("Managed video or detector checkpoint is missing")
        from ultralytics import YOLO

        detector = YOLO(str(model_path))
        if str(getattr(detector, "task", "") or "") != "detect":
            raise RuntimeError("The registered video model is not a detector")
        results = detector.track(
            source=str(video_path),
            stream=True,
            persist=True,
            tracker=tracker_config,
            conf=confidence,
            iou=iou,
            device=resolve_torch_device(device),
            vid_stride=every_n_frames,
            verbose=False,
        )
        keyframes_by_track: dict[int, list[dict[str, Any]]] = defaultdict(list)
        labels_by_track: dict[int, str | None] = {}
        predicted_labels: dict[int, str] = {}
        processed_frames = 0

        for result_index, result in enumerate(results):
            frame_index = result_index * every_n_frames
            boxes = getattr(result, "boxes", None)
            processed_frames += 1
            if boxes is not None and boxes.id is not None:
                xyxy = boxes.xyxy.tolist()
                track_ids = boxes.id.int().tolist()
                confidences = boxes.conf.tolist()
                classes = boxes.cls.int().tolist()
                names = (
                    getattr(result, "names", None)
                    or getattr(detector, "names", None)
                    or {}
                )
                for index, raw_track_id in enumerate(track_ids):
                    track_number = int(raw_track_id)
                    if track_number < 1:
                        track_number += 1
                    class_index = int(classes[index])
                    label = (
                        str(names.get(class_index, class_index))
                        if isinstance(names, dict)
                        else str(names[class_index])
                        if class_index < len(names)
                        else str(class_index)
                    )
                    coords = xyxy[index]
                    keyframes_by_track[track_number].append(
                        {
                            "frame_index": frame_index,
                            "x_min": float(coords[0]),
                            "y_min": float(coords[1]),
                            "x_max": float(coords[2]),
                            "y_max": float(coords[3]),
                            "confidence": float(confidences[index]),
                            "source": tracker_kind,
                        }
                    )
                    labels_by_track[track_number] = _mapped_label_class_id(
                        class_map,
                        label,
                    )
                    predicted_labels[track_number] = label
            with factory() as session:
                job = session.get(Job, job_id)
                if job is None:
                    return False
                if job.status == "cancel_requested":
                    job.status = "cancelled"
                    job.completed_at = datetime.now(UTC)
                    session.commit()
                    return True
                job.progress_current = processed_frames
                job.result_json = {
                    "stage": "tracking",
                    "processed_frames": processed_frames,
                    "active_track_count": len(keyframes_by_track),
                    "tracker": tracker_kind,
                }
                session.commit()

        with factory() as session:
            if replace_generated:
                session.execute(
                    delete(VideoTrack).where(
                        VideoTrack.video_id == video_id,
                        VideoTrack.status == "generated",
                    )
                )
            for track_number, keyframes in sorted(keyframes_by_track.items()):
                if not keyframes:
                    continue
                session.add(
                    VideoTrack(
                        video_id=video_id,
                        label_class_id=labels_by_track.get(track_number),
                        track_number=track_number,
                        geometry_kind="bounding_box",
                        keyframes_json=keyframes,
                        interpolation="linear",
                        status="generated",
                        metadata_json={
                            "tracker": tracker_kind,
                            "tracker_config": tracker_config,
                            "model_id": model_id,
                            "model_checksum": model_checksum,
                            "provider_name": "ultralytics",
                            "provider_version": provider_version,
                            "predicted_label": predicted_labels.get(track_number),
                            "confidence_threshold": confidence,
                            "iou_threshold": iou,
                            "every_n_frames": every_n_frames,
                            "device": device,
                            "source_video_sha256": video_checksum,
                        },
                    )
                )
            job = session.get(Job, job_id)
            if job is None:
                raise RuntimeError("Video tracking job disappeared")
            job.status = "succeeded"
            job.progress_current = max(processed_frames, job.progress_total)
            job.result_json = {
                "stage": "completed",
                "tracker": tracker_kind,
                "processed_frames": processed_frames,
                "track_count": len(keyframes_by_track),
                "unresolved_class_count": sum(
                    1 for value in labels_by_track.values() if value is None
                ),
            }
            job.completed_at = datetime.now(UTC)
            session.commit()
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

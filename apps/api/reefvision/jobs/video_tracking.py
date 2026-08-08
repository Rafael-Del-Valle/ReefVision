"""Background detector-plus-tracker video inference."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, VideoAsset, VideoTrack
from reefvision.ml.video_tracking import TrackObservation, video_tracking_provider_for_name
from reefvision.storage.projects import resolve_managed_project_path


def _fail(factory: sessionmaker[Session], job_id: str, message: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_message = message
        job.completed_at = datetime.now(UTC)
        session.commit()


def _project_class_mapping(model: ModelRegistration) -> dict[str, str]:
    payload = dict(model.class_map_json or {})
    mapping = payload.get("mapping", {})
    if isinstance(mapping, dict):
        return {
            str(label).strip().casefold(): str(class_id)
            for label, class_id in mapping.items()
            if class_id
        }
    provider_classes = payload.get("provider_classes", {})
    if isinstance(provider_classes, dict):
        result: dict[str, str] = {}
        for label, metadata in provider_classes.items():
            if isinstance(metadata, dict) and metadata.get("label_class_id"):
                result[str(label).strip().casefold()] = str(metadata["label_class_id"])
        return result
    return {}


def _keyframes(observations: list[TrackObservation]) -> list[dict[str, object]]:
    return [
        {
            "frame": item.frame,
            "bbox": list(item.bbox),
            "confidence": item.confidence,
        }
        for item in observations
    ]


def process_video_tracking_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "video_tracking" or job.status != "queued":
            return False
        request = dict(job.request_json)
        video = session.get(VideoAsset, str(request.get("video_id", "")))
        model = session.get(ModelRegistration, str(request.get("model_id", "")))
        if video is None or model is None or video.project_id != model.project_id:
            job.status = "failed"
            job.error_message = "Video or detector model was not found in the selected project"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        if model.purpose not in {"detector", "segmenter"} or model.task not in {
            "detect",
            "segment",
        }:
            job.status = "failed"
            job.error_message = "Video tracking requires a registered detection or instance model"
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False
        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.progress_total = video.frame_count
        job.progress_current = 0
        job.error_message = None
        video.status = "tracking"
        session.commit()
        video_path = video.managed_path
        model_path = model.managed_path
        provider_name = model.provider_name
        class_mapping = _project_class_mapping(model)
        project_id = video.project_id
        video_id = video.id
        model_id = model.id

    try:
        provider = video_tracking_provider_for_name(provider_name)
        observations = provider.track(
            resolve_managed_project_path(settings, model_path),
            resolve_managed_project_path(settings, video_path),
            tracker=str(request.get("tracker", "bytetrack.yaml")),
            confidence=float(request.get("confidence", 0.25)),
            iou=float(request.get("iou", 0.5)),
            device=str(request.get("device", "auto")),
        )
        grouped: dict[tuple[int, str], list[TrackObservation]] = defaultdict(list)
        unmapped_labels: set[str] = set()
        for item in observations:
            label_class_id = class_mapping.get(item.class_name.strip().casefold())
            if label_class_id is None:
                unmapped_labels.add(item.class_name)
                continue
            grouped[(item.provider_track_id, label_class_id)].append(item)
        minimum_frames = max(1, int(request.get("minimum_track_frames", 2)))

        with factory() as session:
            video = session.get(VideoAsset, video_id)
            job = session.get(Job, job_id)
            if video is None or job is None:
                raise RuntimeError("Video tracking records disappeared")
            existing = list(
                session.scalars(
                    select(VideoTrack).where(
                        VideoTrack.video_id == video_id,
                        VideoTrack.source_model_id == model_id,
                        VideoTrack.deleted_at.is_(None),
                    )
                )
            )
            for track in existing:
                track.deleted_at = datetime.now(UTC)
                track.revision += 1
            next_number = (
                int(
                    session.scalar(
                        select(func.max(VideoTrack.track_number)).where(
                            VideoTrack.video_id == video_id
                        )
                    )
                    or 0
                )
                + 1
            )
            created = 0
            observation_count = 0
            for (provider_track_id, label_class_id), items in sorted(grouped.items()):
                ordered = sorted(items, key=lambda item: item.frame)
                if len(ordered) < minimum_frames:
                    continue
                session.add(
                    VideoTrack(
                        video_id=video_id,
                        label_class_id=label_class_id,
                        track_number=next_number,
                        geometry_kind="bbox",
                        keyframes_json=_keyframes(ordered),
                        interpolation="linear",
                        status="machine_generated",
                        source_model_id=model_id,
                        source_job_id=job_id,
                        metadata_json={
                            "provider_track_id": provider_track_id,
                            "provider_name": provider.provider_id,
                            "provider_version": provider.provider_version,
                            "tracker": str(request.get("tracker", "bytetrack.yaml")),
                            "mean_confidence": mean(item.confidence for item in ordered),
                        },
                    )
                )
                next_number += 1
                created += 1
                observation_count += len(ordered)
            video.status = "tracked"
            video.revision += 1
            job.status = "succeeded"
            job.progress_current = video.frame_count
            job.result_json = {
                "track_count": created,
                "observation_count": observation_count,
                "unmapped_labels": sorted(unmapped_labels),
                "provider_version": provider.provider_version,
                "project_id": project_id,
            }
            job.completed_at = datetime.now(UTC)
            session.commit()
        return True
    except Exception as exc:
        with factory() as session:
            video = session.get(VideoAsset, str(request.get("video_id", "")))
            if video is not None:
                video.status = "tracking_failed"
                video.revision += 1
                session.commit()
        _fail(factory, job_id, str(exc))
        return False

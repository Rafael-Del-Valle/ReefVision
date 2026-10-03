"""Background detector-plus-tracker video inference."""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, VideoAsset, VideoTrack
from reefvision.domain.errors import ValidationError
from reefvision.ml.video_tracking import (
    TrackObservation,
    VideoTrackingCancelled,
    VideoTrackingProgress,
    video_tracking_provider_for_name,
)
from reefvision.schemas.georeferenced_observation import BoundingBoxPixels
from reefvision.schemas.pose_tracking import PoseTemporalAssociationBuildRequest
from reefvision.services.georeferenced_observations import GeoReferencedObservationService
from reefvision.services.pose_temporal_tracking import PoseTemporalTrackingService
from reefvision.services.video_georeferencing import VideoGeoreferencingService
from reefvision.services.video_georeferencing_readiness import VideoGeoreferencingReadinessService
from reefvision.storage.projects import resolve_managed_project_path

LOGGER = logging.getLogger("reefvision.video_tracking")
PROGRESS_WRITE_INTERVAL_SECONDS = 0.5
CANCELLATION_CHECK_INTERVAL_SECONDS = 0.25
PROGRESS_LOG_INTERVAL_SECONDS = 10.0


def _fail(factory: sessionmaker[Session], job_id: str, message: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        now = datetime.now(UTC)
        result = dict(job.result_json or {})
        result.update({"stage": "failed", "heartbeat_at": now.isoformat()})
        job.status = "failed"
        job.result_json = result
        job.error_message = message
        job.completed_at = now
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


def _keyframes(
    observations: list[TrackObservation],
    pose_landmark_schema: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    labels_raw = (
        pose_landmark_schema.get("expanded_labels") if pose_landmark_schema is not None else None
    )
    expanded_labels = [str(item) for item in labels_raw] if isinstance(labels_raw, list) else None

    keyframes: list[dict[str, object]] = []
    for item in observations:
        payload: dict[str, object] = {
            "frame": item.frame,
            "bbox": list(item.bbox),
            "confidence": item.confidence,
        }
        if item.pose_uncertainty is not None:
            payload["pose_uncertainty"] = dict(item.pose_uncertainty)
        if item.keypoints is not None:
            payload["keypoints"] = [list(point) for point in item.keypoints]
            if expanded_labels is not None:
                if len(expanded_labels) != len(item.keypoints):
                    raise ValidationError(
                        "Pose prediction landmark count does not match the "
                        "bound ReefVision landmark schema"
                    )
                occurrence_counts: dict[str, int] = {}
                pose_observations: list[dict[str, object]] = []
                for index, point in enumerate(item.keypoints):
                    label = expanded_labels[index]
                    occurrence_index = occurrence_counts.get(label, 0)
                    occurrence_counts[label] = occurrence_index + 1
                    x, y, confidence = (
                        float(point[0]),
                        float(point[1]),
                        float(point[2]),
                    )
                    visible = (
                        math.isfinite(x)
                        and math.isfinite(y)
                        and math.isfinite(confidence)
                        and x >= 0
                        and y >= 0
                        and confidence > 0
                    )
                    pose_observations.append(
                        {
                            "id": (
                                f"provider:{item.provider_track_id}:"
                                f"frame:{item.frame}:landmark:{index}"
                            ),
                            "semantic_label": label,
                            "occurrence_index": occurrence_index,
                            "x": x if visible else 0.0,
                            "y": y if visible else 0.0,
                            "confidence": (
                                min(max(confidence, 0.0), 1.0) if math.isfinite(confidence) else 0.0
                            ),
                            "status": "visible" if visible else "absent",
                            "source": "model",
                        }
                    )
                payload["pose_observations"] = pose_observations
        keyframes.append(payload)
    return keyframes


def _bounding_box_pixels(
    observation: TrackObservation,
) -> BoundingBoxPixels:
    """Convert ReefVision/Ultralytics xywh into Task 10 xyxy pixels."""

    x, y, width, height = observation.bbox

    if width <= 0 or height <= 0:
        raise ValidationError("YOLO detection bounding box requires positive dimensions")

    return BoundingBoxPixels(
        x_min=float(x),
        y_min=float(y),
        x_max=float(x + width),
        y_max=float(y + height),
    )


def _georeference_track_observations(
    service: VideoGeoreferencingService,
    persistence: GeoReferencedObservationService,
    *,
    video_id: str,
    track_id: str,
    observations: list[TrackObservation],
) -> tuple[int, int]:
    """Feed retained YOLO/ByteTrack observations into georeferencing.

    YOLO supplies no explicit scientific representative point here, so
    georeference_detection() intentionally receives only the bbox. The
    Task 9 bbox-center fallback therefore selects the projected pixel.

    Returns:
        (successful_count, failed_count)
    """

    configuration_hash = service.configuration_hash(video_id)

    successful = 0
    failed = 0

    for observation in observations:
        try:
            geo_observation = service.georeference_detection(
                video_id,
                frame_index=observation.frame,
                bbox=_bounding_box_pixels(observation),
                track_id=track_id,
            )
        except ValidationError as exc:
            failed += 1
            LOGGER.debug(
                ("Could not georeference video %s track %s frame %s: %s"),
                video_id,
                track_id,
                observation.frame,
                exc,
            )
        else:
            # Persistence failures are intentionally not swallowed here.
            # A database/provenance mismatch should fail the transaction
            # rather than report a geographic point that was never stored.
            persistence.persist(
                geo_observation,
                configuration_hash=configuration_hash,
            )
            successful += 1

    return successful, failed


def process_video_tracking_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "video_tracking":
            return False

        claim_stage = str((job.result_json or {}).get("stage") or "")
        preclaimed = job.status == "running" and claim_stage == "launching_process"

        if job.status == "cancel_requested" and claim_stage == "launching_process":
            now = datetime.now(UTC)
            result = dict(job.result_json or {})
            result.update(
                {
                    "stage": "cancelled",
                    "heartbeat_at": now.isoformat(),
                }
            )
            job.status = "cancelled"
            job.result_json = result
            job.error_message = None
            job.completed_at = now
            session.commit()
            return True

        if job.status != "queued" and not preclaimed:
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
            "pose",
        }:
            job.status = "failed"
            job.error_message = (
                "Video tracking requires a registered detection, instance, or pose model"
            )
            job.completed_at = datetime.now(UTC)
            session.commit()
            return False

        started_at = datetime.now(UTC)
        job.status = "running"
        job.started_at = started_at
        job.progress_total = video.frame_count
        job.progress_current = 0
        job.error_message = None
        job.result_json = {
            "stage": "starting",
            "heartbeat_at": started_at.isoformat(),
            "frames_processed": 0,
            "detection_count": 0,
            "tracked_observations_seen": 0,
            "tracks_seen": 0,
        }
        video.status = "tracking"
        session.commit()

        video_path = video.managed_path
        model_path = model.managed_path
        provider_name = model.provider_name
        class_mapping = _project_class_mapping(model)
        project_id = video.project_id
        video_id = video.id
        model_id = model.id
        model_task = model.task
        raw_pose_landmark_schema = dict(model.metadata_json or {}).get("pose_landmark_schema")
        pose_landmark_schema = (
            dict(raw_pose_landmark_schema) if isinstance(raw_pose_landmark_schema, dict) else None
        )
        if model_task == "pose" and pose_landmark_schema is None:
            job.status = "failed"
            job.error_message = (
                "Pose video inference requires a bound ReefVision landmark schema before tracking"
            )
            job.completed_at = datetime.now(UTC)
            video.status = "tracking_failed"
            video.revision += 1
            session.commit()
            return False
        total_frames = video.frame_count

    LOGGER.info(
        "Starting video tracking job %s for video %s with model %s",
        job_id,
        video_id,
        model_id,
    )

    latest_progress = VideoTrackingProgress(0, 0, 0, 0)
    last_progress_write = 0.0
    last_cancel_check = 0.0
    last_progress_log = 0.0
    cancel_requested = False

    def should_cancel() -> bool:
        nonlocal cancel_requested, last_cancel_check

        now_monotonic = time.monotonic()
        if now_monotonic - last_cancel_check < CANCELLATION_CHECK_INTERVAL_SECONDS:
            return cancel_requested

        last_cancel_check = now_monotonic
        with factory() as session:
            live_job = session.get(Job, job_id)
            cancel_requested = live_job is None or live_job.status in {
                "cancel_requested",
                "cancelled",
            }
        return cancel_requested

    def report_progress(progress: VideoTrackingProgress) -> None:
        nonlocal last_progress_log, last_progress_write, latest_progress

        latest_progress = progress
        now_monotonic = time.monotonic()
        force = progress.frames_processed >= total_frames or progress.stage != "tracking"

        if not force and now_monotonic - last_progress_write < PROGRESS_WRITE_INTERVAL_SECONDS:
            return

        last_progress_write = now_monotonic
        heartbeat = datetime.now(UTC)

        with factory() as session:
            live_job = session.get(Job, job_id)

            if live_job is None:
                raise VideoTrackingCancelled("Video tracking job disappeared during inference")
            if live_job.status in {"cancel_requested", "cancelled"}:
                raise VideoTrackingCancelled("Video tracking cancelled by user")
            if live_job.status != "running":
                raise RuntimeError(
                    f"Video tracking stopped because job state became {live_job.status}"
                )

            result = dict(live_job.result_json or {})
            result.update(
                {
                    "stage": progress.stage,
                    "heartbeat_at": heartbeat.isoformat(),
                    "frames_processed": progress.frames_processed,
                    "detection_count": progress.detections_seen,
                    "tracked_observations_seen": progress.tracked_observations_seen,
                    "tracks_seen": progress.unique_tracks_seen,
                }
            )

            live_job.progress_current = min(
                progress.frames_processed,
                live_job.progress_total,
            )
            live_job.result_json = result
            session.commit()

        should_log = (
            progress.frames_processed == 1
            or progress.stage != "tracking"
            or force
            or now_monotonic - last_progress_log >= PROGRESS_LOG_INTERVAL_SECONDS
        )
        if should_log:
            last_progress_log = now_monotonic
            LOGGER.info(
                (
                    "Video tracking job %s progress %s/%s; "
                    "%s detections; %s tracked observations; %s tracks"
                ),
                job_id,
                progress.frames_processed,
                total_frames,
                progress.detections_seen,
                progress.tracked_observations_seen,
                progress.unique_tracks_seen,
            )

    try:
        report_progress(
            VideoTrackingProgress(
                frames_processed=0,
                detections_seen=0,
                tracked_observations_seen=0,
                unique_tracks_seen=0,
                stage="initializing_provider",
            )
        )

        provider = video_tracking_provider_for_name(provider_name)

        report_progress(
            VideoTrackingProgress(
                frames_processed=0,
                detections_seen=0,
                tracked_observations_seen=0,
                unique_tracks_seen=0,
                stage="provider_ready",
            )
        )

        link_detections = bool(request.get("link_detections", True))
        requested_tracker = str(request.get("tracker", "bytetrack.yaml"))
        resolve_tracker_name = getattr(provider, "resolve_tracker_name", None)
        tracker_name = (
            str(
                resolve_tracker_name(
                    requested_tracker,
                    link_detections=link_detections,
                )
            )
            if callable(resolve_tracker_name)
            else requested_tracker
            if link_detections
            else "instances-only"
        )
        confidence = float(request.get("confidence", 0.25))
        iou = float(request.get("iou", 0.5))
        device = str(request.get("device", "auto"))

        observations = provider.track(
            resolve_managed_project_path(settings, model_path),
            resolve_managed_project_path(settings, video_path),
            tracker=tracker_name,
            confidence=confidence,
            iou=iou,
            device=device,
            link_detections=link_detections,
            on_progress=report_progress,
            should_cancel=should_cancel,
        )

        with factory() as session:
            live_job = session.get(Job, job_id)
            if live_job is None:
                raise RuntimeError("Video tracking job disappeared")
            if live_job.status in {"cancel_requested", "cancelled"}:
                raise VideoTrackingCancelled("Video tracking cancelled by user")

            result = dict(live_job.result_json or {})
            result.update(
                {
                    "stage": "finalizing",
                    "heartbeat_at": datetime.now(UTC).isoformat(),
                }
            )
            live_job.result_json = result
            session.commit()

        grouped: dict[tuple[int, str], list[TrackObservation]] = defaultdict(list)
        unmapped_labels: set[str] = set()

        for item in observations:
            label_class_id = class_mapping.get(item.class_name.strip().casefold())
            if label_class_id is None:
                unmapped_labels.add(item.class_name)
                continue
            grouped[(item.provider_track_id, label_class_id)].append(item)

        minimum_frames = (
            max(1, int(request.get("minimum_track_frames", 2))) if link_detections else 1
        )

        with factory() as session:
            video = session.get(VideoAsset, video_id)
            job = session.get(Job, job_id)

            if video is None or job is None:
                raise RuntimeError("Video tracking records disappeared")
            if job.status in {"cancel_requested", "cancelled"}:
                raise VideoTrackingCancelled("Video tracking cancelled during finalization")

            existing = list(
                session.scalars(
                    select(VideoTrack).where(
                        VideoTrack.video_id == video_id,
                        VideoTrack.source_job_id == job_id,
                        VideoTrack.deleted_at.is_(None),
                    )
                )
            )

            persistence = GeoReferencedObservationService(session)

            # A tracking-job rerun replaces its previous machine outputs.
            # Remove the derived geographic observations before soft-deleting
            # and recreating those tracks so duplicate map points cannot
            # accumulate.
            persistence.delete_for_tracks(track.id for track in existing)

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
            pose_landmark_track_count = 0
            pose_temporal_observation_count = 0
            pose_unresolved_association_count = 0
            pose_identity_break_count = 0

            georeferencing_readiness = VideoGeoreferencingReadinessService(
                session,
                settings,
            ).evaluate(video_id)

            georeferencing_ready = georeferencing_readiness.ready
            georeferencing_issue_codes = [issue.code for issue in georeferencing_readiness.issues]

            georeferencing_service = (
                VideoGeoreferencingService(session, settings) if georeferencing_ready else None
            )

            georeferencing_attempted_count = 0
            georeferenced_observation_count = 0
            georeferencing_failure_count = 0

            for (provider_track_id, label_class_id), items in sorted(grouped.items()):
                ordered = sorted(items, key=lambda item: item.frame)
                if len(ordered) < minimum_frames:
                    continue

                track = VideoTrack(
                    video_id=video_id,
                    label_class_id=label_class_id,
                    track_number=next_number,
                    geometry_kind="bbox",
                    keyframes_json=_keyframes(ordered, pose_landmark_schema),
                    interpolation="linear",
                    status="machine_generated",
                    source_model_id=model_id,
                    source_job_id=job_id,
                    metadata_json={
                        "provider_track_id": provider_track_id,
                        "provider_name": provider.provider_id,
                        "provider_version": provider.provider_version,
                        "tracker": tracker_name,
                        "link_detections": link_detections,
                        "mean_confidence": mean(item.confidence for item in ordered),
                        "model_task": model_task,
                        "pose_tracking": model_task == "pose",
                        "pose_keypoint_count": max(
                            (len(item.keypoints or ()) for item in ordered),
                            default=0,
                        ),
                        "pose_landmark_schema": (
                            dict(pose_landmark_schema) if pose_landmark_schema is not None else None
                        ),
                    },
                )

                session.add(track)

                # We need the persistent ReefVision track UUID before
                # constructing GeoReferencedObservation.track_id.
                session.flush()

                if model_task == "pose" and any(item.keypoints for item in ordered):
                    temporal_result = PoseTemporalTrackingService(session).build(
                        track.id,
                        PoseTemporalAssociationBuildRequest(),
                        commit=False,
                    )
                    pose_landmark_track_count += temporal_result.created_landmark_tracks
                    pose_temporal_observation_count += temporal_result.created_observations
                    pose_unresolved_association_count += temporal_result.unresolved_associations
                    pose_identity_break_count += temporal_result.identity_breaks

                if georeferencing_service is not None:
                    georeferencing_attempted_count += len(ordered)

                    successful, failed = _georeference_track_observations(
                        georeferencing_service,
                        persistence,
                        video_id=video_id,
                        track_id=track.id,
                        observations=ordered,
                    )

                    georeferenced_observation_count += successful
                    georeferencing_failure_count += failed

                next_number += 1
                created += 1
                observation_count += len(ordered)

            completed_at = datetime.now(UTC)
            video.status = "tracked"
            video.revision += 1
            job.status = "succeeded"
            job.progress_current = video.frame_count
            job.result_json = {
                **dict(job.result_json or {}),
                "stage": "completed",
                "heartbeat_at": completed_at.isoformat(),
                "frames_processed": video.frame_count,
                "detection_count": latest_progress.detections_seen,
                "tracked_observations_seen": (latest_progress.tracked_observations_seen),
                "tracks_seen": latest_progress.unique_tracks_seen,
                "track_count": created,
                "observation_count": observation_count,
                "unmapped_labels": sorted(unmapped_labels),
                "provider_version": provider.provider_version,
                "project_id": project_id,
                "video_id": video_id,
                "model_id": model_id,
                "model_task": model_task,
                "pose_tracking": model_task == "pose",
                "pose_landmark_track_count": pose_landmark_track_count,
                "pose_temporal_observation_count": pose_temporal_observation_count,
                "pose_unresolved_association_count": pose_unresolved_association_count,
                "pose_identity_break_count": pose_identity_break_count,
                "pose_landmark_schema": (
                    dict(pose_landmark_schema) if pose_landmark_schema is not None else None
                ),
                "source_job_id": job_id,
                "tracker": tracker_name,
                "link_detections": link_detections,
                "confidence": confidence,
                "iou": iou,
                "device": device,
                "minimum_track_frames": minimum_frames,
                "georeferencing_ready": georeferencing_ready,
                "georeferencing_issue_codes": (georeferencing_issue_codes),
                "georeferencing_attempted_count": (georeferencing_attempted_count),
                "georeferenced_observation_count": (georeferenced_observation_count),
                "georeferencing_failure_count": (georeferencing_failure_count),
            }
            job.completed_at = completed_at
            session.commit()

        LOGGER.info(
            ("Completed video tracking job %s: %s tracks, %s retained observations, %s detections"),
            job_id,
            created,
            observation_count,
            latest_progress.detections_seen,
        )
        return True

    except VideoTrackingCancelled as exc:
        with factory() as session:
            job = session.get(Job, job_id)
            video = session.get(VideoAsset, str(request.get("video_id", "")))
            now = datetime.now(UTC)

            if job is not None:
                result = dict(job.result_json or {})
                result.update(
                    {
                        "stage": "cancelled",
                        "heartbeat_at": now.isoformat(),
                    }
                )
                job.status = "cancelled"
                job.result_json = result
                job.error_message = str(exc)
                job.completed_at = now

            if video is not None:
                video.status = "tracking_cancelled"
                video.revision += 1

            session.commit()

        LOGGER.info(
            "Cancelled video tracking job %s at frame %s",
            job_id,
            latest_progress.frames_processed,
        )
        return True

    except Exception as exc:
        LOGGER.exception("Video tracking job %s failed", job_id)

        with factory() as session:
            video = session.get(VideoAsset, str(request.get("video_id", "")))
            if video is not None:
                video.status = "tracking_failed"
                video.revision += 1
                session.commit()

        _fail(factory, job_id, str(exc))
        return False

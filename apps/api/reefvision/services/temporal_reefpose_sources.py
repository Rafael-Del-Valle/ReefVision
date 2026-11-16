"""Resolve, validate, and freeze native ReefPose video evidence."""

from __future__ import annotations

from collections import Counter
from itertools import pairwise
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseAnimalIdentity,
    PoseIdentityAssociationRun,
    PoseIdentityObservation,
    PoseLandmarkSchema,
    PoseLandmarkSchemaRevision,
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
    VideoAsset,
    VideoTrack,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.temporal_reefpose import TemporalPointRead, TemporalSource
from reefvision.schemas.videos import VideoTrackKeyframe
from reefvision.services.pose_schemas import definition_for_revision
from reefvision.storage.datasets import canonical_json_sha256

TEMPORAL_METHOD = "reefpose-residual-tcn"
TEMPORAL_FRAME_POLICY = "presentation_time_or_nominal_fps"
REVIEWED = frozenset({"scientist_confirmed", "scientist_verified"})
HUMAN_POSE_SOURCES = frozenset({"manual", "corrected", "human"})
GROUP_FIELDS = ("session_id", "recording_group", "animal_id", "group_key", "group_id")


def _group_tokens(metadata: dict[str, Any]) -> list[str]:
    return [
        f"group:{metadata[key]}"
        for key in GROUP_FIELDS
        if isinstance(metadata.get(key), str) and metadata[key].strip()
    ]


def track_binding(track: VideoTrack) -> dict[str, Any]:
    binding = (track.metadata_json or {}).get("pose_landmark_schema")
    return dict(binding) if isinstance(binding, dict) else {}


def source_model(session: Session, project_id: str, model_id: str) -> ModelRegistration:
    model = session.get(ModelRegistration, model_id)
    if model is None or model.project_id != project_id:
        raise NotFoundError("Pose model was not found in this project")
    return model


def frame_evidence(
    session: Session, project_id: str, track: VideoTrack, video: VideoAsset
) -> tuple[ModelRegistration, Job]:
    model = source_model(session, project_id, track.source_model_id or "")
    if model.provider_name != "reefpose" or model.task != "pose":
        raise ValidationError("Temporal refinement requires a native frame ReefPose checkpoint")
    job = session.get(Job, track.source_job_id)
    if (
        job is None
        or job.job_type != "video_tracking"
        or job.status != "succeeded"
        or job.project_id != project_id
        or job.request_json.get("video_id") != video.id
        or job.request_json.get("model_id") != model.id
    ):
        raise ValidationError("The selected track has no completed native video inference evidence")
    record = job.result_json or {}
    hashes = record.get("pose_input_hashes") or {}
    if hashes.get("model_sha256") != model.sha256 or hashes.get("video_sha256") != video.sha256:
        raise ConflictError("Frame inference lacks matching checkpoint and recording checksums")
    checksum = canonical_json_sha256(track.keyframes_json)
    if (record.get("pose_track_hashes") or {}).get(track.id) != checksum:
        raise ConflictError("Frame predictions changed since video inference. Select fresh output.")
    if not record.get("pose_inference_protocol"):
        raise ConflictError("Frame inference configuration is unavailable")
    return model, job


def _track(session: Session, project_id: str, track_id: str) -> tuple[VideoTrack, VideoAsset]:
    track = session.get(VideoTrack, track_id)
    video = session.get(VideoAsset, track.video_id) if track is not None else None
    if (
        track is None
        or track.deleted_at is not None
        or video is None
        or video.project_id != project_id
    ):
        raise NotFoundError("Pose track was not found in this project")
    return track, video


def _keyframes(track: VideoTrack, video: VideoAsset) -> dict[int, VideoTrackKeyframe]:
    try:
        frames = [VideoTrackKeyframe.model_validate(item) for item in track.keyframes_json]
    except ValueError as exc:
        raise ValidationError("Stored pose keyframes are invalid") from exc
    if (
        not frames
        or any(b.frame <= a.frame for a, b in pairwise(frames))
        or frames[-1].frame >= video.frame_count
    ):
        raise ValidationError("Pose keyframes must be unique and ordered within the source video")
    return {frame.frame: frame for frame in frames}


def _schema(session: Session, project_id: str, binding: dict[str, Any]) -> dict[str, Any]:
    revision = session.scalar(
        select(PoseLandmarkSchemaRevision)
        .join(PoseLandmarkSchema)
        .where(
            PoseLandmarkSchema.project_id == project_id,
            PoseLandmarkSchemaRevision.schema_id == binding.get("schema_id"),
            PoseLandmarkSchemaRevision.revision == binding.get("schema_revision"),
            PoseLandmarkSchemaRevision.content_hash == binding.get("content_hash"),
        )
    )
    if revision is None:
        raise ValidationError("The pose track must use a registered landmark schema revision")
    return {
        "schema_id": revision.schema_id,
        "schema_revision": revision.revision,
        "content_hash": revision.content_hash,
        **definition_for_revision(revision),
        "expanded_labels": list(revision.expanded_labels_json),
    }


def _point_mapping(
    keyframe: VideoTrackKeyframe, schema: dict[str, Any], *, human: bool
) -> dict[str, dict[str, Any]]:
    landmark_ids = [point["id"] for point in schema["landmarks"]]
    occurrences: Counter[str] = Counter()
    by_label = {}
    for landmark_id, label in zip(landmark_ids, schema["expanded_labels"], strict=True):
        by_label[(label, occurrences[label])] = landmark_id
        occurrences[label] += 1
    result: dict[str, dict[str, Any]] = {}
    for point in keyframe.pose_observations or []:
        if human and point.source not in HUMAN_POSE_SOURCES:
            continue
        landmark_id = point.landmark_id or by_label.get(
            (point.semantic_label, point.occurrence_index)
        )
        if landmark_id is None or landmark_id not in landmark_ids or landmark_id in result:
            raise ValidationError("Pose observations do not match the bound landmark schema")
        coordinates_defined = point.status in {"visible", "uncertain"}
        result[landmark_id] = TemporalPointRead(
            landmark_id=landmark_id,
            x=point.x if coordinates_defined else None,
            y=point.y if coordinates_defined else None,
            confidence=point.confidence,
            visibility=point.status,
        ).model_dump(mode="json")
    if not human and not result and keyframe.keypoints is not None:
        if len(keyframe.keypoints) != len(landmark_ids):
            raise ValidationError("Frame prediction count does not match its landmark schema")
        for landmark_id, (x, y, confidence) in zip(landmark_ids, keyframe.keypoints, strict=True):
            result[landmark_id] = TemporalPointRead(
                landmark_id=landmark_id,
                x=x if confidence > 0 else None,
                y=y if confidence > 0 else None,
                confidence=confidence,
                visibility="visible" if confidence > 0 else "absent",
            ).model_dump(mode="json")
    return result


def _identity(
    session: Session, payload: TemporalSource, video: VideoAsset, schema: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[PoseIdentityObservation]]:
    if payload.identity_observation_run_id is None:
        return None, []
    run = session.get(PoseIdentityAssociationRun, str(payload.identity_observation_run_id))
    animal = session.get(PoseAnimalIdentity, str(payload.animal_identity_id))
    if (
        run is None
        or animal is None
        or run.project_id != video.project_id
        or run.video_id != video.id
        or run.status != "completed"
        or run.pose_schema_id != schema["schema_id"]
        or run.pose_schema_revision != schema["schema_revision"]
        or run.pose_schema_content_hash != schema["content_hash"]
        or animal.association_run_id != run.id
        or animal.verification_state not in REVIEWED
        or run.algorithm == TEMPORAL_METHOD
    ):
        raise ValidationError("Select a reviewed compatible animal identity from this recording")
    observations = list(
        session.scalars(
            select(PoseIdentityObservation)
            .where(
                PoseIdentityObservation.animal_identity_id == animal.id,
                PoseIdentityObservation.is_current.is_(True),
                PoseIdentityObservation.verification_state.in_(REVIEWED),
            )
            .order_by(PoseIdentityObservation.frame_index)
        )
    )
    if not observations or len({item.frame_index for item in observations}) != len(observations):
        raise ValidationError(
            "The selected identity needs an unambiguous reviewed frame assignment"
        )
    return {
        "run_id": run.id,
        "run_revision": run.revision,
        "animal_id": animal.id,
        "animal_revision": animal.revision,
        "observations": [{"id": item.id, "revision": item.revision} for item in observations],
    }, observations


def _identity_target(
    observation: PoseIdentityObservation, landmark_ids: list[str]
) -> dict[str, dict[str, Any]]:
    targets = {}
    for point in observation.landmarks_json:
        if point.get("source") not in HUMAN_POSE_SOURCES:
            continue
        landmark_id = point.get("landmark_id")
        if landmark_id not in landmark_ids:
            raise ValidationError("Reviewed identity landmark does not match the schema")
        visibility = point.get("visibility", point.get("status", "visible"))
        visible = visibility in {"visible", "uncertain"}
        targets[landmark_id] = TemporalPointRead(
            landmark_id=landmark_id,
            x=point.get("x") if visible else None,
            y=point.get("y") if visible else None,
            visibility=visibility,
        ).model_dump(mode="json")
    return targets


def _verify_reviewed_pairing(
    session: Session,
    video: VideoAsset,
    frame_track_id: str,
    reviewed_track_id: str,
    association_run_id: str | None,
    animal_identity_id: str | None,
) -> None:
    statement = (
        select(PoseIdentityObservation)
        .join(PoseIdentityAssociationRun)
        .where(
            PoseIdentityAssociationRun.video_id == video.id,
            PoseIdentityAssociationRun.status == "completed",
            PoseIdentityAssociationRun.algorithm != TEMPORAL_METHOD,
            PoseIdentityObservation.source_video_track_id.in_((frame_track_id, reviewed_track_id)),
            PoseIdentityObservation.animal_identity_id.is_not(None),
            PoseIdentityObservation.is_current.is_(True),
            PoseIdentityObservation.verification_state.in_(REVIEWED),
        )
    )
    if association_run_id:
        statement = statement.where(PoseIdentityAssociationRun.id == association_run_id)
    assignments: dict[tuple[str, int], dict[str, str | None]] = {}
    known_memberships: dict[str, dict[str, set[str]]] = {}
    for item in session.scalars(statement):
        if item.animal_identity_id is not None:
            membership = known_memberships.setdefault(item.association_run_id, {})
            membership.setdefault(item.source_video_track_id, set()).add(item.animal_identity_id)
            if (
                animal_identity_id is not None
                and item.source_video_track_id == reviewed_track_id
                and item.animal_identity_id != animal_identity_id
            ):
                raise ValidationError("Selected reviewed landmarks belong to a different animal")
        observation = assignments.setdefault((item.association_run_id, item.frame_index), {})
        observation[item.source_video_track_id] = item.animal_identity_id
        if len(set(observation.values())) > 1:
            raise ValidationError(
                "Reviewed identity assigns the selected tracks to different animals"
            )
    for membership in known_memberships.values():
        if (
            frame_track_id in membership
            and reviewed_track_id in membership
            and membership[frame_track_id].isdisjoint(membership[reviewed_track_id])
        ):
            raise ValidationError(
                "Reviewed identity assigns the selected tracks to different animals"
            )


def freeze_source(session: Session, project_id: str, payload: TemporalSource) -> dict[str, Any]:
    track, video = _track(session, project_id, str(payload.frame_track_id))
    model, job = frame_evidence(session, project_id, track, video)
    schema = _schema(session, project_id, track_binding(track))
    job_record = job.result_json or {}
    identity, observations = _identity(session, payload, video, schema)
    frames = _keyframes(track, video)
    reviewed: dict[int, VideoTrackKeyframe] = {}
    review_snapshot = None
    if payload.reviewed_track_id is not None:
        reviewed_track, reviewed_video = _track(session, project_id, str(payload.reviewed_track_id))
        binding = track_binding(reviewed_track)
        if (
            reviewed_video.id != video.id
            or reviewed_track.label_class_id != track.label_class_id
            or reviewed_track.status not in {"verified", "reviewed"}
            or any(
                binding.get(key) != schema[key]
                for key in ("schema_id", "schema_revision", "content_hash")
            )
        ):
            raise ValidationError("Reviewed landmarks must belong to the same recording and schema")
        reviewed = _keyframes(reviewed_track, video)
        _verify_reviewed_pairing(
            session,
            video,
            track.id,
            reviewed_track.id,
            str(payload.identity_observation_run_id)
            if payload.identity_observation_run_id
            else None,
            str(payload.animal_identity_id) if payload.animal_identity_id else None,
        )
        review_snapshot = {
            "id": reviewed_track.id,
            "revision": reviewed_track.revision,
            "keyframes_sha256": canonical_json_sha256(reviewed_track.keyframes_json),
            "confirmed_same_animal": payload.confirm_same_animal,
        }
    if identity:
        if not any(item.source_video_track_id == track.id for item in observations):
            raise ValidationError("The reviewed identity has no observations on the selected track")
        allowed_indices = {
            item.frame_index for item in observations if item.source_video_track_id == track.id
        }
        frames = {index: frame for index, frame in frames.items() if index in allowed_indices}
        reviewed = {index: frame for index, frame in reviewed.items() if index in allowed_indices}
        observations = [item for item in observations if item.frame_index in allowed_indices]

    landmark_ids = [point["id"] for point in schema["landmarks"]]
    absent = {
        identifier: TemporalPointRead(
            landmark_id=identifier, x=None, y=None, visibility="absent"
        ).model_dump(mode="json")
        for identifier in landmark_ids
    }
    by_identity_frame = {item.frame_index: item for item in observations}
    breaks = sorted(payload.discontinuity_frames)
    if breaks and breaks[-1] >= video.frame_count:
        raise ValidationError("Discontinuity frame is outside the source recording")
    identity_breaks = {
        second.frame_index
        for first, second in pairwise(observations)
        if second.frame_index != first.frame_index + 1
    }
    evidence: list[dict[str, Any]] = []
    last_index = -1
    ordered_indices = sorted(frames.keys() | reviewed.keys() | by_identity_frame.keys())
    for index in ordered_indices:
        frame, target, identity_row = (
            frames.get(index),
            reviewed.get(index),
            by_identity_frame.get(index),
        )
        timestamp, timestamp_source = next(
            (
                (value, origin)
                for value, origin in (
                    (frame.timestamp_seconds if frame else None, "frame_presentation_timestamp"),
                    (target.timestamp_seconds if target else None, "reviewed_frame_timestamp"),
                    (identity_row.time_s if identity_row else None, "identity_time_unverified"),
                    (index / video.fps if video.fps > 0 else None, "nominal_fps"),
                )
                if value is not None
            ),
            (None, "unavailable"),
        )
        if timestamp is None or (evidence and timestamp <= evidence[-1]["timestamp_seconds"]):
            raise ValidationError("Source frames require strictly increasing timestamps")
        frame_points = _point_mapping(frame, schema, human=False) if frame else {}
        target_points = _point_mapping(target, schema, human=True) if target else {}
        if identity_row and not target_points:
            target_points = _identity_target(identity_row, landmark_ids)
        bbox = (
            frame.bbox
            if frame
            else target.bbox
            if target
            else identity_row.bbox_json
            if identity_row
            else None
        )
        evidence.append(
            {
                "frame_index": index,
                "timestamp_seconds": timestamp,
                "timestamp_source": timestamp_source,
                "annotation_timestamp_seconds": target.timestamp_seconds if target else None,
                "bbox": list(bbox) if bbox is not None else None,
                "frame_points": [frame_points.get(key, absent[key]) for key in landmark_ids]
                if frame
                else None,
                "target_points": [target_points.get(key) for key in landmark_ids]
                if target_points
                else None,
                "discontinuity": index in identity_breaks
                or any(last_index < item <= index for item in breaks),
            }
        )
        last_index = index
    if not evidence or not frames:
        raise ValidationError("The selected sequence has no native frame observations")
    metadata = video.metadata_json or {}
    timing_sources = sorted({frame["timestamp_source"] for frame in evidence})
    calibration = metadata.get("spatial_calibration")
    recording_key = str(metadata.get("recording_id") or f"sha256:{video.sha256}")
    related_groups = [
        f"content:{video.sha256}",
        f"recording:{recording_key}",
        *_group_tokens(metadata),
    ]
    if payload.group_key:
        related_groups.append(f"group:{payload.group_key}")
    return {
        "recording": {
            "id": video.id,
            "name": video.original_filename,
            "sha256": video.sha256,
            "recording_key": recording_key,
            "width": video.width_px,
            "height": video.height_px,
            "frame_count": video.frame_count,
            "fps": video.fps,
            "coordinate_space": "source_pixels",
            "calibration": calibration,
            "calibration_sha256": canonical_json_sha256(calibration) if calibration else None,
            "time_source": " + ".join(timing_sources),
        },
        "frame_track": {
            "id": track.id,
            "revision": track.revision,
            "keyframes_sha256": canonical_json_sha256(track.keyframes_json),
            "job_id": job.id,
        },
        "reviewed_track": review_snapshot,
        "identity": identity,
        "schema": schema,
        "frame_model": {
            "id": model.id,
            "checkpoint_sha256": model.sha256,
            "provider_version": model.provider_version,
            "configuration": job_record["pose_inference_protocol"],
            "configuration_sha256": canonical_json_sha256(job_record["pose_inference_protocol"]),
            "runtime_seconds": (
                max(0.0, (job.completed_at - job.started_at).total_seconds())
                if job.started_at is not None and job.completed_at is not None
                else None
            ),
        },
        "animal_id": identity["animal_id"] if identity else track.id,
        "groups": sorted(set(related_groups)),
        "declared_discontinuities": breaks,
        "frames": evidence,
    }


def frame_training_lineage(
    session: Session, model: ModelRegistration, *, visited: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Follow registered frame training, selection, and initialization evidence."""
    unavailable = {"complete": False, "recordings": [], "datasets": []}
    if model.id in visited:
        return unavailable
    metadata = model.metadata_json or {}
    recordings: dict[str, list[str]] = {}
    datasets = []
    complete = True
    for role in ("training", "validation"):
        identifier = metadata.get(f"source_pose_{role}_dataset_id")
        expected = metadata.get(f"source_pose_{role}_dataset_manifest_sha256")
        if not identifier:
            complete &= (
                role == "validation" and metadata.get("source_pose_validation_mode") == "none"
            )
            continue
        dataset = session.get(PoseTrainingDataset, identifier)
        if (
            dataset is None
            or dataset.project_id != model.project_id
            or dataset.manifest_sha256 != expected
        ):
            complete = False
            continue
        items = list(
            session.scalars(
                select(PoseTrainingDatasetItem).where(
                    PoseTrainingDatasetItem.dataset_id == dataset.id
                )
            )
        )
        if not items:
            complete = False
        datasets.append({"id": dataset.id, "sha256": dataset.manifest_sha256, "role": role})
        for item in items:
            provenance = item.acquisition_provenance_json or {}
            groups = recordings.setdefault(item.video_sha256, [])
            video = session.get(VideoAsset, item.video_id)
            tags = video.metadata_json if video is not None else {}
            frozen_groups = _group_tokens(provenance)
            if not frozen_groups:
                complete = False
            groups.extend(frozen_groups)
            # Current tags may reveal an overlap. They cannot establish that
            # training grouping was known when the frame checkpoint was selected.
            groups.extend(_group_tokens(tags))
            recording_id = provenance.get("recording_id") or tags.get("recording_id")
            if recording_id:
                groups.append(f"recording:{recording_id}")
    ancestor_id = metadata.get("source_initial_pose_model_id")
    ancestor_sha256 = metadata.get("source_initial_pose_model_sha256")
    if ancestor_id or ancestor_sha256:
        parent = session.get(ModelRegistration, ancestor_id) if ancestor_id else None
        if (
            parent is None
            or parent.project_id != model.project_id
            or parent.sha256 != ancestor_sha256
        ):
            complete = False
        else:
            ancestry = frame_training_lineage(session, parent, visited=visited | {model.id})
            complete &= ancestry["complete"]
            datasets.extend(ancestry["datasets"])
            for item in ancestry["recordings"]:
                recordings.setdefault(item["sha256"], []).extend(item["groups"])
    return {
        "complete": complete,
        "datasets": datasets,
        "recordings": [
            {"sha256": checksum, "groups": sorted(set(groups))}
            for checksum, groups in sorted(recordings.items())
        ],
    }

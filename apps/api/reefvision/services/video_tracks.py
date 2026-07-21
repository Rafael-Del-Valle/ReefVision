"""Revision-safe video-track persistence and manual correction operations."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    LabelClass,
    VideoAsset,
    VideoTrack,
    VideoTrackEvent,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.track_operations import (
    TrackDeleteRequest,
    TrackIdentitySwapRequest,
    TrackMergeRequest,
    TrackObservationAddRequest,
    TrackObservationDeleteRequest,
    TrackObservationReassignRequest,
    TrackObservationRestoreRequest,
    TrackObservationUpdateRequest,
    TrackOperationResponse,
    TrackRestoreRequest,
    TrackSplitRequest,
    VideoTrackEventResponse,
)
from reefvision.schemas.videos import (
    VideoTrackCreateRequest,
    VideoTrackKeyframe,
    VideoTrackResponse,
    VideoTrackUpdateRequest,
)


def _now() -> datetime:
    return datetime.now(UTC)


def observation_center(observation: VideoTrackKeyframe) -> tuple[float, float]:
    return (
        (float(observation.x_min) + float(observation.x_max)) / 2.0,
        (float(observation.y_min) + float(observation.y_max)) / 2.0,
    )


def _observation_payload(
    observation: VideoTrackKeyframe,
    *,
    video: VideoAsset,
    track_id: str,
    ordinal: int,
    manual_default: bool,
) -> dict[str, Any]:
    payload = observation.model_dump(mode="json")
    if not payload.get("id"):
        payload["id"] = str(
            uuid5(
                NAMESPACE_URL,
                f"reefvision-video-observation:{track_id}:{observation.frame_index}:{ordinal}",
            )
        )
    if payload.get("timestamp_seconds") is None:
        payload["timestamp_seconds"] = observation.frame_index / video.fps
    center_x, center_y = observation_center(observation)
    payload["centroid_x"] = center_x
    payload["centroid_y"] = center_y
    if manual_default and observation.source == "human":
        payload["manual_edit"] = True
    return payload


def normalize_track_observations(
    track: VideoTrack,
    video: VideoAsset,
) -> tuple[list[VideoTrackKeyframe], bool]:
    observations: list[VideoTrackKeyframe] = []
    normalized: list[dict[str, Any]] = []
    changed = False
    for ordinal, raw in enumerate(track.keyframes_json or []):
        observation = VideoTrackKeyframe.model_validate(raw)
        payload = _observation_payload(
            observation,
            video=video,
            track_id=track.id,
            ordinal=ordinal,
            manual_default=track.source_type == "human",
        )
        normalized_observation = VideoTrackKeyframe.model_validate(payload)
        normalized_payload = normalized_observation.model_dump(mode="json")
        observations.append(normalized_observation)
        normalized.append(normalized_payload)
        if normalized_payload != raw:
            changed = True
    if changed:
        track.keyframes_json = normalized
    if track.status == "generated" and track.source_type == "human":
        track.source_type = "generated"
        changed = True
    return observations, changed


def active_track_observations(track: VideoTrack, video: VideoAsset) -> list[VideoTrackKeyframe]:
    observations, _changed = normalize_track_observations(track, video)
    return sorted(
        (item for item in observations if item.deleted_at is None),
        key=lambda item: (item.frame_index, item.id or ""),
    )


def interpolate_track(track: VideoTrack, video: VideoAsset) -> list[VideoTrackKeyframe]:
    keyframes = active_track_observations(track, video)
    if len(keyframes) <= 1:
        return keyframes
    interpolated: list[VideoTrackKeyframe] = []
    for left, right in itertools.pairwise(keyframes):
        frame_delta = right.frame_index - left.frame_index
        if frame_delta <= 0:
            continue
        left_time = (
            float(left.timestamp_seconds)
            if left.timestamp_seconds is not None
            else left.frame_index / video.fps
        )
        right_time = (
            float(right.timestamp_seconds)
            if right.timestamp_seconds is not None
            else right.frame_index / video.fps
        )
        for frame_index in range(left.frame_index, right.frame_index):
            ratio = (frame_index - left.frame_index) / frame_delta
            geometry_ratio = 0.0 if track.interpolation == "hold" else ratio
            confidence = (
                left.confidence
                if right.confidence is None or left.confidence is None
                else float(left.confidence)
                + (float(right.confidence) - float(left.confidence)) * geometry_ratio
            )
            x_min = float(left.x_min) + (float(right.x_min) - float(left.x_min)) * geometry_ratio
            y_min = float(left.y_min) + (float(right.y_min) - float(left.y_min)) * geometry_ratio
            x_max = float(left.x_max) + (float(right.x_max) - float(left.x_max)) * geometry_ratio
            y_max = float(left.y_max) + (float(right.y_max) - float(left.y_max)) * geometry_ratio
            interpolated.append(
                VideoTrackKeyframe(
                    id=left.id if frame_index == left.frame_index else None,
                    frame_index=frame_index,
                    timestamp_seconds=left_time + (right_time - left_time) * ratio,
                    x_min=x_min,
                    y_min=y_min,
                    x_max=x_max,
                    y_max=y_max,
                    confidence=confidence,
                    source=(left.source if frame_index == left.frame_index else "interpolated"),
                    manual_edit=left.manual_edit if frame_index == left.frame_index else False,
                    automated_provenance=(
                        left.automated_provenance if frame_index == left.frame_index else None
                    ),
                    revision=left.revision if frame_index == left.frame_index else 1,
                )
            )
    interpolated.append(keyframes[-1])
    return interpolated


def track_response(track: VideoTrack, video: VideoAsset) -> VideoTrackResponse:
    observations, _changed = normalize_track_observations(track, video)
    return VideoTrackResponse(
        id=track.id,
        video_id=track.video_id,
        label_class_id=track.label_class_id,
        origin_job_id=track.origin_job_id,
        track_number=track.track_number,
        name=track.name,
        geometry_kind=track.geometry_kind,
        keyframes=sorted(observations, key=lambda item: (item.frame_index, item.id or "")),
        interpolation=track.interpolation,
        status=track.status,
        source_type=track.source_type,
        is_ground_truth=track.is_ground_truth,
        metadata_json=dict(track.metadata_json or {}),
        created_by=track.created_by,
        updated_by=track.updated_by,
        created_at=track.created_at,
        updated_at=track.updated_at,
        deleted_at=track.deleted_at,
        revision=track.revision,
    )


def _snapshot(track: VideoTrack, video: VideoAsset) -> dict[str, Any]:
    return track_response(track, video).model_dump(mode="json")


class VideoTrackCorrectionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _track(self, track_id: str, *, include_deleted: bool = False) -> VideoTrack:
        track = self.session.get(VideoTrack, track_id)
        if track is None or (track.deleted_at is not None and not include_deleted):
            raise NotFoundError("Video track not found")
        return track

    def _validate_class(self, video: VideoAsset, label_class_id: str | None) -> None:
        if label_class_id is None:
            return
        label_class = self.session.get(LabelClass, label_class_id)
        if label_class is None or label_class.project_id != video.project_id:
            raise ValidationError("Track classes must belong to the video project")

    def _validate_observations(
        self,
        video: VideoAsset,
        observations: list[VideoTrackKeyframe],
        *,
        require_active: bool = True,
    ) -> None:
        active = [item for item in observations if item.deleted_at is None]
        if require_active and not active:
            raise ValidationError("A video track requires at least one active observation")
        frames = [item.frame_index for item in active]
        if len(frames) != len(set(frames)):
            raise ConflictError("A track cannot contain duplicate active frame observations")
        ids = [item.id for item in observations if item.id]
        if len(ids) != len(set(ids)):
            raise ConflictError("A track cannot contain duplicate observation IDs")
        for observation in observations:
            if observation.frame_index >= video.frame_count:
                raise ValidationError("Track observations must fall within the video")
            if observation.x_max > video.width_px or observation.y_max > video.height_px:
                raise ValidationError("Track boxes must remain inside the video frame")
            if (
                observation.timestamp_seconds is not None
                and float(observation.timestamp_seconds) > video.duration_seconds + 1 / video.fps
            ):
                raise ValidationError("Observation timestamps must fall within the video duration")

    @staticmethod
    def _require_revision(track: VideoTrack, expected_revision: int | None) -> None:
        if expected_revision is not None and track.revision != expected_revision:
            raise ConflictError(
                f"Video track revision conflict: expected {expected_revision}, "
                f"current revision is {track.revision}"
            )

    def _existing_event(self, operation_id: str | None) -> VideoTrackEvent | None:
        if not operation_id:
            return None
        return self.session.scalar(
            select(VideoTrackEvent).where(VideoTrackEvent.operation_id == operation_id)
        )

    def _event_tracks(self, event: VideoTrackEvent) -> list[VideoTrackResponse]:
        responses: list[VideoTrackResponse] = []
        for track_id in event.result_json.get("track_ids", []):
            track = self.session.get(VideoTrack, str(track_id))
            if track is not None:
                responses.append(track_response(track, self._video(track.video_id)))
        return responses

    def _replayed_operation(self, event: VideoTrackEvent) -> TrackOperationResponse:
        return TrackOperationResponse(
            operation=event.event_type,
            operation_id=event.operation_id,
            tracks=self._event_tracks(event),
            deleted_track_ids=[
                str(item) for item in event.result_json.get("deleted_track_ids", [])
            ],
            warnings=[str(item) for item in event.result_json.get("warnings", [])],
            replayed=True,
        )

    def _add_event(
        self,
        *,
        track: VideoTrack,
        event_type: str,
        operation_id: str | None,
        actor: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        track_ids: list[str],
        deleted_track_ids: list[str] | None = None,
        warnings: list[str] | None = None,
        related_tracks: list[VideoTrack] | None = None,
    ) -> None:
        result = {
            "track_ids": track_ids,
            "deleted_track_ids": deleted_track_ids or [],
            "warnings": warnings or [],
        }
        event_tracks = [track, *(related_tracks or [])]
        for index, event_track in enumerate(event_tracks):
            self.session.add(
                VideoTrackEvent(
                    video_track_id=event_track.id,
                    video_id=event_track.video_id,
                    operation_id=operation_id if index == 0 else None,
                    event_type=event_type,
                    before_json=before,
                    after_json=after,
                    result_json={**result, "operation_id": operation_id},
                    actor=actor,
                )
            )

    def _next_track_number(self, video_id: str) -> int:
        maximum = self.session.scalar(
            select(func.max(VideoTrack.track_number)).where(VideoTrack.video_id == video_id)
        )
        return int(maximum or 0) + 1

    def list_tracks(
        self,
        video_id: str,
        *,
        include_deleted: bool = False,
    ) -> list[VideoTrackResponse]:
        video = self._video(video_id)
        query = select(VideoTrack).where(VideoTrack.video_id == video_id)
        if not include_deleted:
            query = query.where(VideoTrack.deleted_at.is_(None))
        tracks = list(self.session.scalars(query.order_by(VideoTrack.track_number, VideoTrack.id)))
        changed = False
        responses: list[VideoTrackResponse] = []
        for track in tracks:
            _observations, normalized = normalize_track_observations(track, video)
            changed = changed or normalized
            responses.append(track_response(track, video))
        if changed:
            self.session.commit()
        return responses

    def create_track(
        self,
        video_id: str,
        request: VideoTrackCreateRequest,
    ) -> VideoTrackResponse:
        replay = self._existing_event(request.operation_id)
        if replay is not None:
            tracks = self._event_tracks(replay)
            if tracks:
                return tracks[0]
        video = self._video(video_id)
        if request.video_id != video.id:
            raise ValidationError("Track request video_id does not match the route")
        self._validate_class(video, request.label_class_id)
        existing = self.session.scalar(
            select(VideoTrack).where(
                VideoTrack.video_id == video.id,
                VideoTrack.track_number == request.track_number,
            )
        )
        if existing is not None:
            raise ConflictError("A track with this number already exists for the video")
        track = VideoTrack(
            video_id=video.id,
            label_class_id=request.label_class_id,
            track_number=request.track_number,
            name=request.name,
            geometry_kind=request.geometry_kind,
            keyframes_json=[],
            interpolation=request.interpolation,
            status=request.status,
            source_type="human",
            is_ground_truth=request.is_ground_truth,
            metadata_json={"source": "human", "automated_provenance_preserved": True},
            created_by=request.actor,
            updated_by=request.actor,
        )
        self.session.add(track)
        self.session.flush()
        observations = [
            VideoTrackKeyframe.model_validate(
                _observation_payload(
                    item,
                    video=video,
                    track_id=track.id,
                    ordinal=index,
                    manual_default=True,
                )
            )
            for index, item in enumerate(request.keyframes)
        ]
        self._validate_observations(video, observations)
        track.keyframes_json = [item.model_dump(mode="json") for item in observations]
        after = _snapshot(track, video)
        self._add_event(
            track=track,
            event_type="track_created",
            operation_id=request.operation_id,
            actor=request.actor,
            before=None,
            after=after,
            track_ids=[track.id],
        )
        self.session.commit()
        self.session.refresh(track)
        return track_response(track, video)

    @staticmethod
    def _automated_snapshot(
        observation: VideoTrackKeyframe,
        track: VideoTrack,
    ) -> dict[str, Any]:
        return {
            "observation": observation.model_dump(mode="json"),
            "track_provenance": dict(track.metadata_json or {}),
        }

    def _merge_wholesale_observations(
        self,
        *,
        track: VideoTrack,
        video: VideoAsset,
        requested: list[VideoTrackKeyframe],
    ) -> list[VideoTrackKeyframe]:
        current, _changed = normalize_track_observations(track, video)
        by_id = {item.id: item for item in current if item.id}
        by_frame = {item.frame_index: item for item in current if item.deleted_at is None}
        used_ids: set[str] = set()
        merged: list[VideoTrackKeyframe] = []
        for ordinal, incoming in enumerate(requested):
            matched = by_id.get(incoming.id) if incoming.id else by_frame.get(incoming.frame_index)
            payload = _observation_payload(
                incoming,
                video=video,
                track_id=track.id,
                ordinal=ordinal,
                manual_default=True,
            )
            if matched is not None:
                payload["id"] = matched.id
                changed = any(
                    payload[name] != matched.model_dump(mode="json").get(name)
                    for name in (
                        "frame_index",
                        "timestamp_seconds",
                        "x_min",
                        "y_min",
                        "x_max",
                        "y_max",
                        "confidence",
                    )
                )
                if changed:
                    payload["revision"] = matched.revision + 1
                    payload["manual_edit"] = True
                    payload["source"] = "human"
                    payload["automated_provenance"] = matched.automated_provenance or (
                        self._automated_snapshot(matched, track)
                        if matched.source not in {"human", "manual"}
                        or track.source_type == "generated"
                        else None
                    )
                else:
                    payload["revision"] = matched.revision
                    payload["manual_edit"] = matched.manual_edit
                    payload["source"] = matched.source
                    payload["automated_provenance"] = matched.automated_provenance
                    payload["deleted_at"] = matched.model_dump(mode="json")["deleted_at"]
            observation = VideoTrackKeyframe.model_validate(payload)
            if observation.id:
                used_ids.add(observation.id)
            merged.append(observation)
        for current_observation in current:
            if current_observation.id in used_ids:
                continue
            payload = current_observation.model_dump(mode="json")
            if current_observation.deleted_at is None:
                payload["deleted_at"] = _now().isoformat()
                payload["revision"] = current_observation.revision + 1
                payload["manual_edit"] = True
                payload["source"] = "human"
                if (
                    not current_observation.automated_provenance
                    and track.source_type == "generated"
                ):
                    payload["automated_provenance"] = self._automated_snapshot(
                        current_observation,
                        track,
                    )
            merged.append(VideoTrackKeyframe.model_validate(payload))
        return merged

    def update_track(
        self,
        track_id: str,
        request: VideoTrackUpdateRequest,
    ) -> VideoTrackResponse:
        replay = self._existing_event(request.operation_id)
        if replay is not None:
            tracks = self._event_tracks(replay)
            if tracks:
                return tracks[0]
        track = self._track(track_id)
        self._require_revision(track, request.expected_revision)
        video = self._video(track.video_id)
        before = _snapshot(track, video)
        label_class_id = (
            request.label_class_id
            if "label_class_id" in request.model_fields_set
            else track.label_class_id
        )
        self._validate_class(video, label_class_id)
        track.label_class_id = label_class_id
        if "name" in request.model_fields_set:
            track.name = request.name
        if request.keyframes is not None:
            observations = self._merge_wholesale_observations(
                track=track,
                video=video,
                requested=request.keyframes,
            )
            self._validate_observations(video, observations)
            track.keyframes_json = [item.model_dump(mode="json") for item in observations]
        if request.interpolation is not None:
            track.interpolation = request.interpolation
        if request.status is not None:
            track.status = request.status
        if request.is_ground_truth is not None:
            track.is_ground_truth = request.is_ground_truth
        if track.is_ground_truth and track.status != "verified":
            raise ValidationError("Ground-truth tracks must have verified status")
        track.updated_by = request.actor
        track.revision += 1
        after = _snapshot(track, video)
        self._add_event(
            track=track,
            event_type="track_updated",
            operation_id=request.operation_id,
            actor=request.actor,
            before=before,
            after=after,
            track_ids=[track.id],
        )
        self.session.commit()
        self.session.refresh(track)
        return track_response(track, video)

    def add_observation(
        self,
        track_id: str,
        request: TrackObservationAddRequest,
    ) -> TrackOperationResponse:
        replay = self._existing_event(request.operation_id)
        if replay is not None:
            return self._replayed_operation(replay)
        track = self._track(track_id)
        self._require_revision(track, request.expected_revision)
        video = self._video(track.video_id)
        before = _snapshot(track, video)
        observations, _changed = normalize_track_observations(track, video)
        payload = _observation_payload(
            request.observation,
            video=video,
            track_id=track.id,
            ordinal=len(observations),
            manual_default=True,
        )
        payload["id"] = request.observation.id or str(uuid4())
        payload["source"] = "human"
        payload["manual_edit"] = True
        observation = VideoTrackKeyframe.model_validate(payload)
        observations.append(observation)
        self._validate_observations(video, observations)
        track.keyframes_json = [item.model_dump(mode="json") for item in observations]
        track.updated_by = request.actor
        track.revision += 1
        after = _snapshot(track, video)
        self._add_event(
            track=track,
            event_type="observation_added",
            operation_id=request.operation_id,
            actor=request.actor,
            before=before,
            after=after,
            track_ids=[track.id],
        )
        self.session.commit()
        return TrackOperationResponse(
            operation="observation_added",
            operation_id=request.operation_id,
            tracks=[track_response(track, video)],
        )

    def _observation_index(
        self,
        observations: list[VideoTrackKeyframe],
        observation_id: str,
    ) -> int:
        for index, observation in enumerate(observations):
            if observation.id == observation_id:
                return index
        raise NotFoundError("Video track observation not found")

    def update_observation(
        self,
        track_id: str,
        observation_id: str,
        request: TrackObservationUpdateRequest,
    ) -> TrackOperationResponse:
        replay = self._existing_event(request.operation_id)
        if replay is not None:
            return self._replayed_operation(replay)
        track = self._track(track_id)
        self._require_revision(track, request.expected_revision)
        video = self._video(track.video_id)
        before = _snapshot(track, video)
        observations, _changed = normalize_track_observations(track, video)
        index = self._observation_index(observations, observation_id)
        existing = observations[index]
        if existing.deleted_at is not None:
            raise ConflictError("Restore the observation before editing it")
        payload = existing.model_dump(mode="json")
        for field in (
            "frame_index",
            "timestamp_seconds",
            "x_min",
            "y_min",
            "x_max",
            "y_max",
            "confidence",
        ):
            if field in request.model_fields_set:
                payload[field] = getattr(request, field)
        payload["source"] = "human"
        payload["manual_edit"] = True
        payload["revision"] = existing.revision + 1
        if not existing.automated_provenance and (
            existing.source not in {"human", "manual"} or track.source_type == "generated"
        ):
            payload["automated_provenance"] = self._automated_snapshot(existing, track)
        observations[index] = VideoTrackKeyframe.model_validate(payload)
        self._validate_observations(video, observations)
        track.keyframes_json = [item.model_dump(mode="json") for item in observations]
        track.updated_by = request.actor
        track.revision += 1
        after = _snapshot(track, video)
        self._add_event(
            track=track,
            event_type="observation_updated",
            operation_id=request.operation_id,
            actor=request.actor,
            before=before,
            after=after,
            track_ids=[track.id],
        )
        self.session.commit()
        return TrackOperationResponse(
            operation="observation_updated",
            operation_id=request.operation_id,
            tracks=[track_response(track, video)],
        )

    def _set_observation_deleted(
        self,
        *,
        track_id: str,
        observation_id: str,
        request: TrackObservationDeleteRequest | TrackObservationRestoreRequest,
        restore: bool,
    ) -> TrackOperationResponse:
        replay = self._existing_event(request.operation_id)
        if replay is not None:
            return self._replayed_operation(replay)
        track = self._track(track_id)
        self._require_revision(track, request.expected_revision)
        video = self._video(track.video_id)
        before = _snapshot(track, video)
        observations, _changed = normalize_track_observations(track, video)
        index = self._observation_index(observations, observation_id)
        existing = observations[index]
        if restore and existing.deleted_at is None:
            raise ConflictError("Video track observation is not deleted")
        if not restore and existing.deleted_at is not None:
            raise ConflictError("Video track observation is already deleted")
        payload = existing.model_dump(mode="json")
        payload["deleted_at"] = None if restore else _now().isoformat()
        payload["manual_edit"] = True
        payload["source"] = "human"
        payload["revision"] = existing.revision + 1
        if not existing.automated_provenance and track.source_type == "generated":
            payload["automated_provenance"] = self._automated_snapshot(existing, track)
        observations[index] = VideoTrackKeyframe.model_validate(payload)
        self._validate_observations(video, observations, require_active=restore)
        track.keyframes_json = [item.model_dump(mode="json") for item in observations]
        track.updated_by = request.actor
        track.revision += 1
        event_type = "observation_restored" if restore else "observation_deleted"
        after = _snapshot(track, video)
        self._add_event(
            track=track,
            event_type=event_type,
            operation_id=request.operation_id,
            actor=request.actor,
            before=before,
            after=after,
            track_ids=[track.id],
        )
        self.session.commit()
        return TrackOperationResponse(
            operation=event_type,
            operation_id=request.operation_id,
            tracks=[track_response(track, video)],
        )

    def delete_observation(
        self,
        track_id: str,
        observation_id: str,
        request: TrackObservationDeleteRequest,
    ) -> TrackOperationResponse:
        return self._set_observation_deleted(
            track_id=track_id,
            observation_id=observation_id,
            request=request,
            restore=False,
        )

    def restore_observation(
        self,
        track_id: str,
        observation_id: str,
        request: TrackObservationRestoreRequest,
    ) -> TrackOperationResponse:
        return self._set_observation_deleted(
            track_id=track_id,
            observation_id=observation_id,
            request=request,
            restore=True,
        )

    def delete_track(
        self,
        track_id: str,
        request: TrackDeleteRequest | None = None,
    ) -> TrackOperationResponse:
        operation_id = request.operation_id if request is not None else None
        replay = self._existing_event(operation_id)
        if replay is not None:
            return self._replayed_operation(replay)
        track = self._track(track_id, include_deleted=True)
        if track.deleted_at is not None:
            video = self._video(track.video_id)
            return TrackOperationResponse(
                operation="track_deleted",
                operation_id=operation_id,
                tracks=[track_response(track, video)],
                deleted_track_ids=[track.id],
                replayed=True,
            )
        if request is not None:
            self._require_revision(track, request.expected_revision)
        video = self._video(track.video_id)
        before = _snapshot(track, video)
        track.deleted_at = _now()
        track.status = "archived"
        track.is_ground_truth = False
        track.updated_by = request.actor if request is not None else "local_user"
        track.revision += 1
        after = _snapshot(track, video)
        self._add_event(
            track=track,
            event_type="track_deleted",
            operation_id=operation_id,
            actor=track.updated_by,
            before=before,
            after=after,
            track_ids=[track.id],
            deleted_track_ids=[track.id],
        )
        self.session.commit()
        return TrackOperationResponse(
            operation="track_deleted",
            operation_id=operation_id,
            tracks=[track_response(track, video)],
            deleted_track_ids=[track.id],
        )

    def restore_track(
        self,
        track_id: str,
        request: TrackRestoreRequest,
    ) -> TrackOperationResponse:
        replay = self._existing_event(request.operation_id)
        if replay is not None:
            return self._replayed_operation(replay)
        track = self._track(track_id, include_deleted=True)
        self._require_revision(track, request.expected_revision)
        if track.deleted_at is None:
            raise ConflictError("Video track is not deleted")
        video = self._video(track.video_id)
        duplicate = self.session.scalar(
            select(VideoTrack).where(
                VideoTrack.video_id == video.id,
                VideoTrack.track_number == track.track_number,
                VideoTrack.deleted_at.is_(None),
                VideoTrack.id != track.id,
            )
        )
        if duplicate is not None:
            raise ConflictError("Track number is already used by an active track")
        before = _snapshot(track, video)
        track.deleted_at = None
        track.status = "verified" if track.source_type == "human" else "generated"
        track.updated_by = request.actor
        track.revision += 1
        after = _snapshot(track, video)
        self._add_event(
            track=track,
            event_type="track_restored",
            operation_id=request.operation_id,
            actor=request.actor,
            before=before,
            after=after,
            track_ids=[track.id],
        )
        self.session.commit()
        return TrackOperationResponse(
            operation="track_restored",
            operation_id=request.operation_id,
            tracks=[track_response(track, video)],
        )

    def split_track(self, track_id: str, request: TrackSplitRequest) -> TrackOperationResponse:
        replay = self._existing_event(request.operation_id)
        if replay is not None:
            return self._replayed_operation(replay)
        track = self._track(track_id)
        self._require_revision(track, request.expected_revision)
        video = self._video(track.video_id)
        before = _snapshot(track, video)
        observations, _changed = normalize_track_observations(track, video)
        moving = [
            item
            for item in observations
            if item.deleted_at is None and item.frame_index >= request.split_frame
        ]
        staying = [
            item
            for item in observations
            if item.deleted_at is not None or item.frame_index < request.split_frame
        ]
        if not moving or not any(item.deleted_at is None for item in staying):
            raise ValidationError("A split must leave active observations on both tracks")
        new_track = VideoTrack(
            video_id=track.video_id,
            label_class_id=track.label_class_id,
            origin_job_id=track.origin_job_id,
            track_number=self._next_track_number(track.video_id),
            name=request.new_track_key or f"{track.name or f'Track {track.track_number}'} split",
            geometry_kind=track.geometry_kind,
            keyframes_json=[item.model_dump(mode="json") for item in moving],
            interpolation=track.interpolation,
            status=track.status,
            source_type=track.source_type,
            is_ground_truth=track.is_ground_truth,
            metadata_json={
                **dict(track.metadata_json or {}),
                "split_from_track_id": track.id,
                "split_frame": request.split_frame,
                "manual_correction": True,
            },
            created_by=request.actor,
            updated_by=request.actor,
        )
        self.session.add(new_track)
        self.session.flush()
        track.keyframes_json = [item.model_dump(mode="json") for item in staying]
        track.updated_by = request.actor
        track.revision += 1
        after = {
            "primary": _snapshot(track, video),
            "split": _snapshot(new_track, video),
        }
        self._add_event(
            track=track,
            event_type="track_split",
            operation_id=request.operation_id,
            actor=request.actor,
            before=before,
            after=after,
            track_ids=[track.id, new_track.id],
            related_tracks=[new_track],
        )
        self.session.commit()
        return TrackOperationResponse(
            operation="track_split",
            operation_id=request.operation_id,
            tracks=[track_response(track, video), track_response(new_track, video)],
        )

    def _paired_tracks(
        self,
        first_id: str,
        second_id: str,
        first_revision: int,
        second_revision: int,
    ) -> tuple[VideoTrack, VideoTrack, VideoAsset]:
        first = self._track(first_id)
        second = self._track(second_id)
        if first.video_id != second.video_id:
            raise ValidationError("Track corrections cannot cross videos")
        self._require_revision(first, first_revision)
        self._require_revision(second, second_revision)
        return first, second, self._video(first.video_id)

    def merge_tracks(self, request: TrackMergeRequest) -> TrackOperationResponse:
        replay = self._existing_event(request.operation_id)
        if replay is not None:
            return self._replayed_operation(replay)
        primary, secondary, video = self._paired_tracks(
            request.primary_track_id,
            request.secondary_track_id,
            request.expected_primary_revision,
            request.expected_secondary_revision,
        )
        before = {
            "primary": _snapshot(primary, video),
            "secondary": _snapshot(secondary, video),
        }
        primary_observations, _changed = normalize_track_observations(primary, video)
        secondary_observations, _changed = normalize_track_observations(secondary, video)
        selected: dict[int, VideoTrackKeyframe] = {
            item.frame_index: item for item in primary_observations if item.deleted_at is None
        }
        for observation in secondary_observations:
            if observation.deleted_at is not None:
                continue
            existing = selected.get(observation.frame_index)
            if existing is None:
                selected[observation.frame_index] = observation
            elif request.conflict_policy == "highest_confidence":
                existing_confidence = (
                    float(existing.confidence) if existing.confidence is not None else -1.0
                )
                incoming_confidence = (
                    float(observation.confidence) if observation.confidence is not None else -1.0
                )
                if incoming_confidence > existing_confidence:
                    selected[observation.frame_index] = observation
        retained_deleted = [
            item
            for item in primary_observations
            if item.deleted_at is not None
            and item.id not in {value.id for value in selected.values()}
        ]
        merged = [*selected.values(), *retained_deleted]
        self._validate_observations(video, merged)
        primary.keyframes_json = [
            item.model_dump(mode="json")
            for item in sorted(merged, key=lambda value: (value.frame_index, value.id or ""))
        ]
        primary.label_class_id = primary.label_class_id or secondary.label_class_id
        primary.updated_by = request.actor
        primary.revision += 1
        primary.metadata_json = {
            **dict(primary.metadata_json or {}),
            "merged_track_ids": sorted(
                {
                    *[str(item) for item in primary.metadata_json.get("merged_track_ids", [])],
                    secondary.id,
                }
            ),
            "manual_correction": True,
        }
        secondary.deleted_at = _now()
        secondary.status = "archived"
        secondary.is_ground_truth = False
        secondary.updated_by = request.actor
        secondary.revision += 1
        after = {
            "primary": _snapshot(primary, video),
            "secondary": _snapshot(secondary, video),
        }
        self._add_event(
            track=primary,
            event_type="tracks_merged",
            operation_id=request.operation_id,
            actor=request.actor,
            before=before,
            after=after,
            track_ids=[primary.id, secondary.id],
            deleted_track_ids=[secondary.id],
            related_tracks=[secondary],
        )
        self.session.commit()
        return TrackOperationResponse(
            operation="tracks_merged",
            operation_id=request.operation_id,
            tracks=[track_response(primary, video), track_response(secondary, video)],
            deleted_track_ids=[secondary.id],
        )

    def identity_swap(self, request: TrackIdentitySwapRequest) -> TrackOperationResponse:
        replay = self._existing_event(request.operation_id)
        if replay is not None:
            return self._replayed_operation(replay)
        first, second, video = self._paired_tracks(
            request.first_track_id,
            request.second_track_id,
            request.expected_first_revision,
            request.expected_second_revision,
        )
        before = {
            "first": _snapshot(first, video),
            "second": _snapshot(second, video),
        }
        first_observations, _changed = normalize_track_observations(first, video)
        second_observations, _changed = normalize_track_observations(second, video)
        first_head = [
            item
            for item in first_observations
            if item.deleted_at is not None or item.frame_index <= request.after_frame
        ]
        first_tail = [
            item
            for item in first_observations
            if item.deleted_at is None and item.frame_index > request.after_frame
        ]
        second_head = [
            item
            for item in second_observations
            if item.deleted_at is not None or item.frame_index <= request.after_frame
        ]
        second_tail = [
            item
            for item in second_observations
            if item.deleted_at is None and item.frame_index > request.after_frame
        ]
        first_result = [*first_head, *second_tail]
        second_result = [*second_head, *first_tail]
        self._validate_observations(video, first_result)
        self._validate_observations(video, second_result)
        first.keyframes_json = [item.model_dump(mode="json") for item in first_result]
        second.keyframes_json = [item.model_dump(mode="json") for item in second_result]
        for track in (first, second):
            track.updated_by = request.actor
            track.revision += 1
            track.metadata_json = {
                **dict(track.metadata_json or {}),
                "manual_correction": True,
                "last_identity_switch_frame": request.after_frame,
            }
        after = {
            "first": _snapshot(first, video),
            "second": _snapshot(second, video),
        }
        self._add_event(
            track=first,
            event_type="identity_switch_corrected",
            operation_id=request.operation_id,
            actor=request.actor,
            before=before,
            after=after,
            track_ids=[first.id, second.id],
            related_tracks=[second],
        )
        self.session.commit()
        return TrackOperationResponse(
            operation="identity_switch_corrected",
            operation_id=request.operation_id,
            tracks=[track_response(first, video), track_response(second, video)],
        )

    def reassign_observations(
        self,
        request: TrackObservationReassignRequest,
    ) -> TrackOperationResponse:
        replay = self._existing_event(request.operation_id)
        if replay is not None:
            return self._replayed_operation(replay)
        source, target, video = self._paired_tracks(
            request.source_track_id,
            request.target_track_id,
            request.expected_source_revision,
            request.expected_target_revision,
        )
        before = {
            "source": _snapshot(source, video),
            "target": _snapshot(target, video),
        }
        source_observations, _changed = normalize_track_observations(source, video)
        target_observations, _changed = normalize_track_observations(target, video)
        requested_ids = set(request.observation_ids)
        moving = [
            item
            for item in source_observations
            if item.id in requested_ids and item.deleted_at is None
        ]
        if {item.id for item in moving} != requested_ids:
            raise ValidationError("All reassigned observations must be active on the source track")
        target_frames = {
            item.frame_index for item in target_observations if item.deleted_at is None
        }
        conflict_frames = sorted(target_frames & {item.frame_index for item in moving})
        if conflict_frames:
            raise ConflictError(
                "Target track already has observations at frames "
                + ", ".join(str(item) for item in conflict_frames)
            )
        source_result = [item for item in source_observations if item.id not in requested_ids]
        target_result = [*target_observations, *moving]
        self._validate_observations(video, source_result)
        self._validate_observations(video, target_result)
        source.keyframes_json = [item.model_dump(mode="json") for item in source_result]
        target.keyframes_json = [item.model_dump(mode="json") for item in target_result]
        for track in (source, target):
            track.updated_by = request.actor
            track.revision += 1
            track.metadata_json = {
                **dict(track.metadata_json or {}),
                "manual_correction": True,
            }
        after = {
            "source": _snapshot(source, video),
            "target": _snapshot(target, video),
        }
        self._add_event(
            track=source,
            event_type="observations_reassigned",
            operation_id=request.operation_id,
            actor=request.actor,
            before=before,
            after=after,
            track_ids=[source.id, target.id],
            related_tracks=[target],
        )
        self.session.commit()
        return TrackOperationResponse(
            operation="observations_reassigned",
            operation_id=request.operation_id,
            tracks=[track_response(source, video), track_response(target, video)],
        )

    def list_events(self, track_id: str) -> list[VideoTrackEventResponse]:
        track = self._track(track_id, include_deleted=True)
        events = list(
            self.session.scalars(
                select(VideoTrackEvent)
                .where(VideoTrackEvent.video_track_id == track.id)
                .order_by(VideoTrackEvent.created_at, VideoTrackEvent.id)
            )
        )
        return [
            VideoTrackEventResponse.model_validate(item, from_attributes=True) for item in events
        ]

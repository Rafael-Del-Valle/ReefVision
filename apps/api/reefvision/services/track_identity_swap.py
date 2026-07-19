"""Conflict-safe tail identity swapping for persisted video tracks."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import VideoAsset, VideoTrack, VideoTrackEvent
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.track_operations import (
    TrackIdentitySwapRequest,
    TrackOperationResponse,
)
from reefvision.services.track_operations import TrackOperationService

_EVENT_FIELDS = (
    "timestamp_seconds",
    "x",
    "y",
    "width",
    "height",
    "confidence",
    "is_keyframe",
    "is_interpolated",
)


class SafeTrackIdentitySwapService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.responses = TrackOperationService(session)

    def _track(self, track_id: str) -> VideoTrack:
        track = self.session.get(VideoTrack, track_id)
        if track is None:
            raise NotFoundError("Video track not found")
        return track

    def _events_after(self, track_id: str, after_frame: int) -> list[VideoTrackEvent]:
        return list(
            self.session.scalars(
                select(VideoTrackEvent)
                .where(
                    VideoTrackEvent.track_id == track_id,
                    VideoTrackEvent.frame_index > after_frame,
                )
                .order_by(VideoTrackEvent.frame_index, VideoTrackEvent.id)
            )
        )

    @staticmethod
    def _copy_event_values(source: VideoTrackEvent) -> dict[str, object]:
        return {field: getattr(source, field) for field in _EVENT_FIELDS}

    @staticmethod
    def _apply_event_values(target: VideoTrackEvent, values: dict[str, object]) -> None:
        for field, value in values.items():
            setattr(target, field, value)

    def swap(
        self,
        video_id: str,
        request: TrackIdentitySwapRequest,
    ) -> TrackOperationResponse:
        if self.session.get(VideoAsset, video_id) is None:
            raise NotFoundError("Video not found")
        first = self._track(request.first_track_id)
        second = self._track(request.second_track_id)
        if first.video_id != video_id or second.video_id != video_id:
            raise ValidationError("Identity-swap tracks must belong to the selected video")
        if first.revision != request.expected_first_revision:
            raise ConflictError("First video track revision conflict")
        if second.revision != request.expected_second_revision:
            raise ConflictError("Second video track revision conflict")
        first_tail = self._events_after(first.id, request.after_frame)
        second_tail = self._events_after(second.id, request.after_frame)
        if not first_tail or not second_tail:
            raise ValidationError("Identity swap requires both tracks after the selected frame")

        first_by_frame = {event.frame_index: event for event in first_tail}
        second_by_frame = {event.frame_index: event for event in second_tail}
        shared_frames = set(first_by_frame) & set(second_by_frame)
        for frame_index in shared_frames:
            first_event = first_by_frame[frame_index]
            second_event = second_by_frame[frame_index]
            first_values = self._copy_event_values(first_event)
            second_values = self._copy_event_values(second_event)
            self._apply_event_values(first_event, second_values)
            self._apply_event_values(second_event, first_values)

        for frame_index in set(first_by_frame) - shared_frames:
            first_by_frame[frame_index].track_id = second.id
        for frame_index in set(second_by_frame) - shared_frames:
            second_by_frame[frame_index].track_id = first.id

        operation_id = str(uuid4())
        first.revision += 1
        second.revision += 1
        first.source_type = second.source_type = "human_identity_swap"
        first.provenance_json = {
            **dict(first.provenance_json or {}),
            "last_operation": {
                "operation": "identity_swap",
                "operation_id": operation_id,
                "other_track_id": second.id,
                "after_frame": request.after_frame,
            },
        }
        second.provenance_json = {
            **dict(second.provenance_json or {}),
            "last_operation": {
                "operation": "identity_swap",
                "operation_id": operation_id,
                "other_track_id": first.id,
                "after_frame": request.after_frame,
            },
        }
        first.updated_at = second.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(first)
        self.session.refresh(second)
        return TrackOperationResponse(
            operation="identity_swap",
            tracks=[self.responses._response(first), self.responses._response(second)],
            warnings=(
                [
                    f"Swapped event content in place for {len(shared_frames)} overlapping frames "
                    "to preserve unique track/frame keys."
                ]
                if shared_frames
                else []
            ),
        )

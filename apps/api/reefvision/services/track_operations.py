"""Revision-safe split, merge, and identity correction for video tracks."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import VideoAsset, VideoTrack, VideoTrackEvent
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.track_operations import (
    TrackIdentitySwapRequest,
    TrackMergeRequest,
    TrackOperationResponse,
    TrackSplitRequest,
)
from reefvision.schemas.videos import VideoTrackPointResponse, VideoTrackResponse


class TrackOperationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _track(self, track_id: str) -> VideoTrack:
        track = self.session.get(VideoTrack, track_id)
        if track is None:
            raise NotFoundError("Video track not found")
        return track

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _events(self, track_id: str) -> list[VideoTrackEvent]:
        return list(
            self.session.scalars(
                select(VideoTrackEvent)
                .where(VideoTrackEvent.track_id == track_id)
                .order_by(VideoTrackEvent.frame_index, VideoTrackEvent.id)
            )
        )

    def _response(self, track: VideoTrack) -> VideoTrackResponse:
        events = self._events(track.id)
        return VideoTrackResponse(
            id=track.id,
            video_id=track.video_id,
            label_class_id=track.label_class_id,
            track_key=track.track_key,
            source_type=track.source_type,
            raw_identity=track.raw_identity,
            frame_start=track.frame_start,
            frame_end=track.frame_end,
            status=track.status,
            confidence_mean=track.confidence_mean,
            color_hex=track.color_hex,
            notes=track.notes,
            interpolation_mode=track.interpolation_mode,
            revision=track.revision,
            provenance_json=dict(track.provenance_json or {}),
            created_at=track.created_at,
            updated_at=track.updated_at,
            point_count=len(events),
            keyframe_count=sum(event.is_keyframe for event in events),
            events=[
                VideoTrackPointResponse(
                    frame_index=event.frame_index,
                    timestamp_seconds=event.timestamp_seconds,
                    x=event.x,
                    y=event.y,
                    width=event.width,
                    height=event.height,
                    confidence=event.confidence,
                    is_keyframe=event.is_keyframe,
                    is_interpolated=event.is_interpolated,
                )
                for event in events
            ],
        )

    @staticmethod
    def _refresh_summary(track: VideoTrack, events: list[VideoTrackEvent]) -> None:
        if not events:
            raise ValidationError("A persisted video track must contain at least one event")
        track.frame_start = min(event.frame_index for event in events)
        track.frame_end = max(event.frame_index for event in events)
        confidences = [event.confidence for event in events if event.confidence is not None]
        track.confidence_mean = (
            sum(confidences) / len(confidences) if confidences else None
        )
        track.updated_at = datetime.now(UTC)

    def split(self, track_id: str, request: TrackSplitRequest) -> TrackOperationResponse:
        track = self._track(track_id)
        if track.revision != request.expected_revision:
            raise ConflictError("Video track revision conflict")
        events = self._events(track.id)
        before = [event for event in events if event.frame_index < request.split_frame]
        after = [event for event in events if event.frame_index >= request.split_frame]
        if not before or not after:
            raise ValidationError("Split frame must leave events on both resulting tracks")
        existing_keys = set(
            self.session.scalars(
                select(VideoTrack.track_key).where(VideoTrack.video_id == track.video_id)
            )
        )
        requested_key = (request.new_track_key or f"{track.track_key}-split").strip()
        candidate = requested_key
        suffix = 2
        while candidate in existing_keys:
            candidate = f"{requested_key}-{suffix}"
            suffix += 1
        new_track = VideoTrack(
            video_id=track.video_id,
            label_class_id=track.label_class_id,
            track_key=candidate,
            source_type="human_split",
            raw_identity=track.raw_identity,
            frame_start=after[0].frame_index,
            frame_end=after[-1].frame_index,
            status=track.status,
            confidence_mean=None,
            color_hex=track.color_hex,
            notes=track.notes,
            interpolation_mode=track.interpolation_mode,
            revision=1,
            provenance_json={
                "operation": "split",
                "source_track_id": track.id,
                "source_revision": track.revision,
                "split_frame": request.split_frame,
            },
        )
        self.session.add(new_track)
        self.session.flush()
        for event in after:
            event.track_id = new_track.id
        track.revision += 1
        track.source_type = "human_split"
        track.provenance_json = {
            **dict(track.provenance_json or {}),
            "last_operation": {
                "operation": "split",
                "new_track_id": new_track.id,
                "split_frame": request.split_frame,
            },
        }
        self._refresh_summary(track, before)
        self._refresh_summary(new_track, after)
        self.session.commit()
        self.session.refresh(track)
        self.session.refresh(new_track)
        return TrackOperationResponse(
            operation="split",
            tracks=[self._response(track), self._response(new_track)],
        )

    def merge(self, video_id: str, request: TrackMergeRequest) -> TrackOperationResponse:
        self._video(video_id)
        primary = self._track(request.primary_track_id)
        secondary = self._track(request.secondary_track_id)
        if primary.video_id != video_id or secondary.video_id != video_id:
            raise ValidationError("Merge tracks must belong to the selected video")
        if primary.revision != request.expected_primary_revision:
            raise ConflictError("Primary video track revision conflict")
        if secondary.revision != request.expected_secondary_revision:
            raise ConflictError("Secondary video track revision conflict")
        if (
            primary.label_class_id is not None
            and secondary.label_class_id is not None
            and primary.label_class_id != secondary.label_class_id
        ):
            raise ValidationError("Tracks with different classes cannot be merged")
        primary_events = self._events(primary.id)
        secondary_events = self._events(secondary.id)
        by_frame: dict[int, list[VideoTrackEvent]] = defaultdict(list)
        for event in [*primary_events, *secondary_events]:
            by_frame[event.frame_index].append(event)
        retained: list[VideoTrackEvent] = []
        conflicts = 0
        for frame_index in sorted(by_frame):
            choices = by_frame[frame_index]
            if len(choices) > 1:
                conflicts += 1
            if request.conflict_policy == "primary":
                selected = next(
                    (event for event in choices if event.track_id == primary.id),
                    choices[0],
                )
            else:
                selected = max(
                    choices,
                    key=lambda event: (
                        event.confidence if event.confidence is not None else -1,
                        event.is_keyframe,
                        event.track_id == primary.id,
                    ),
                )
            retained.append(selected)
            selected.track_id = primary.id
            for event in choices:
                if event is not selected:
                    self.session.delete(event)
        primary.label_class_id = primary.label_class_id or secondary.label_class_id
        primary.revision += 1
        primary.source_type = "human_merge"
        primary.provenance_json = {
            **dict(primary.provenance_json or {}),
            "last_operation": {
                "operation": "merge",
                "secondary_track_id": secondary.id,
                "secondary_revision": secondary.revision,
                "conflict_policy": request.conflict_policy,
                "frame_conflicts": conflicts,
            },
        }
        self._refresh_summary(primary, retained)
        deleted_id = secondary.id
        self.session.delete(secondary)
        self.session.commit()
        self.session.refresh(primary)
        warnings = (
            [f"Resolved {conflicts} overlapping frame events using {request.conflict_policy}."]
            if conflicts
            else []
        )
        return TrackOperationResponse(
            operation="merge",
            tracks=[self._response(primary)],
            deleted_track_ids=[deleted_id],
            warnings=warnings,
        )

    def swap_identities(
        self,
        video_id: str,
        request: TrackIdentitySwapRequest,
    ) -> TrackOperationResponse:
        self._video(video_id)
        first = self._track(request.first_track_id)
        second = self._track(request.second_track_id)
        if first.video_id != video_id or second.video_id != video_id:
            raise ValidationError("Identity-swap tracks must belong to the selected video")
        if first.revision != request.expected_first_revision:
            raise ConflictError("First video track revision conflict")
        if second.revision != request.expected_second_revision:
            raise ConflictError("Second video track revision conflict")
        first_events = self._events(first.id)
        second_events = self._events(second.id)
        first_tail = [event for event in first_events if event.frame_index > request.after_frame]
        second_tail = [event for event in second_events if event.frame_index > request.after_frame]
        if not first_tail or not second_tail:
            raise ValidationError("Identity swap requires both tracks after the selected frame")
        first_tail_frames = {event.frame_index for event in first_tail}
        second_tail_frames = {event.frame_index for event in second_tail}
        if first_tail_frames & second_tail_frames:
            # Swapping is still safe because every frame remains one event per track.
            pass
        for event in first_tail:
            event.track_id = second.id
        for event in second_tail:
            event.track_id = first.id
        first.revision += 1
        second.revision += 1
        first.source_type = second.source_type = "human_identity_swap"
        operation_id = str(uuid4())
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
        refreshed_first = self._events(first.id)
        refreshed_second = self._events(second.id)
        self._refresh_summary(first, refreshed_first)
        self._refresh_summary(second, refreshed_second)
        self.session.commit()
        self.session.refresh(first)
        self.session.refresh(second)
        return TrackOperationResponse(
            operation="identity_swap",
            tracks=[self._response(first), self._response(second)],
        )

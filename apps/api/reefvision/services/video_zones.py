"""Persistent revision-safe video analysis zones."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import VideoAsset, VideoZoneRecord
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.videos import (
    VideoZone,
    VideoZoneCreateRequest,
    VideoZoneResponse,
    VideoZoneUpdateRequest,
)


def zone_response(zone: VideoZoneRecord) -> VideoZoneResponse:
    return VideoZoneResponse.model_validate(zone, from_attributes=True)


class VideoZoneService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _zone(self, zone_id: str, *, include_deleted: bool = False) -> VideoZoneRecord:
        zone = self.session.get(VideoZoneRecord, zone_id)
        if zone is None or (zone.deleted_at is not None and not include_deleted):
            raise NotFoundError("Video zone not found")
        return zone

    @staticmethod
    def _validate_bounds(video: VideoAsset, zone: VideoZone) -> None:
        if zone.x_max > video.width_px or zone.y_max > video.height_px:
            raise ValidationError("Video zones must remain inside source-frame bounds")

    def _validate_name(
        self,
        video_id: str,
        name: str,
        *,
        exclude_id: str | None = None,
    ) -> None:
        zones = list(
            self.session.scalars(
                select(VideoZoneRecord).where(
                    VideoZoneRecord.video_id == video_id,
                    VideoZoneRecord.deleted_at.is_(None),
                )
            )
        )
        if any(item.id != exclude_id and item.name.casefold() == name.casefold() for item in zones):
            raise ConflictError("An active zone with this name already exists")

    def list(self, video_id: str) -> list[VideoZoneResponse]:
        self._video(video_id)
        zones = list(
            self.session.scalars(
                select(VideoZoneRecord)
                .where(
                    VideoZoneRecord.video_id == video_id,
                    VideoZoneRecord.deleted_at.is_(None),
                )
                .order_by(VideoZoneRecord.name, VideoZoneRecord.id)
            )
        )
        return [zone_response(item) for item in zones]

    def create(
        self,
        video_id: str,
        payload: VideoZoneCreateRequest,
    ) -> VideoZoneResponse:
        video = self._video(video_id)
        self._validate_bounds(video, payload)
        self._validate_name(video.id, payload.name)
        zone = VideoZoneRecord(video_id=video.id, **payload.model_dump(mode="python"))
        self.session.add(zone)
        self.session.commit()
        self.session.refresh(zone)
        return zone_response(zone)

    def update(
        self,
        zone_id: str,
        payload: VideoZoneUpdateRequest,
    ) -> VideoZoneResponse:
        zone = self._zone(zone_id)
        if zone.revision != payload.expected_revision:
            raise ConflictError(
                f"Video zone revision conflict: expected {payload.expected_revision}, "
                f"current revision is {zone.revision}"
            )
        video = self._video(zone.video_id)
        self._validate_bounds(video, payload)
        self._validate_name(video.id, payload.name, exclude_id=zone.id)
        zone.name = payload.name
        zone.x_min = float(payload.x_min)
        zone.y_min = float(payload.y_min)
        zone.x_max = float(payload.x_max)
        zone.y_max = float(payload.y_max)
        zone.revision += 1
        self.session.commit()
        self.session.refresh(zone)
        return zone_response(zone)

    def delete(self, zone_id: str, *, expected_revision: int) -> None:
        zone = self._zone(zone_id, include_deleted=True)
        if zone.deleted_at is not None:
            return
        if zone.revision != expected_revision:
            raise ConflictError(
                f"Video zone revision conflict: expected {expected_revision}, "
                f"current revision is {zone.revision}"
            )
        zone.deleted_at = datetime.now(UTC)
        zone.revision += 1
        self.session.commit()

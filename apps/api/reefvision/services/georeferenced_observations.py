"""Persistence and retrieval for geo-referenced video observations."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    GeoReferencedObservation as GeoReferencedObservationRecord,
)
from reefvision.db.models import VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.georeferenced_observation import (
    GeoReferencedObservation,
)
from reefvision.schemas.georeferenced_observation_api import (
    GeoReferencedObservationSummaryResponse,
)


class GeoReferencedObservationService:
    """Persist and query the canonical Task 10 observation contract."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _configuration_hash(
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        rendered = value.strip().lower()

        if len(rendered) != 64 or any(
            character not in "0123456789abcdef" for character in rendered
        ):
            raise ValidationError(
                "Georeferencing configuration hash must be a 64-character SHA-256 value"
            )

        return rendered

    def persist(
        self,
        observation: GeoReferencedObservation,
        *,
        configuration_hash: str | None = None,
    ) -> GeoReferencedObservationRecord:
        """Stage one canonical observation in the current transaction."""

        project_id = str(observation.project_id)
        video_id = str(observation.video_asset_id)

        track_id = str(observation.track_id) if observation.track_id is not None else None

        detection_id = (
            str(observation.detection_id) if observation.detection_id is not None else None
        )

        video = self.session.get(VideoAsset, video_id)

        if video is None:
            raise NotFoundError("Geo-referenced observation video was not found")

        if video.project_id != project_id:
            raise ValidationError("Geo-referenced observation project does not match video")

        if observation.frame_index >= video.frame_count:
            raise ValidationError("Geo-referenced observation frame exceeds video range")

        if (
            observation.frame_width_px != video.width_px
            or observation.frame_height_px != video.height_px
        ):
            raise ValidationError("Geo-referenced observation dimensions do not match video")

        if track_id is not None:
            track = self.session.get(VideoTrack, track_id)

            if track is None:
                raise NotFoundError("Geo-referenced observation track was not found")

            if track.video_id != video_id:
                raise ValidationError(
                    "Geo-referenced observation track does not belong to the video"
                )

        normalized_configuration_hash = self._configuration_hash(configuration_hash)

        is_stale = normalized_configuration_hash is None
        stale_reason = "configuration_not_recorded" if is_stale else None
        stale_at = datetime.now(UTC) if is_stale else None

        record = GeoReferencedObservationRecord(
            id=str(observation.id),
            project_id=project_id,
            video_id=video_id,
            track_id=track_id,
            detection_id=detection_id,
            schema_version=observation.schema_version,
            frame_index=observation.frame_index,
            frame_width_px=observation.frame_width_px,
            frame_height_px=observation.frame_height_px,
            bbox_x_min=observation.bbox.x_min,
            bbox_y_min=observation.bbox.y_min,
            bbox_x_max=observation.bbox.x_max,
            bbox_y_max=observation.bbox.y_max,
            representative_pixel_x=(observation.representative_pixel.x),
            representative_pixel_y=(observation.representative_pixel.y),
            representative_pixel_method=(observation.representative_pixel.method),
            frame_time_s=observation.timestamp.frame_time_s,
            latitude_deg=observation.location.latitude_deg,
            longitude_deg=observation.location.longitude_deg,
            crs=observation.location.crs,
            method_name=observation.method.name,
            method_version=observation.method.version,
            calibration_id=str(observation.calibration.calibration_id),
            calibration_version=(observation.calibration.calibration_version),
            calibration_checksum_sha256=(observation.calibration.checksum_sha256),
            telemetry_source_id=str(observation.telemetry.source_id),
            telemetry_source_type=(observation.telemetry.source_type),
            telemetry_sample_index=(observation.telemetry.sample_index),
            signed_time_delta_ms=(observation.telemetry.signed_time_delta_ms),
            uncertainty_available=(observation.uncertainty.available),
            configuration_hash=normalized_configuration_hash,
            is_stale=is_stale,
            stale_reason=stale_reason,
            stale_at=stale_at,
            payload_json=observation.model_dump(mode="json"),
            created_at=observation.created_at,
        )

        self.session.add(record)

        return record

    def get(
        self,
        observation_id: str,
    ) -> GeoReferencedObservationRecord:
        record = self.session.get(
            GeoReferencedObservationRecord,
            observation_id,
        )

        if record is None:
            raise NotFoundError("Geo-referenced observation not found")

        return record

    def list_for_video(
        self,
        video_id: str,
        *,
        track_id: str | None = None,
        frame_index: int | None = None,
    ) -> list[GeoReferencedObservationRecord]:
        video = self.session.get(VideoAsset, video_id)

        if video is None:
            raise NotFoundError("Video not found")

        if frame_index is not None and (frame_index < 0 or frame_index >= video.frame_count):
            raise ValidationError("Video frame is outside the source frame range")

        if track_id is not None:
            track = self.session.get(VideoTrack, track_id)

            if track is None or track.video_id != video_id:
                raise NotFoundError("Video track not found for video")

        statement = select(GeoReferencedObservationRecord).where(
            GeoReferencedObservationRecord.video_id == video_id
        )

        if track_id is not None:
            statement = statement.where(GeoReferencedObservationRecord.track_id == track_id)

        if frame_index is not None:
            statement = statement.where(GeoReferencedObservationRecord.frame_index == frame_index)

        statement = statement.order_by(
            GeoReferencedObservationRecord.frame_index,
            GeoReferencedObservationRecord.track_id,
            GeoReferencedObservationRecord.id,
        )

        return list(self.session.scalars(statement))

    def list_for_track(
        self,
        track_id: str,
    ) -> list[GeoReferencedObservationRecord]:
        track = self.session.get(VideoTrack, track_id)

        if track is None:
            raise NotFoundError("Video track not found")

        statement = (
            select(GeoReferencedObservationRecord)
            .where(GeoReferencedObservationRecord.track_id == track_id)
            .order_by(
                GeoReferencedObservationRecord.frame_index,
                GeoReferencedObservationRecord.id,
            )
        )

        return list(self.session.scalars(statement))

    def list_for_frame(
        self,
        video_id: str,
        frame_index: int,
    ) -> list[GeoReferencedObservationRecord]:
        return self.list_for_video(
            video_id,
            frame_index=frame_index,
        )

    @staticmethod
    def to_summary(
        record: GeoReferencedObservationRecord,
    ) -> GeoReferencedObservationSummaryResponse:
        return GeoReferencedObservationSummaryResponse(
            id=record.id,
            project_id=record.project_id,
            video_asset_id=record.video_id,
            track_id=record.track_id,
            detection_id=record.detection_id,
            frame_index=record.frame_index,
            frame_width_px=record.frame_width_px,
            frame_height_px=record.frame_height_px,
            frame_time_s=record.frame_time_s,
            bbox={
                "x_min": record.bbox_x_min,
                "y_min": record.bbox_y_min,
                "x_max": record.bbox_x_max,
                "y_max": record.bbox_y_max,
            },
            representative_pixel={
                "x": record.representative_pixel_x,
                "y": record.representative_pixel_y,
                "method": (record.representative_pixel_method),
            },
            location={
                "latitude_deg": record.latitude_deg,
                "longitude_deg": record.longitude_deg,
                "crs": record.crs,
            },
            uncertainty_available=(record.uncertainty_available),
            method_version=record.method_version,
            configuration_hash=record.configuration_hash,
            is_stale=record.is_stale,
            stale_reason=record.stale_reason,
            stale_at=record.stale_at,
            created_at=record.created_at,
        )

    @staticmethod
    def to_response(
        record: GeoReferencedObservationRecord,
    ) -> GeoReferencedObservation:
        """Reconstruct the complete canonical scientific payload."""

        payload = dict(record.payload_json)

        # Database identity/linkage fields are authoritative.
        payload.update(
            {
                "id": record.id,
                "project_id": record.project_id,
                "video_asset_id": record.video_id,
                "track_id": record.track_id,
                "detection_id": record.detection_id,
                "created_at": record.created_at,
            }
        )

        try:
            return GeoReferencedObservation.model_validate(payload)
        except PydanticValidationError as exc:
            raise ValidationError("Stored geo-referenced observation payload is invalid") from exc

    def delete_for_tracks(
        self,
        track_ids: Iterable[str],
    ) -> None:
        """Remove derived observations before replacing machine tracks."""

        ids = tuple(dict.fromkeys(track_ids))

        if not ids:
            return

        self.session.execute(
            delete(GeoReferencedObservationRecord).where(
                GeoReferencedObservationRecord.track_id.in_(ids)
            )
        )

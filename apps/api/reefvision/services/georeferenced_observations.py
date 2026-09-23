"""Persistence and retrieval for geo-referenced video observations."""

from __future__ import annotations

from collections.abc import Iterable

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


class GeoReferencedObservationService:
    """Persist and query the canonical Task 10 observation contract."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def persist(
        self,
        observation: GeoReferencedObservation,
    ) -> GeoReferencedObservationRecord:
        """Stage one canonical observation in the current transaction.

        This method deliberately does not commit. The caller owns the
        transaction so a tracking job can atomically persist tracks and their
        geographic observations together.
        """

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
            payload_json=observation.model_dump(mode="json"),
            created_at=observation.created_at,
        )

        self.session.add(record)

        return record

    def list_for_video(
        self,
        video_id: str,
    ) -> list[GeoReferencedObservationRecord]:
        video = self.session.get(VideoAsset, video_id)

        if video is None:
            raise NotFoundError("Video not found")

        statement = (
            select(GeoReferencedObservationRecord)
            .where(GeoReferencedObservationRecord.video_id == video_id)
            .order_by(
                GeoReferencedObservationRecord.frame_index,
                GeoReferencedObservationRecord.track_id,
                GeoReferencedObservationRecord.id,
            )
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
        video = self.session.get(VideoAsset, video_id)

        if video is None:
            raise NotFoundError("Video not found")

        if frame_index < 0 or frame_index >= video.frame_count:
            raise ValidationError("Video frame is outside the source frame range")

        statement = (
            select(GeoReferencedObservationRecord)
            .where(
                GeoReferencedObservationRecord.video_id == video_id,
                GeoReferencedObservationRecord.frame_index == frame_index,
            )
            .order_by(
                GeoReferencedObservationRecord.track_id,
                GeoReferencedObservationRecord.id,
            )
        )

        return list(self.session.scalars(statement))

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

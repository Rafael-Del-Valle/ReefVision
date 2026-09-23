"""Canonical production service for georeferencing a native video pixel."""

from __future__ import annotations

from math import isfinite

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.geospatial.calibration import CameraCalibration
from reefvision.geospatial.models import TelemetryProvenance
from reefvision.geospatial.projection import SurfaceReference, georeference_pixel
from reefvision.schemas.video_georeferencing import (
    VideoGeoreferenceFailureReason,
    VideoGeoreferenceResponse,
)
from reefvision.services.video_assets import VideoAssetService

DEFAULT_MAX_TELEMETRY_DELTA_S = 0.100


class VideoGeoreferencingService:
    """Resolve video/telemetry state and execute the shared projection contract.

    The project surface datum is resolved automatically. Camera calibration remains
    explicit until Task 5 wires persisted full calibration into this service.
    """

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.video_assets = VideoAssetService(session, settings)

    @staticmethod
    def _failure(
        *,
        video_id: str,
        project_id: str,
        frame_index: int,
        timestamp_seconds: float,
        pixel_x: float,
        pixel_y: float,
        reason: VideoGeoreferenceFailureReason,
        message: str,
        sync_error_s: float | None = None,
        telemetry_delta_s: float | None = None,
        telemetry_provenance: TelemetryProvenance | None = None,
    ) -> VideoGeoreferenceResponse:
        return VideoGeoreferenceResponse.model_validate(
            {
                "status": "failed",
                "video_id": video_id,
                "project_id": project_id,
                "frame_index": frame_index,
                "timestamp_seconds": timestamp_seconds,
                "pixel_x": pixel_x,
                "pixel_y": pixel_y,
                "sync_error_s": sync_error_s,
                "telemetry_delta_s": telemetry_delta_s,
                "telemetry_provenance": telemetry_provenance,
                "failure_reason": reason,
                "message": message,
            }
        )

    def georeference_point(
        self,
        video_id: str,
        *,
        frame_index: int,
        pixel_x: float,
        pixel_y: float,
        calibration: CameraCalibration,
        max_delta_s: float = DEFAULT_MAX_TELEMETRY_DELTA_S,
    ) -> VideoGeoreferenceResponse:
        video = self.video_assets.get_record(video_id)
        valid_nonnegative_frame = (
            isinstance(frame_index, int) and not isinstance(frame_index, bool) and frame_index >= 0
        )
        timestamp_seconds = frame_index / video.fps if valid_nonnegative_frame else 0.0

        if (
            isinstance(frame_index, bool)
            or not isinstance(frame_index, int)
            or frame_index < 0
            or frame_index >= video.frame_count
        ):
            return self._failure(
                video_id=video.id,
                project_id=video.project_id,
                frame_index=max(0, frame_index if isinstance(frame_index, int) else 0),
                timestamp_seconds=max(0.0, timestamp_seconds),
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                reason="frame_out_of_range",
                message="Video frame is outside the source frame range",
            )

        if not isfinite(max_delta_s) or max_delta_s < 0:
            raise ValidationError("Maximum telemetry delta must be finite and nonnegative")

        if (calibration.width_px, calibration.height_px) != (video.width_px, video.height_px):
            return self._failure(
                video_id=video.id,
                project_id=video.project_id,
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                reason="calibration_mismatch",
                message="Camera calibration dimensions do not match the source video",
            )

        project = self.session.get(Project, video.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        evidence = (project.georeference_height_evidence or "").strip()
        if not evidence:
            return self._failure(
                video_id=video.id,
                project_id=video.project_id,
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                reason="surface_reference_unavailable",
                message="Project georeferencing height datum evidence has not been configured",
            )
        surface = SurfaceReference(
            takeoff_height_above_surface_m=project.georeference_height_offset_m,
            evidence=evidence,
        )

        telemetry_source = self.video_assets.telemetry_source(video.id)
        if telemetry_source is None:
            return self._failure(
                video_id=video.id,
                project_id=video.project_id,
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                reason="telemetry_unavailable",
                message="Video has no usable telemetry source",
            )

        telemetry_match = telemetry_source.sample_for_frame(
            frame_index,
            video.fps,
            max_delta_s=max_delta_s,
        )
        if telemetry_match is None:
            return self._failure(
                video_id=video.id,
                project_id=video.project_id,
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                reason="telemetry_out_of_sync",
                message="No telemetry sample falls within the synchronization limit",
            )

        try:
            result = georeference_pixel(
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                telemetry=telemetry_match.sample,
                calibration=calibration,
                surface=surface,
            )
        except ValidationError as exc:
            return self._failure(
                video_id=video.id,
                project_id=video.project_id,
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                reason="projection_failed",
                message=str(exc),
                sync_error_s=telemetry_match.error_s,
                telemetry_delta_s=telemetry_match.delta_s,
                telemetry_provenance=telemetry_match.provenance,
            )

        return VideoGeoreferenceResponse(
            status="success",
            video_id=video.id,
            project_id=video.project_id,
            frame_index=frame_index,
            timestamp_seconds=timestamp_seconds,
            pixel_x=pixel_x,
            pixel_y=pixel_y,
            sync_error_s=telemetry_match.error_s,
            telemetry_delta_s=telemetry_match.delta_s,
            telemetry_provenance=telemetry_match.provenance,
            result=result,
        )

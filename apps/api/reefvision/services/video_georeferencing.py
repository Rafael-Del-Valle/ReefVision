"""Canonical production service for georeferencing a native video pixel."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isclose, isfinite
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Project, VideoAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.geospatial.mavic3t_camera import (
    MAVIC3T_DYNAMIC_CAMERA_VERSION,
    mavic3t_calibration_bundle_sha256,
    resolve_mavic3t_frame_camera,
)
from reefvision.geospatial.models import TelemetryProvenance
from reefvision.geospatial.projection import SurfaceReference, georeference_pixel
from reefvision.geospatial.synchronization import TelemetrySource
from reefvision.schemas.georeferenced_observation import (
    BoundingBoxPixels,
    CalibrationReference,
    CameraPose,
    GeographicLocation,
    GeoReferencedObservation,
    GeoreferencingMethod,
    GeoreferencingUncertainty,
    ObservationPose,
    ObservationTimestamp,
    PlatformPose,
    RepresentativePixel,
    TelemetryReference,
)
from reefvision.schemas.video_georeferencing import (
    VideoGeoreferenceFailureReason,
    VideoGeoreferenceResponse,
)
from reefvision.services.georeferencing_configuration import (
    GeoreferencingConfigurationError,
    GeoreferencingConfigurationSnapshot,
    georeferencing_configuration_hash,
)
from reefvision.services.video_assets import VideoAssetService
from reefvision.services.video_georeferencing_calibration import (
    VideoGeoreferencingCalibrationService,
)

DEFAULT_MAX_TELEMETRY_DELTA_S = 0.100


class VideoGeoreferencingService:
    """Resolve video/telemetry state and execute the shared projection contract.

    Project surface datum and the selected full camera calibration are resolved
    automatically from persisted ReefVision state.
    """

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.video_assets = VideoAssetService(session, settings)
        self.calibrations = VideoGeoreferencingCalibrationService(session)
        self._telemetry_source_cache: dict[str, TelemetrySource | None] = {}

    def _telemetry_source(
        self,
        video_id: str,
    ) -> TelemetrySource | None:
        """Load aligned telemetry once per service instance/video."""

        if video_id not in self._telemetry_source_cache:
            self._telemetry_source_cache[video_id] = self.video_assets.telemetry_source(video_id)

        return self._telemetry_source_cache[video_id]

    def configuration_hash(
        self,
        video_id: str,
        *,
        max_delta_s: float = DEFAULT_MAX_TELEMETRY_DELTA_S,
    ) -> str:
        """Fingerprint the persisted configuration used for projection."""
        if not isfinite(max_delta_s) or max_delta_s < 0:
            raise ValidationError("Maximum telemetry delta must be finite and nonnegative")

        video = self.video_assets.get_record(video_id)

        project = self.session.get(
            Project,
            video.project_id,
        )

        if project is None:
            raise NotFoundError("Project not found")

        calibration = self.calibrations.get(video.id)

        metadata = dict(video.metadata_json or {})

        def telemetry_identity(
            key: str,
        ) -> tuple[str | None, int | None]:
            raw_metadata = metadata.get(key)

            if not isinstance(raw_metadata, dict):
                return None, None

            raw_source_id = raw_metadata.get("source_path")

            source_id = str(raw_source_id).strip() if raw_source_id is not None else None

            if not source_id:
                source_id = None

            sample_count = raw_metadata.get("sample_count")

            if sample_count is not None and (
                isinstance(sample_count, bool) or not isinstance(sample_count, int)
            ):
                raise ValidationError(f"Stored {key} sample count is invalid")

            return source_id, sample_count

        srt_source_id, srt_sample_count = telemetry_identity("telemetry")

        (
            airdata_source_id,
            airdata_sample_count,
        ) = telemetry_identity("airdata_telemetry")

        raw_alignment = metadata.get("airdata_alignment")

        if raw_alignment is None:
            alignment: dict[str, object] = {}
        elif isinstance(raw_alignment, dict):
            alignment = raw_alignment
        else:
            raise ValidationError("Stored AirData alignment metadata is invalid")

        raw_offset = alignment.get(
            "time_offset_s",
            0.0,
        )

        if isinstance(raw_offset, bool) or not isinstance(
            raw_offset,
            (int, float),
        ):
            raise ValidationError("Stored AirData time offset is invalid")

        raw_evidence = alignment.get("evidence")

        alignment_evidence = str(raw_evidence) if raw_evidence is not None else None

        try:
            snapshot = GeoreferencingConfigurationSnapshot(
                video_id=str(video.id),
                video_sha256=str(video.sha256),
                video_fps=float(video.fps),
                srt_source_id=srt_source_id,
                srt_sample_count=srt_sample_count,
                airdata_source_id=airdata_source_id,
                airdata_sample_count=airdata_sample_count,
                airdata_time_offset_s=float(raw_offset),
                airdata_alignment_evidence=alignment_evidence,
                calibration_checksum_sha256=(calibration.checksum_sha256),
                calibration_revision=(calibration.calibration_revision),
                mavic3t_dynamic_camera_version=MAVIC3T_DYNAMIC_CAMERA_VERSION,
                mavic3t_calibration_bundle_sha256=(mavic3t_calibration_bundle_sha256()),
                project_height_offset_m=float(project.georeference_height_offset_m),
                project_height_evidence=(project.georeference_height_evidence or ""),
                max_telemetry_delta_s=max_delta_s,
            )

            return georeferencing_configuration_hash(snapshot)
        except GeoreferencingConfigurationError as exc:
            raise ValidationError(f"Georeferencing configuration is invalid: {exc}") from exc

    @staticmethod
    def _required_uuid(
        value: str | UUID,
        *,
        field_name: str,
    ) -> UUID:
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError(f"{field_name} must be a valid UUID") from exc

    @classmethod
    def _optional_uuid(
        cls,
        value: str | UUID | None,
        *,
        field_name: str,
    ) -> UUID | None:
        if value is None:
            return None
        return cls._required_uuid(value, field_name=field_name)

    @staticmethod
    def _representative_pixel_for_detection(
        *,
        bbox: BoundingBoxPixels,
        frame_width_px: int,
        frame_height_px: int,
        explicit_pixel: tuple[float, float] | list[float] | None,
    ) -> RepresentativePixel:
        """Apply Task 9: explicit representative point, else bbox center."""

        coordinates = (
            bbox.x_min,
            bbox.y_min,
            bbox.x_max,
            bbox.y_max,
        )

        if not all(isfinite(value) for value in coordinates):
            raise ValidationError("Detection bounding box must contain finite coordinates")

        if not (
            0.0 <= bbox.x_min < bbox.x_max <= frame_width_px
            and 0.0 <= bbox.y_min < bbox.y_max <= frame_height_px
        ):
            raise ValidationError("Detection bounding box must lie within the native video frame")

        if explicit_pixel is not None:
            if len(explicit_pixel) != 2:
                raise ValidationError("Explicit representative pixel must contain x and y")

            try:
                x = float(explicit_pixel[0])
                y = float(explicit_pixel[1])
            except (TypeError, ValueError) as exc:
                raise ValidationError("Explicit representative pixel must be numeric") from exc

            method = "explicit"

            if not (bbox.x_min <= x <= bbox.x_max and bbox.y_min <= y <= bbox.y_max):
                raise ValidationError(
                    "Explicit representative pixel must lie within the detection bounding box"
                )
        else:
            x = (bbox.x_min + bbox.x_max) / 2.0
            y = (bbox.y_min + bbox.y_max) / 2.0
            method = "bbox_center"

        if not (
            isfinite(x) and isfinite(y) and 0.0 <= x < frame_width_px and 0.0 <= y < frame_height_px
        ):
            raise ValidationError("Representative pixel must lie within the native video frame")

        return RepresentativePixel(
            x=x,
            y=y,
            method=method,
        )

    @staticmethod
    def _telemetry_reference_identity(
        video: VideoAsset,
        provenance: TelemetryProvenance | None,
    ) -> tuple[
        str,
        str,
        dict[str, str | float | None] | None,
    ]:
        """Resolve user-facing telemetry identity without losing merged provenance."""

        metadata = dict(video.metadata_json or {})

        field_provenance = provenance.model_dump(mode="json") if provenance is not None else None

        used_sources: set[str] = set()

        if provenance is not None:
            for source in (
                provenance.position_source,
                provenance.relative_altitude_source,
                provenance.gimbal_yaw_source,
                provenance.gimbal_pitch_source,
                provenance.gimbal_roll_source,
            ):
                if source is not None:
                    used_sources.add(source)

        def source_path(key: str) -> str | None:
            raw = metadata.get(key)
            if not isinstance(raw, dict):
                return None
            value = raw.get("source_path")
            if value is None:
                return None
            rendered = str(value).strip()
            return rendered or None

        if used_sources == {"dji_srt"}:
            source_type = "dji_srt"
            source_id = source_path("telemetry") or f"dji_srt:{video.id}"
        elif used_sources == {"airdata"}:
            source_type = "csv"
            source_id = source_path("airdata_telemetry") or f"airdata:{video.id}"
        elif len(used_sources) > 1:
            source_type = "other"

            paths = [
                path
                for path in (
                    source_path("airdata_telemetry"),
                    source_path("telemetry"),
                )
                if path is not None
            ]

            source_id = "merged:" + "|".join(paths) if paths else f"merged:{video.id}"
        else:
            telemetry_path = source_path("telemetry")
            airdata_path = source_path("airdata_telemetry")

            if telemetry_path is not None:
                source_type = "dji_srt"
                source_id = telemetry_path
            elif airdata_path is not None:
                source_type = "csv"
                source_id = airdata_path
            else:
                source_type = "other"
                source_id = f"telemetry:{video.id}"

        return source_type, source_id, field_provenance

    def georeference_detection(
        self,
        video_id: str,
        *,
        frame_index: int,
        bbox: BoundingBoxPixels,
        representative_pixel: (tuple[float, float] | list[float] | None) = None,
        detection_id: str | UUID | None = None,
        track_id: str | UUID | None = None,
        max_delta_s: float = DEFAULT_MAX_TELEMETRY_DELTA_S,
    ) -> GeoReferencedObservation:
        """Create one reproducible geographic observation from a detection.

        Representative-pixel policy:
        1. Explicit representative pixel, when supplied.
        2. Native-frame bounding-box center otherwise.

        Projection remains delegated to georeference_point(), so detection
        georeferencing cannot diverge from ReefVision's canonical production
        projection implementation.
        """

        video = self.video_assets.get_record(video_id)

        selected_pixel = self._representative_pixel_for_detection(
            bbox=bbox,
            frame_width_px=video.width_px,
            frame_height_px=video.height_px,
            explicit_pixel=representative_pixel,
        )

        response = self.georeference_point(
            video.id,
            frame_index=frame_index,
            pixel_x=selected_pixel.x,
            pixel_y=selected_pixel.y,
            max_delta_s=max_delta_s,
        )

        if response.status != "success" or response.result is None:
            reason = response.failure_reason or "unknown"
            message = response.message or "Unknown georeferencing failure"
            raise ValidationError(f"Detection georeferencing failed ({reason}): {message}")

        result = response.result

        # Resolve the same persisted calibration used by georeference_point().
        calibration_record = self.calibrations.get(video.id)

        # Re-resolve the synchronized sample so the observation stores the
        # actual pose and telemetry provenance used by projection.
        telemetry_source = self._telemetry_source(video.id)

        if telemetry_source is None:
            raise ValidationError(
                "Telemetry source became unavailable while constructing "
                "the geo-referenced observation"
            )

        telemetry_match = telemetry_source.sample_for_frame(
            frame_index,
            video.fps,
            max_delta_s=max_delta_s,
        )

        if telemetry_match is None:
            raise ValidationError(
                "Telemetry synchronization changed while constructing "
                "the geo-referenced observation"
            )

        sample = telemetry_match.sample

        observation_mavic3t_state = resolve_mavic3t_frame_camera(
            sample,
            pixel_x=selected_pixel.x,
            pixel_y=selected_pixel.y,
        )

        if observation_mavic3t_state is not None:
            observation_calibration = observation_mavic3t_state.calibration
            observation_camera_model = observation_mavic3t_state.camera_model
            observation_zoom_state = observation_mavic3t_state.digital_zoom_ratio
        else:
            observation_calibration = None
            observation_camera_model = calibration_record.camera_mode
            observation_zoom_state = calibration_record.digital_zoom_ratio

        if sample.latitude is None or sample.longitude is None:
            raise ValidationError("Successful georeferencing did not retain a GPS position")

        if (
            sample.gimbal_yaw_deg is None
            or sample.gimbal_pitch_deg is None
            or sample.gimbal_roll_deg is None
        ):
            raise ValidationError(
                "Successful georeferencing did not retain complete gimbal attitude"
            )

        (
            telemetry_source_type,
            telemetry_source_id,
            field_provenance,
        ) = self._telemetry_reference_identity(
            video,
            telemetry_match.provenance,
        )

        if sample.relative_altitude_m is not None:
            stored_altitude_m = sample.relative_altitude_m
            stored_altitude_datum = "relative_takeoff"
        elif sample.absolute_altitude_m is not None:
            stored_altitude_m = sample.absolute_altitude_m
            stored_altitude_datum = "absolute_telemetry"
        else:
            stored_altitude_m = None
            stored_altitude_datum = None

        telemetry_reference = TelemetryReference.model_validate(
            {
                "source_id": telemetry_source_id,
                "source_type": telemetry_source_type,
                "sample_index": sample.sample_index,
                "synchronization_method": "nearest",
                "telemetry_time_s": sample.time_s,
                "telemetry_utc": None,
                "signed_time_delta_ms": (telemetry_match.delta_s * 1000.0),
                "absolute_time_error_ms": (abs(telemetry_match.delta_s) * 1000.0),
                "within_sync_tolerance": (abs(telemetry_match.delta_s) <= max_delta_s),
                "sync_tolerance_ms": max_delta_s * 1000.0,
                "field_provenance": field_provenance,
            }
        )

        calibration_id = (
            result.calibration_source_id or f"sha256:{calibration_record.checksum_sha256}"
        )

        observation_calibration_version = str(calibration_record.calibration_revision)
        observation_calibration_checksum = calibration_record.checksum_sha256

        if observation_calibration is not None:
            dynamic_source_id = observation_calibration.source_id

            if (
                dynamic_source_id is None
                or not dynamic_source_id.startswith("sha256:")
                or len(dynamic_source_id) != 71
            ):
                raise ValidationError(
                    "Dynamic Mavic 3T calibration did not retain a SHA-256 source identity"
                )

            calibration_id = dynamic_source_id
            observation_calibration_version = MAVIC3T_DYNAMIC_CAMERA_VERSION
            observation_calibration_checksum = dynamic_source_id.removeprefix("sha256:")

        return GeoReferencedObservation(
            id=uuid4(),
            project_id=self._required_uuid(
                video.project_id,
                field_name="project_id",
            ),
            video_asset_id=self._required_uuid(
                video.id,
                field_name="video_asset_id",
            ),
            detection_id=self._optional_uuid(
                detection_id,
                field_name="detection_id",
            ),
            track_id=self._optional_uuid(
                track_id,
                field_name="track_id",
            ),
            frame_index=frame_index,
            frame_width_px=video.width_px,
            frame_height_px=video.height_px,
            bbox=bbox,
            representative_pixel=selected_pixel,
            timestamp=ObservationTimestamp(
                frame_time_s=frame_index / video.fps,
                utc=None,
                source="frame_index_fps",
                fps=video.fps,
            ),
            pose=ObservationPose(
                platform=PlatformPose(
                    latitude_deg=sample.latitude,
                    longitude_deg=sample.longitude,
                    altitude_m=stored_altitude_m,
                    altitude_datum=stored_altitude_datum,
                    height_above_surface_m=result.camera_height_m,
                    yaw_deg=sample.aircraft_yaw_deg,
                    pitch_deg=sample.aircraft_pitch_deg,
                    roll_deg=sample.aircraft_roll_deg,
                    heading_reference="unknown",
                ),
                camera=CameraPose(
                    yaw_deg=sample.gimbal_yaw_deg,
                    pitch_deg=sample.gimbal_pitch_deg,
                    roll_deg=sample.gimbal_roll_deg,
                    orientation_source="gimbal_telemetry",
                ),
            ),
            calibration=CalibrationReference(
                calibration_id=calibration_id,
                calibration_version=observation_calibration_version,
                checksum_sha256=observation_calibration_checksum,
                camera_model=observation_camera_model,
                image_width_px=(
                    observation_calibration.width_px
                    if observation_calibration is not None
                    else calibration_record.width_px
                ),
                image_height_px=(
                    observation_calibration.height_px
                    if observation_calibration is not None
                    else calibration_record.height_px
                ),
                focal_length_x_px=(
                    observation_calibration.fx_px
                    if observation_calibration is not None
                    else calibration_record.fx_px
                ),
                focal_length_y_px=(
                    observation_calibration.fy_px
                    if observation_calibration is not None
                    else calibration_record.fy_px
                ),
                principal_point_x_px=(
                    observation_calibration.cx_px
                    if observation_calibration is not None
                    else calibration_record.cx_px
                ),
                principal_point_y_px=(
                    observation_calibration.cy_px
                    if observation_calibration is not None
                    else calibration_record.cy_px
                ),
                distortion_model=(
                    "opencv_coefficients"
                    if (
                        observation_calibration.distortion_coefficients
                        if observation_calibration is not None
                        else calibration_record.distortion_coefficients
                    )
                    else "none"
                ),
                zoom_state=observation_zoom_state,
            ),
            telemetry=telemetry_reference,
            location=GeographicLocation(
                latitude_deg=result.latitude,
                longitude_deg=result.longitude,
            ),
            uncertainty=GeoreferencingUncertainty(
                available=False,
                method="not_estimated",
                reason_unavailable=("Formal uncertainty propagation is not yet implemented."),
            ),
            method=GeoreferencingMethod(
                version=result.method,
                surface_model="local_horizontal_plane",
                representative_pixel_policy_version="1.0.0",
                synchronization_version="nearest-frame-time-v1",
                pose_convention_version=("absolute-gimbal-ned-to-enu-v1"),
            ),
            created_at=datetime.now(UTC),
        )

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

        try:
            calibration = self.calibrations.camera_calibration(video.id)
        except NotFoundError:
            return self._failure(
                video_id=video.id,
                project_id=video.project_id,
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                reason="calibration_unavailable",
                message="Video georeferencing camera calibration has not been configured",
            )
        except ValidationError as exc:
            return self._failure(
                video_id=video.id,
                project_id=video.project_id,
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                reason="calibration_mismatch",
                message=str(exc),
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

        telemetry_source = self._telemetry_source(video.id)
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

        projection_calibration = calibration
        projection_pixel_x = pixel_x
        projection_pixel_y = pixel_y
        projection_telemetry = telemetry_match.sample

        try:
            mavic3t_state = resolve_mavic3t_frame_camera(
                telemetry_match.sample,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
            )
        except ValidationError as exc:
            return self._failure(
                video_id=video.id,
                project_id=video.project_id,
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                reason="calibration_mismatch",
                message=str(exc),
                sync_error_s=telemetry_match.error_s,
                telemetry_delta_s=telemetry_match.delta_s,
                telemetry_provenance=telemetry_match.provenance,
            )

        if mavic3t_state is not None:
            projection_calibration = mavic3t_state.calibration
            projection_pixel_x = mavic3t_state.native_pixel_x
            projection_pixel_y = mavic3t_state.native_pixel_y

            # Mavic 3T digital zoom has already been undone by mapping the
            # displayed pixel back into the native 1x optical-camera frame.
            #
            # georeference_pixel() still validates telemetry zoom against the
            # calibration, so provide a projection-only telemetry copy whose
            # zoom matches the selected base calibration. The original sample
            # remains untouched and is retained for observation provenance.
            projection_telemetry = telemetry_match.sample.model_copy(
                update={"digital_zoom_ratio": projection_calibration.digital_zoom_ratio}
            )
        else:
            telemetry_zoom = telemetry_match.sample.digital_zoom_ratio
            if telemetry_zoom is not None and not isclose(
                telemetry_zoom,
                calibration.digital_zoom_ratio,
                rel_tol=1e-6,
            ):
                return self._failure(
                    video_id=video.id,
                    project_id=video.project_id,
                    frame_index=frame_index,
                    timestamp_seconds=timestamp_seconds,
                    pixel_x=pixel_x,
                    pixel_y=pixel_y,
                    reason="calibration_zoom_mismatch",
                    message=(
                        "Telemetry zoom does not match the selected georeferencing calibration"
                    ),
                    sync_error_s=telemetry_match.error_s,
                    telemetry_delta_s=telemetry_match.delta_s,
                    telemetry_provenance=telemetry_match.provenance,
                )

        try:
            result = georeference_pixel(
                pixel_x=projection_pixel_x,
                pixel_y=projection_pixel_y,
                telemetry=projection_telemetry,
                calibration=projection_calibration,
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

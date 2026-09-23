"""Evaluate whether persisted video state is ready for production georeferencing."""

from __future__ import annotations

from math import isclose

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.video_georeferencing_readiness import (
    VideoGeoreferencingReadinessIssue,
    VideoGeoreferencingReadinessResponse,
    VideoGeoreferencingReadinessState,
)
from reefvision.services.video_assets import VideoAssetService
from reefvision.services.video_georeferencing import DEFAULT_MAX_TELEMETRY_DELTA_S
from reefvision.services.video_georeferencing_calibration import (
    VideoGeoreferencingCalibrationService,
)


class VideoGeoreferencingReadinessService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.video_assets = VideoAssetService(session, settings)
        self.calibrations = VideoGeoreferencingCalibrationService(session)

    @staticmethod
    def _sample_frames(frame_count: int) -> list[int]:
        if frame_count <= 1:
            return [0]
        candidates = [
            0,
            round((frame_count - 1) * 0.25),
            round((frame_count - 1) * 0.50),
            round((frame_count - 1) * 0.75),
            frame_count - 1,
        ]
        return list(dict.fromkeys(int(frame) for frame in candidates))

    @staticmethod
    def _primary_state(
        issues: list[VideoGeoreferencingReadinessIssue],
    ) -> VideoGeoreferencingReadinessState:
        priority: tuple[tuple[str, VideoGeoreferencingReadinessState], ...] = (
            ("missing_calibration", "missing_calibration"),
            ("invalid_calibration", "invalid_calibration"),
            ("missing_surface_reference", "missing_surface_reference"),
            ("missing_telemetry", "missing_telemetry"),
            ("invalid_airdata_alignment", "alignment_problem"),
            ("telemetry_out_of_sync", "synchronization_problem"),
            ("calibration_zoom_mismatch", "zoom_mismatch"),
        )
        issue_codes = {issue.code for issue in issues}
        for code, state in priority:
            if code in issue_codes:
                return state
        return "ready"

    def evaluate(
        self,
        video_id: str,
        *,
        max_delta_s: float = DEFAULT_MAX_TELEMETRY_DELTA_S,
    ) -> VideoGeoreferencingReadinessResponse:
        video = self.video_assets.get(video_id)
        project = self.session.get(Project, video.project_id)
        if project is None:
            raise NotFoundError("Project not found")

        issues: list[VideoGeoreferencingReadinessIssue] = []
        evidence = (project.georeference_height_evidence or "").strip()
        surface_reference_configured = bool(evidence)
        if not surface_reference_configured:
            issues.append(
                VideoGeoreferencingReadinessIssue(
                    code="missing_surface_reference",
                    message="Project georeferencing height datum evidence has not been configured",
                )
            )

        calibration_available = False
        calibration_valid = False
        calibration_checksum: str | None = None
        calibration = None
        try:
            calibration_record = self.calibrations.get(video.id)
            calibration_available = True
            calibration_checksum = calibration_record.checksum_sha256
            calibration = self.calibrations.camera_calibration(video.id)
            calibration_valid = True
        except NotFoundError:
            issues.append(
                VideoGeoreferencingReadinessIssue(
                    code="missing_calibration",
                    message="Video georeferencing camera calibration has not been configured",
                )
            )
        except ValidationError as exc:
            calibration_available = True
            issues.append(
                VideoGeoreferencingReadinessIssue(
                    code="invalid_calibration",
                    message=str(exc),
                )
            )

        srt_available = video.telemetry.available
        airdata_available = video.airdata_telemetry.available
        airdata_alignment_valid = True
        if (
            airdata_available
            and video.airdata_alignment.time_offset_s != 0
            and not (video.airdata_alignment.evidence or "").strip()
        ):
            airdata_alignment_valid = False
            issues.append(
                VideoGeoreferencingReadinessIssue(
                    code="invalid_airdata_alignment",
                    message="Nonzero AirData alignment offset requires evidence",
                )
            )

        if not srt_available and not airdata_available:
            issues.append(
                VideoGeoreferencingReadinessIssue(
                    code="missing_telemetry",
                    message="Video has no available SRT or AirData telemetry",
                )
            )

        sampled_frames = self._sample_frames(video.frame_count)
        synchronized = 0
        maximum_sync_error_s: float | None = None
        zoom_compatible: bool | None = None

        telemetry_source = None
        if (srt_available or airdata_available) and airdata_alignment_valid:
            telemetry_source = self.video_assets.telemetry_source(video.id)
            if telemetry_source is None:
                issues.append(
                    VideoGeoreferencingReadinessIssue(
                        code="missing_telemetry",
                        message="Configured telemetry could not be loaded",
                    )
                )

        zoom_checks: list[bool] = []
        if telemetry_source is not None:
            for frame_index in sampled_frames:
                match = telemetry_source.sample_for_frame(
                    frame_index,
                    video.fps,
                    max_delta_s=max_delta_s,
                )
                if match is None:
                    continue
                synchronized += 1
                maximum_sync_error_s = max(
                    maximum_sync_error_s or 0.0,
                    match.error_s,
                )
                if calibration is not None and match.sample.digital_zoom_ratio is not None:
                    zoom_checks.append(
                        isclose(
                            match.sample.digital_zoom_ratio,
                            calibration.digital_zoom_ratio,
                            rel_tol=1e-6,
                        )
                    )

            if synchronized != len(sampled_frames):
                issues.append(
                    VideoGeoreferencingReadinessIssue(
                        code="telemetry_out_of_sync",
                        message=(
                            "Telemetry did not synchronize within "
                            f"{max_delta_s:.3f} s for all representative video frames"
                        ),
                    )
                )

        if zoom_checks:
            zoom_compatible = all(zoom_checks)
            if not zoom_compatible:
                issues.append(
                    VideoGeoreferencingReadinessIssue(
                        code="calibration_zoom_mismatch",
                        message=(
                            "Telemetry zoom does not match the selected georeferencing calibration"
                        ),
                    )
                )

        state = self._primary_state(issues)
        return VideoGeoreferencingReadinessResponse(
            schema_version="video-georeferencing-readiness-0001",
            video_id=video.id,
            project_id=video.project_id,
            ready=state == "ready",
            state=state,
            issues=issues,
            srt_available=srt_available,
            airdata_available=airdata_available,
            airdata_alignment_valid=airdata_alignment_valid,
            surface_reference_configured=surface_reference_configured,
            calibration_available=calibration_available,
            calibration_valid=calibration_valid,
            calibration_checksum_sha256=calibration_checksum,
            sampled_frame_indices=sampled_frames,
            synchronized_frame_count=synchronized,
            sampled_frame_count=len(sampled_frames),
            maximum_sync_error_s=maximum_sync_error_s,
            zoom_compatible=zoom_compatible,
            max_allowed_sync_error_s=max_delta_s,
        )

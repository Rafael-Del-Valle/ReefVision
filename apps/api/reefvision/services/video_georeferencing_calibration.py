"""Persist and resolve the selected full camera calibration for georeferencing."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from reefvision.db.models import VideoAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.geospatial.calibration import CameraCalibration
from reefvision.schemas.video_georeferencing_calibration import (
    VideoGeoreferencingCalibrationResponse,
    VideoGeoreferencingCalibrationSetRequest,
)

GEOREREFERENCING_CALIBRATION_METADATA_KEY = "georeferencing_camera_calibration"
GEOREREFERENCING_CALIBRATION_SCHEMA_VERSION = "video-georeferencing-calibration-0001"


def _canonical_geometry(
    *,
    width_px: int,
    height_px: int,
    fx_px: float,
    fy_px: float,
    cx_px: float,
    cy_px: float,
    distortion_coefficients: tuple[float, ...],
    digital_zoom_ratio: float,
    camera_mode: str,
) -> dict[str, object]:
    return {
        "width_px": width_px,
        "height_px": height_px,
        "fx_px": fx_px,
        "fy_px": fy_px,
        "cx_px": cx_px,
        "cy_px": cy_px,
        "distortion_coefficients": list(distortion_coefficients),
        "digital_zoom_ratio": digital_zoom_ratio,
        "camera_mode": camera_mode,
    }


def _checksum(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class VideoGeoreferencingCalibrationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    @staticmethod
    def _response_from_video(video: VideoAsset) -> VideoGeoreferencingCalibrationResponse:
        metadata = dict(video.metadata_json or {})
        raw = metadata.get(GEOREREFERENCING_CALIBRATION_METADATA_KEY)
        if not isinstance(raw, dict):
            raise NotFoundError("Video georeferencing camera calibration has not been set")
        try:
            geometry = _canonical_geometry(
                width_px=int(raw["width_px"]),
                height_px=int(raw["height_px"]),
                fx_px=float(raw["fx_px"]),
                fy_px=float(raw["fy_px"]),
                cx_px=float(raw["cx_px"]),
                cy_px=float(raw["cy_px"]),
                distortion_coefficients=tuple(
                    float(value) for value in raw["distortion_coefficients"]
                ),
                digital_zoom_ratio=float(raw["digital_zoom_ratio"]),
                camera_mode=str(raw["camera_mode"]),
            )
            source = str(raw["source"])
            evidence = str(raw["evidence"])
            checksum = str(raw["checksum_sha256"])
            revision = int(raw["calibration_revision"])
            updated_at = datetime.fromisoformat(str(raw["calibration_updated_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Stored georeferencing camera calibration is invalid") from exc

        try:
            calibration = CameraCalibration.model_validate(
                {
                    "width_px": geometry["width_px"],
                    "height_px": geometry["height_px"],
                    "fx_px": geometry["fx_px"],
                    "fy_px": geometry["fy_px"],
                    "cx_px": geometry["cx_px"],
                    "cy_px": geometry["cy_px"],
                    "distortion_coefficients": geometry["distortion_coefficients"],
                    "digital_zoom_ratio": geometry["digital_zoom_ratio"],
                }
            )
        except ValueError as exc:
            raise ValidationError("Stored georeferencing camera calibration is invalid") from exc

        if (calibration.width_px, calibration.height_px) != (video.width_px, video.height_px):
            raise ValidationError(
                "Stored georeferencing calibration resolution does not match video"
            )
        if _checksum(geometry) != checksum:
            raise ValidationError("Stored georeferencing camera calibration checksum mismatch")
        if not source.strip() or not evidence.strip() or not str(geometry["camera_mode"]).strip():
            raise ValidationError("Stored georeferencing calibration provenance is incomplete")

        return VideoGeoreferencingCalibrationResponse(
            schema_version=GEOREREFERENCING_CALIBRATION_SCHEMA_VERSION,
            video_id=video.id,
            width_px=calibration.width_px,
            height_px=calibration.height_px,
            fx_px=calibration.fx_px,
            fy_px=calibration.fy_px,
            cx_px=calibration.cx_px,
            cy_px=calibration.cy_px,
            distortion_coefficients=tuple(float(v) for v in calibration.distortion_coefficients),
            digital_zoom_ratio=float(calibration.digital_zoom_ratio),
            camera_mode=str(geometry["camera_mode"]),
            source=source.strip(),
            evidence=evidence.strip(),
            checksum_sha256=checksum,
            calibration_revision=revision,
            calibration_updated_at=updated_at,
            video_revision=video.revision,
        )

    def set(
        self,
        video_id: str,
        payload: VideoGeoreferencingCalibrationSetRequest,
    ) -> VideoGeoreferencingCalibrationResponse:
        video = self._video(video_id)
        if (payload.width_px, payload.height_px) != (video.width_px, video.height_px):
            raise ValidationError("Georeferencing calibration resolution must match source video")

        geometry = _canonical_geometry(
            width_px=payload.width_px,
            height_px=payload.height_px,
            fx_px=float(payload.fx_px),
            fy_px=float(payload.fy_px),
            cx_px=float(payload.cx_px),
            cy_px=float(payload.cy_px),
            distortion_coefficients=tuple(float(v) for v in payload.distortion_coefficients),
            digital_zoom_ratio=float(payload.digital_zoom_ratio),
            camera_mode=payload.camera_mode,
        )
        metadata: dict[str, Any] = dict(video.metadata_json or {})
        previous = metadata.get(GEOREREFERENCING_CALIBRATION_METADATA_KEY)
        previous_revision = (
            int(previous.get("calibration_revision", 0)) if isinstance(previous, dict) else 0
        )
        metadata[GEOREREFERENCING_CALIBRATION_METADATA_KEY] = {
            "schema_version": GEOREREFERENCING_CALIBRATION_SCHEMA_VERSION,
            **geometry,
            "source": payload.source,
            "evidence": payload.evidence,
            "checksum_sha256": _checksum(geometry),
            "calibration_revision": previous_revision + 1,
            "calibration_updated_at": datetime.now(UTC).isoformat(),
        }
        video.metadata_json = metadata
        video.revision += 1
        self.session.commit()
        self.session.refresh(video)
        return self._response_from_video(video)

    def get(self, video_id: str) -> VideoGeoreferencingCalibrationResponse:
        return self._response_from_video(self._video(video_id))

    def clear(self, video_id: str) -> None:
        video = self._video(video_id)
        metadata = dict(video.metadata_json or {})
        if GEOREREFERENCING_CALIBRATION_METADATA_KEY not in metadata:
            return
        metadata.pop(GEOREREFERENCING_CALIBRATION_METADATA_KEY, None)
        video.metadata_json = metadata
        video.revision += 1
        self.session.commit()

    def camera_calibration(self, video_id: str) -> CameraCalibration:
        record = self.get(video_id)
        return CameraCalibration(
            width_px=record.width_px,
            height_px=record.height_px,
            fx_px=record.fx_px,
            fy_px=record.fy_px,
            cx_px=record.cx_px,
            cy_px=record.cy_px,
            distortion_coefficients=record.distortion_coefficients,
            digital_zoom_ratio=record.digital_zoom_ratio,
            source_id=f"sha256:{record.checksum_sha256}",
        )

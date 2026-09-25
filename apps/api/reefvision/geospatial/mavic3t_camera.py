from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.calibration import CameraCalibration
from reefvision.geospatial.models import TelemetrySample
from reefvision.storage.georeferencing import load_camera_calibration

# SRT focal_len on the Mavic 3T behaves as approximately:
#
#     optical-camera 35 mm equivalent focal length * digital zoom
#
# The two optical bases observed/documented for M3T RGB video are:
#
#     Wide ≈ 24 mm equivalent
#     Tele ≈ 161-162 mm equivalent
#
# These ranges deliberately leave a large unsupported gap rather than guessing.
WIDE_BASE_MIN_MM = 20.0
WIDE_BASE_MAX_MM = 35.0
TELE_BASE_MIN_MM = 140.0
TELE_BASE_MAX_MM = 180.0

MAVIC3T_DYNAMIC_CAMERA_VERSION = "mavic3t-focal-over-dzoom-centered-crop-v1"

_CALIBRATION_DIR = Path(__file__).resolve().parents[1] / "data" / "camera_calibrations"

_WIDE_FILENAME = "camera_calibration_DJIM3T_RGBwide.json"
_TELE_FILENAME = "camera_calibration_DJIM3T_RGBtele.json"


@dataclass(frozen=True)
class Mavic3TFrameCameraState:
    optical_camera: str
    base_focal_equivalent_mm: float
    digital_zoom_ratio: float
    calibration: CameraCalibration
    native_pixel_x: float
    native_pixel_y: float
    calibration_quality: str

    @property
    def camera_model(self) -> str:
        if self.optical_camera == "wide":
            return "DJI Mavic 3T RGB Wide"
        return "DJI Mavic 3T RGB Tele"


def mavic3t_calibration_bundle_sha256(
    calibration_dir: Path | None = None,
) -> str:
    """Fingerprint the exact Wide and Tele calibration resources."""

    root = calibration_dir or _CALIBRATION_DIR
    digest = hashlib.sha256()

    for filename in (_WIDE_FILENAME, _TELE_FILENAME):
        path = root / filename

        if not path.is_file():
            raise ValidationError(f"Mavic 3T calibration resource is unavailable: {path}")

        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\0")

    return digest.hexdigest()


def _camera_from_base_focal(base_focal_mm: float) -> tuple[str, str, str] | None:
    if WIDE_BASE_MIN_MM <= base_focal_mm <= WIDE_BASE_MAX_MM:
        return "wide", _WIDE_FILENAME, "measured"

    if TELE_BASE_MIN_MM <= base_focal_mm <= TELE_BASE_MAX_MM:
        return "tele", _TELE_FILENAME, "provisional"

    return None


def resolve_mavic3t_frame_camera(
    sample: TelemetrySample,
    *,
    pixel_x: float,
    pixel_y: float,
    calibration_dir: Path | None = None,
) -> Mavic3TFrameCameraState | None:
    """Resolve an M3T optical camera and undo its centered digital crop.

    Returns ``None`` when telemetry does not identify an M3T Wide/Tele optical
    regime. This preserves the existing persisted-calibration workflow for
    other drones/cameras.

    Digital zoom is modeled as a centered crop followed by rescaling to the
    recorded frame dimensions. The observed video pixel is therefore mapped
    back into the native 1x optical-camera coordinate system before physical
    lens distortion is applied by the existing OpenCV projection code.
    """

    focal = sample.focal_length_mm
    zoom = sample.digital_zoom_ratio

    if focal is None:
        return None

    if zoom is None:
        zoom = 1.0

    if zoom <= 0:
        raise ValidationError("Digital zoom ratio must be positive")

    base_focal = focal / zoom
    camera_spec = _camera_from_base_focal(base_focal)

    if camera_spec is None:
        return None

    optical_camera, filename, quality = camera_spec

    root = calibration_dir or _CALIBRATION_DIR
    path = root / filename

    if not path.is_file():
        raise ValidationError(f"Mavic 3T {optical_camera} calibration is unavailable: {path}")

    calibration = load_camera_calibration(path)

    # DJI digital zoom is represented as a centered crop/rescale. Convert the
    # displayed video coordinate back to the native 1x optical-camera pixel.
    native_x = calibration.cx_px + (pixel_x - calibration.cx_px) / zoom
    native_y = calibration.cy_px + (pixel_y - calibration.cy_px) / zoom

    return Mavic3TFrameCameraState(
        optical_camera=optical_camera,
        base_focal_equivalent_mm=base_focal,
        digital_zoom_ratio=zoom,
        calibration=calibration,
        native_pixel_x=native_x,
        native_pixel_y=native_y,
        calibration_quality=quality,
    )

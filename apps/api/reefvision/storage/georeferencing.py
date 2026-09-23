"""Read-only calibration resource loading. No dataset locations or downloads."""

import hashlib
import json
from pathlib import Path

from reefvision.domain.errors import ValidationError
from reefvision.geospatial.calibration import CameraCalibration, calibration_from_mapping


def load_camera_calibration(path: Path) -> CameraCalibration:
    try:
        with path.open("rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValidationError("Camera calibration exceeds 1 MiB")
        payload = json.loads(data.decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValidationError("Camera calibration must be a JSON object")
        return calibration_from_mapping(
            payload, source_id="sha256:" + hashlib.sha256(data).hexdigest()
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValidationError("Camera calibration is missing, unreadable, or malformed") from exc

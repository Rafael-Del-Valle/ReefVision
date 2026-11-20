"""Local inspection of supported encoded video files."""

from math import isfinite
from pathlib import Path

import cv2

from reefvision.domain.errors import ValidationError

SUPPORTED_VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}


def inspect_video(path: Path) -> dict[str, float | int]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValidationError("Uploaded video could not be opened")
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
    finally:
        capture.release()
    if width <= 0 or height <= 0 or frame_count <= 0 or not isfinite(fps) or fps <= 0:
        raise ValidationError("Uploaded video metadata is incomplete or unsupported")
    return {
        "width_px": width,
        "height_px": height,
        "frame_count": frame_count,
        "fps": fps,
        "duration_seconds": frame_count / fps,
    }

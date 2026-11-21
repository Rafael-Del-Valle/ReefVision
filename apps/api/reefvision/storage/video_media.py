"""Local inspection of supported encoded video files."""

from collections.abc import Callable
from math import isfinite
from pathlib import Path

import cv2
from PIL import Image

from reefvision.db.models.video_asset import VideoAsset
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


def load_exact_video_frames(
    video_path: Path,
    video: VideoAsset,
    frame_indices: list[int],
    *,
    cancellation_check: Callable[[], None] | None = None,
) -> dict[int, Image.Image]:
    targets = sorted(set(frame_indices))
    if not targets or targets[0] < 0 or targets[-1] >= video.frame_count:
        raise ValidationError("Evaluation contains an invalid source video frame")
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise ValidationError("Could not open the managed evaluation source video")
    frames: dict[int, Image.Image] = {}
    target_set = set(targets)
    try:
        for frame_index in range(targets[-1] + 1):
            if cancellation_check is not None:
                cancellation_check()
            ok, frame = capture.read()
            if not ok or frame is None:
                raise ValidationError(f"Evaluation video ended before frozen frame {targets[-1]}")
            if frame_index in target_set:
                height, width = frame.shape[:2]
                if (width, height) != (video.width_px, video.height_px):
                    raise ValidationError(
                        "Decoded evaluation frame dimensions differ from frozen video metadata"
                    )
                frames[frame_index] = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()
    return frames

"""One bounded frame from the explicitly selected local OpenCV camera."""

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from multiprocessing import get_context
from pathlib import Path
from sys import platform
from time import monotonic

from reefvision.storage.acquisition_source import read_camera_frame, spool_camera_frame

CAMERA_TIMEOUT_SECONDS = 4.0


class CameraUnavailable(RuntimeError):
    """The chosen local device did not return a supported frame."""


@dataclass(frozen=True)
class LocalCameraFrame:
    png: bytes
    received_at_utc: datetime
    read_elapsed_seconds: float


def _grab_once(camera_index: int, directory: Path) -> None:
    import cv2

    backend = cv2.CAP_DSHOW if platform == "win32" else cv2.CAP_ANY
    camera = cv2.VideoCapture(camera_index, backend)
    try:
        if not camera.isOpened():
            return
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        start = monotonic()
        ok, frame = camera.read()
        elapsed = monotonic() - start
        received = datetime.now(UTC)
        if not ok or frame is None:
            return
        height, width = frame.shape[:2]
        if not (0 < width <= 1920 and 0 < height <= 1080):
            return
        written, encoded = cv2.imencode(".png", frame)
        if written:
            spool_camera_frame(
                directory,
                encoded.tobytes(),
                {"received_at_utc": received.isoformat(), "read_elapsed_seconds": elapsed},
            )
    finally:
        camera.release()


def capture_local_camera(camera_index: int, directory: Path) -> LocalCameraFrame:
    """Terminate the isolated reader if the native driver stalls while opening or reading."""
    if not 0 <= camera_index <= 15:
        raise CameraUnavailable("The selected local camera index is outside the supported range")
    process = get_context("spawn").Process(target=_grab_once, args=(camera_index, directory))
    try:
        deadline = monotonic() + CAMERA_TIMEOUT_SECONDS
        process.start()
        process.join(max(deadline - monotonic(), 0))
        if process.is_alive():
            raise CameraUnavailable(
                "The selected local camera timed out opening or reading a frame"
            )
        if process.exitcode != 0:
            raise CameraUnavailable("The selected local camera reader exited without a frame")
        png, summary = read_camera_frame(directory)
        received = datetime.fromisoformat(str(summary["received_at_utc"]))
        elapsed = float(summary["read_elapsed_seconds"])
        if received.utcoffset() is None or not isfinite(elapsed) or elapsed < 0:
            raise ValueError("Local camera clock evidence is incomplete")
        return LocalCameraFrame(png, received.astimezone(UTC), elapsed)
    except (OSError, ValueError) as exc:
        raise CameraUnavailable(
            "The selected local camera is unavailable or returned an unsupported frame"
        ) from exc
    finally:
        if process.pid is not None and process.is_alive():
            process.kill()
            process.join(1)
        if not process.is_alive():
            process.close()

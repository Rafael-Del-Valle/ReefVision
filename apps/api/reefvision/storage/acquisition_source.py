"""Bound transient acquisition data before publishing through field storage."""

import json
from pathlib import Path

MAX_CAMERA_FRAME_BYTES = 16 * 1024**2
MAX_RECORDED_ORIGINAL_BYTES = 512 * 1024**2


def spool_camera_frame(directory: Path, frame: bytes, summary: dict[str, str | float]) -> None:
    if not 0 < len(frame) <= MAX_CAMERA_FRAME_BYTES:
        raise ValueError("Invalid local frame size")
    (directory / "frame.png").write_bytes(frame)
    (directory / "frame.json").write_text(json.dumps(summary), encoding="utf-8")


def read_camera_frame(directory: Path) -> tuple[bytes, dict[str, str | float]]:
    with (directory / "frame.png").open("rb") as stream:
        frame = stream.read(MAX_CAMERA_FRAME_BYTES + 1)
    if not 0 < len(frame) <= MAX_CAMERA_FRAME_BYTES:
        raise ValueError("Invalid local frame size")
    with (directory / "frame.json").open("r", encoding="utf-8") as stream:
        summary = json.loads(stream.read(1025))
    if not isinstance(summary, dict) or set(summary) != {"received_at_utc", "read_elapsed_seconds"}:
        raise ValueError("Invalid local frame metadata")
    return frame, summary

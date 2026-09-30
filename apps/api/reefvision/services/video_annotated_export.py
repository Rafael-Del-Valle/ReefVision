"""Shared annotated-video rendering for tracking review exports."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import cv2
import imageio_ffmpeg

AnnotatedVideoPreset = Literal["clean_tracking", "full_review"]

OVERLAY_FIELDS = (
    "boxes",
    "track_ids",
    "class_labels",
    "confidence",
    "trails",
    "frame_time",
    "counters",
)


@dataclass(frozen=True)
class ResolvedOverlayOptions:
    boxes: bool
    track_ids: bool
    class_labels: bool
    confidence: bool
    trails: bool
    frame_time: bool
    counters: bool

    def as_dict(self) -> dict[str, bool]:
        return {field: bool(getattr(self, field)) for field in OVERLAY_FIELDS}


@dataclass(frozen=True)
class RenderObservation:
    frame: int
    track_key: str
    track_number: int
    label: str
    confidence: float | None
    bbox: tuple[float, float, float, float]
    display_color: str
    keypoints: tuple[tuple[float, float, float], ...] | None = None


class AnnotatedVideoExportCancelled(RuntimeError):
    """Raised when an annotated-video export is cancelled."""


PRESET_DEFAULTS: dict[AnnotatedVideoPreset, dict[str, bool]] = {
    "clean_tracking": {
        "boxes": True,
        "track_ids": True,
        "class_labels": True,
        "confidence": True,
        "trails": False,
        "frame_time": False,
        "counters": False,
    },
    "full_review": {
        "boxes": True,
        "track_ids": True,
        "class_labels": True,
        "confidence": True,
        "trails": True,
        "frame_time": True,
        "counters": True,
    },
}


def resolve_overlay_options(
    preset: AnnotatedVideoPreset,
    overrides: dict[str, object] | None,
) -> ResolvedOverlayOptions:
    resolved = dict(PRESET_DEFAULTS[preset])
    for field in OVERLAY_FIELDS:
        value = (overrides or {}).get(field)
        if isinstance(value, bool):
            resolved[field] = value
    return ResolvedOverlayOptions(**resolved)


def _hex_to_bgr(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return (255, 170, 0)
    try:
        red = int(text[0:2], 16)
        green = int(text[2:4], 16)
        blue = int(text[4:6], 16)
    except ValueError:
        return (255, 170, 0)
    return (blue, green, red)


def _timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes, remainder = divmod(seconds, 60.0)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remainder:05.2f}"
    return f"{minutes:02d}:{remainder:05.2f}"


def _draw_label(
    frame: Any,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int],
    *,
    font_scale: float,
    thickness: int,
) -> None:
    if not text:
        return
    height, width = frame.shape[:2]
    (text_width, text_height), baseline = cv2.getTextSize(
        text,
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        thickness,
    )
    x = max(0, min(x, max(0, width - text_width - 8)))
    baseline_y = max(
        text_height + baseline + 6,
        min(y, max(text_height + baseline + 6, height - 4)),
    )
    top = max(0, baseline_y - text_height - baseline - 6)
    right = min(width - 1, x + text_width + 8)
    bottom = min(height - 1, baseline_y + 4)
    label_fill = (245, 245, 245)
    label_text = (0, 0, 0)
    border_thickness = max(1, thickness)

    cv2.rectangle(
        frame,
        (x, top),
        (right, bottom),
        label_fill,
        cv2.FILLED,
    )
    cv2.rectangle(
        frame,
        (x, top),
        (right, bottom),
        color,
        border_thickness,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        text,
        (x + 4, baseline_y - baseline),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        label_text,
        thickness,
        cv2.LINE_AA,
    )


class _FfmpegH264Writer:
    """Small adapter around imageio-ffmpeg's streaming writer."""

    def __init__(
        self,
        destination_path: Path,
        *,
        width_px: int,
        height_px: int,
        fps: float,
    ) -> None:
        if width_px % 2 or height_px % 2:
            raise RuntimeError(
                "H.264 yuv420p export requires even video dimensions; "
                f"received {width_px}x{height_px}"
            )

        self._writer = imageio_ffmpeg.write_frames(
            str(destination_path),
            (int(width_px), int(height_px)),
            pix_fmt_in="bgr24",
            pix_fmt_out="yuv420p",
            fps=float(fps),
            quality=None,
            bitrate=None,
            codec="libx264",
            macro_block_size=1,
            ffmpeg_log_level="warning",
            output_params=[
                "-crf",
                "20",
                "-preset",
                "fast",
                "-movflags",
                "+faststart",
            ],
        )
        self._closed = False
        self._writer.send(None)

    def write(self, frame: object) -> None:
        if self._closed:
            raise RuntimeError("H.264 writer is already closed")
        self._writer.send(frame)

    def release(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._writer.close()


def _open_h264_writer(
    destination_path: Path,
    *,
    width_px: int,
    height_px: int,
    fps: float,
) -> _FfmpegH264Writer:
    """Open a controlled libx264 MP4 writer."""

    return _FfmpegH264Writer(
        destination_path,
        width_px=width_px,
        height_px=height_px,
        fps=fps,
    )


def verify_annotated_video(
    path: Path,
    *,
    expected_width: int,
    expected_height: int,
    expected_fps: float,
    expected_frames: int,
) -> dict[str, object]:
    """Validate the completed MP4 before an export may be marked successful."""

    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("Annotated-video export file was not created")

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError("Annotated-video export could not be reopened")

    try:
        actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = float(capture.get(cv2.CAP_PROP_FPS))
        actual_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

        fourcc_value = int(capture.get(cv2.CAP_PROP_FOURCC))
        fourcc = "".join(chr((fourcc_value >> (8 * index)) & 0xFF) for index in range(4))

        if actual_width != expected_width or actual_height != expected_height:
            raise RuntimeError(
                "Annotated-video export resolution mismatch: "
                f"expected {expected_width}x{expected_height}, "
                f"got {actual_width}x{actual_height}"
            )

        if abs(actual_fps - expected_fps) > 0.05:
            raise RuntimeError(
                "Annotated-video export FPS mismatch: "
                f"expected {expected_fps:.6f}, got {actual_fps:.6f}"
            )

        if actual_frames != expected_frames:
            raise RuntimeError(
                "Annotated-video export frame-count mismatch: "
                f"expected {expected_frames}, got {actual_frames}"
            )

        if fourcc.strip().lower() not in {"h264", "avc1"}:
            raise RuntimeError(
                f"Annotated-video export codec mismatch: expected H.264, got {fourcc!r}"
            )

        if expected_frames > 0:
            capture.set(
                cv2.CAP_PROP_POS_FRAMES,
                float(expected_frames - 1),
            )
            ok, _ = capture.read()
            if not ok:
                raise RuntimeError("Annotated-video export final frame could not be decoded")

        return {
            "codec": "h264",
            "container": "mp4",
            "fourcc": fourcc,
            "encoder_backend": "imageio-ffmpeg/libx264",
            "crf": 20,
            "encoder_preset": "fast",
            "pixel_format": "yuv420p",
            "verified_frame_count": actual_frames,
            "verified_fps": actual_fps,
            "verified_width_px": actual_width,
            "verified_height_px": actual_height,
        }
    finally:
        capture.release()


def render_annotated_video(
    source_path: Path,
    destination_path: Path,
    *,
    width_px: int,
    height_px: int,
    fps: float,
    frame_count: int,
    observations: list[RenderObservation],
    options: ResolvedOverlayOptions,
    trail_length: int,
    on_progress: Callable[[int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> int:
    """Render stored tracking observations onto a new MP4.

    Boxes are drawn only on frames with stored observations. Trails use prior
    observed centers but do not synthesize detections on missing frames.
    """

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open source video: {source_path}")

    try:
        writer = _open_h264_writer(
            destination_path,
            width_px=width_px,
            height_px=height_px,
            fps=fps,
        )
    except Exception:
        capture.release()
        raise

    by_frame: dict[int, list[RenderObservation]] = defaultdict(list)
    for observation in observations:
        if 0 <= observation.frame < frame_count:
            by_frame[observation.frame].append(observation)

    trails: dict[str, deque[tuple[int, int]]] = defaultdict(
        lambda: deque(maxlen=max(2, trail_length))
    )
    line_thickness = max(2, round(min(width_px, height_px) / 540))
    text_thickness = max(1, line_thickness // 2)
    font_scale = max(0.45, min(width_px, height_px) / 1200.0)
    processed = 0

    try:
        for frame_index in range(frame_count):
            if should_cancel is not None and should_cancel():
                raise AnnotatedVideoExportCancelled("Annotated video export was cancelled")

            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(
                    f"Source video ended at frame {frame_index} "
                    f"before expected frame count {frame_count}"
                )

            frame_observations = by_frame.get(frame_index, [])
            active_tracks: set[str] = set()

            for observation in frame_observations:
                x, y, box_width, box_height = observation.bbox
                left = max(0, min(width_px - 1, round(x)))
                top = max(0, min(height_px - 1, round(y)))
                right = max(left + 1, min(width_px - 1, round(x + box_width)))
                bottom = max(top + 1, min(height_px - 1, round(y + box_height)))
                center = ((left + right) // 2, (top + bottom) // 2)
                color = _hex_to_bgr(observation.display_color)
                active_tracks.add(observation.track_key)
                trails[observation.track_key].append(center)

                if options.trails:
                    points = list(trails[observation.track_key])
                    for first, second in pairwise(points):
                        cv2.line(
                            frame,
                            first,
                            second,
                            color,
                            max(1, line_thickness - 1),
                            cv2.LINE_AA,
                        )

                if options.boxes:
                    cv2.rectangle(
                        frame,
                        (left, top),
                        (right, bottom),
                        color,
                        line_thickness,
                    )

                for keypoint_x, keypoint_y, keypoint_confidence in observation.keypoints or ():
                    if keypoint_confidence <= 0:
                        continue
                    point_x = max(0, min(width_px - 1, round(keypoint_x)))
                    point_y = max(0, min(height_px - 1, round(keypoint_y)))
                    cv2.circle(
                        frame,
                        (point_x, point_y),
                        max(2, line_thickness + 1),
                        color,
                        cv2.FILLED,
                        cv2.LINE_AA,
                    )

                label_parts: list[str] = []
                if options.track_ids:
                    label_parts.append(f"#{observation.track_number}")
                if options.class_labels:
                    label_parts.append(observation.label)
                if options.confidence and observation.confidence is not None:
                    label_parts.append(f"{observation.confidence:.2f}")

                _draw_label(
                    frame,
                    " ".join(label_parts),
                    left,
                    max(0, top - 6),
                    color,
                    font_scale=font_scale,
                    thickness=text_thickness,
                )

            if options.frame_time:
                _draw_label(
                    frame,
                    f"Frame {frame_index + 1}/{frame_count}  {_timestamp(frame_index / fps)}",
                    12,
                    12 + round(34 * font_scale),
                    (32, 32, 32),
                    font_scale=font_scale,
                    thickness=text_thickness,
                )

            if options.counters:
                _draw_label(
                    frame,
                    f"Observations {len(frame_observations)}  Active tracks {len(active_tracks)}",
                    12,
                    height_px - 18,
                    (32, 32, 32),
                    font_scale=font_scale,
                    thickness=text_thickness,
                )

            writer.write(frame)
            processed = frame_index + 1
            if on_progress is not None:
                on_progress(processed)
    finally:
        writer.release()
        capture.release()

    return processed

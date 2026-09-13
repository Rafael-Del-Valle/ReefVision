"""Shared annotated-video rendering for tracking review exports."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import cv2

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

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(
        str(destination_path),
        fourcc,
        float(fps),
        (int(width_px), int(height_px)),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError("OpenCV could not initialize MP4 video encoding")

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

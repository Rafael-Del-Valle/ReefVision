# Render scientifically traceable preview frames from persisted metric-depth stacks.

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job, VideoAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.storage.projects import resolve_managed_project_path

JOB_TYPE = "video_metric_depth_3d"
DEPTH_TIER = "model_estimated_metric"
PREVIEW_SCALING = "global_positive_depth_percentile_2_98"


@dataclass(frozen=True)
class MetricDepthPreview:
    png_bytes: bytes
    frame: int
    display_min_m: float
    display_max_m: float
    scaling: str
    depth_tier: str


def metric_depth_display_range(depths: NDArray[np.floating[Any]]) -> tuple[float, float]:
    values = np.asarray(depths, dtype=np.float32)
    valid = values[np.isfinite(values) & (values > 0)]
    if valid.size == 0:
        raise ValidationError("Metric depth stack contains no finite positive depth values")
    lower, upper = np.percentile(valid, [2.0, 98.0])
    lower_value = float(lower)
    upper_value = float(upper)
    if not np.isfinite(lower_value) or not np.isfinite(upper_value):
        raise ValidationError("Metric depth preview range is not finite")
    if upper_value <= lower_value:
        padding = max(abs(lower_value) * 0.01, 0.01)
        lower_value = max(0.0, lower_value - padding)
        upper_value = upper_value + padding
    return lower_value, upper_value


def _load_depth_stack(path: Path) -> NDArray[np.float32]:
    if not path.is_file():
        raise NotFoundError("Scientific 3D metric-depth stack is missing")
    try:
        with np.load(path, allow_pickle=False) as payload:
            if "depths" not in payload:
                raise ValidationError(
                    "Scientific 3D metric-depth stack is missing the depths array"
                )
            depths = np.asarray(payload["depths"], dtype=np.float32)
    except (OSError, ValueError) as exc:
        raise ValidationError("Scientific 3D metric-depth stack could not be read") from exc
    if depths.ndim != 3 or depths.shape[0] < 1:
        raise ValidationError("Scientific 3D metric-depth stack must be frame x height x width")
    return depths


def _colorize_depth(
    depth: NDArray[np.floating[Any]],
    *,
    display_min_m: float,
    display_max_m: float,
) -> NDArray[np.uint8]:
    values = np.asarray(depth, dtype=np.float32)
    valid = np.isfinite(values) & (values > 0)
    denominator = display_max_m - display_min_m
    if denominator <= 0:
        raise ValidationError("Scientific 3D preview display range is invalid")

    normalized = np.clip(
        (values - display_min_m) / denominator,
        0.0,
        1.0,
    )
    anchors = np.asarray(
        [
            [25, 45, 170],
            [0, 175, 235],
            [55, 205, 120],
            [245, 215, 55],
            [210, 35, 35],
        ],
        dtype=np.float32,
    )
    scaled = normalized * float(len(anchors) - 1)
    lower_index = np.floor(scaled).astype(np.int32)
    upper_index = np.clip(lower_index + 1, 0, len(anchors) - 1)
    fraction = (scaled - lower_index)[..., None]
    rgb = anchors[lower_index] * (1.0 - fraction) + anchors[upper_index] * fraction
    rgb_uint8: NDArray[np.uint8] = np.asarray(
        np.clip(rgb, 0, 255),
        dtype=np.uint8,
    )
    rgb_uint8[~valid] = np.asarray([18, 18, 18], dtype=np.uint8)
    return rgb_uint8


class VideoMetricDepthPreviewService:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings

    def _validated_result(
        self,
        video_id: str,
        job_id: str,
    ) -> tuple[dict[str, Any], Path]:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")

        job = self.session.get(Job, job_id)
        if job is None or job.job_type != JOB_TYPE or job.project_id != video.project_id:
            raise NotFoundError("Scientific 3D job not found for this video")
        if job.status != "succeeded":
            raise ValidationError("Scientific 3D depth preview requires a succeeded job")

        result = dict(job.result_json or {})
        if result.get("video_id") != video_id:
            raise ValidationError("Scientific 3D job result does not belong to this video")
        if result.get("depth_tier") != DEPTH_TIER:
            raise ValidationError(
                "Scientific 3D preview only supports model-estimated metric depth"
            )
        relative_path = result.get("depth_stack_path")
        if not isinstance(relative_path, str) or not relative_path:
            raise ValidationError("Scientific 3D job does not record a metric-depth stack")
        depth_path = resolve_managed_project_path(
            self.settings,
            relative_path,
        )
        return result, depth_path

    def render(
        self,
        video_id: str,
        job_id: str,
        frame: int,
    ) -> MetricDepthPreview:
        if frame < 0:
            raise ValidationError("Depth preview frame must be non-negative")

        result, depth_path = self._validated_result(video_id, job_id)
        depths = _load_depth_stack(depth_path)
        if frame >= depths.shape[0]:
            raise ValidationError(
                f"Depth preview frame must be between 0 and {depths.shape[0] - 1}"
            )

        preview_meta = result.get("depth_preview")
        if isinstance(preview_meta, dict):
            minimum = preview_meta.get("display_min_m")
            maximum = preview_meta.get("display_max_m")
        else:
            minimum = None
            maximum = None

        if not isinstance(minimum, (int, float)) or not isinstance(
            maximum,
            (int, float),
        ):
            minimum, maximum = metric_depth_display_range(depths)

        display_min_m = float(minimum)
        display_max_m = float(maximum)
        rgb = _colorize_depth(
            depths[frame],
            display_min_m=display_min_m,
            display_max_m=display_max_m,
        )
        image = Image.fromarray(rgb, mode="RGB")
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)

        return MetricDepthPreview(
            png_bytes=output.getvalue(),
            frame=frame,
            display_min_m=display_min_m,
            display_max_m=display_max_m,
            scaling=PREVIEW_SCALING,
            depth_tier=DEPTH_TIER,
        )

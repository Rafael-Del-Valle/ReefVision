"""Bounded geometry-guided SAM alternative boundaries, never box-only refinement."""

from __future__ import annotations

from collections import deque
from typing import Any

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import AssistPrediction, PixelBox, PixelPoint, mask_to_box
from reefvision.ml.sam2_provider import TransformersSam2AssistProvider
from reefvision.schemas.assist import AssistPoint
from reefvision.services.sam2_install import sam2_status
from reefvision.storage.projects import resolve_managed_project_path


def component_points(binary: Any, *, limit: int = 64) -> list[PixelPoint]:
    """One actual foreground pixel per 4-connected component using scanline flood fill."""
    import numpy as np

    remaining = binary.copy()
    points: list[PixelPoint] = []
    height, width = remaining.shape
    for y in range(height):
        while remaining[y].any():
            x = int(np.flatnonzero(remaining[y])[0])
            points.append(PixelPoint(x=x + 0.5, y=y + 0.5))
            if len(points) > limit:
                raise ValidationError("Mask has too many fragments or holes for bounded refinement")
            queue = deque([(y, x)])
            while queue:
                row, col = queue.popleft()
                if not remaining[row, col]:
                    continue
                left = col
                right = col + 1
                while left > 0 and remaining[row, left - 1]:
                    left -= 1
                while right < width and remaining[row, right]:
                    right += 1
                remaining[row, left:right] = False
                for neighbor in (row - 1, row + 1):
                    if 0 <= neighbor < height:
                        runs = remaining[neighbor, left:right]
                        starts = np.flatnonzero(runs & ~np.concatenate(([False], runs[:-1])))
                        queue.extend((neighbor, left + int(start)) for start in starts)
    return points


def guiding_prompts(prior: Any) -> tuple[list[PixelPoint], list[PixelPoint], PixelBox]:
    import numpy as np

    if not prior.any():
        raise ValidationError("Cannot refine a zero-area mask")
    bounds = mask_to_box(prior)
    height, width = prior.shape
    margin = max(3, int(max(bounds.x_max - bounds.x_min, bounds.y_max - bounds.y_min) * 0.1))
    roi = PixelBox(
        x_min=max(0, bounds.x_min - margin),
        y_min=max(0, bounds.y_min - margin),
        x_max=min(width, bounds.x_max + margin),
        y_max=min(height, bounds.y_max + margin),
    )
    left, top, right, bottom = int(roi.x_min), int(roi.y_min), int(roi.x_max), int(roi.y_max)
    cropped = prior[top:bottom, left:right]
    positive = component_points(cropped)
    negative = component_points(~cropped)
    # Bounded deterministic landmarks cover branches beyond the component seed.
    ys, xs = np.nonzero(cropped)
    for index in np.linspace(0, len(xs) - 1, min(24, len(xs)), dtype=int):
        positive.append(PixelPoint(x=float(xs[index]) + 0.5, y=float(ys[index]) + 0.5))
    return (
        [PixelPoint(x=p.x + left, y=p.y + top) for p in positive],
        [PixelPoint(x=p.x + left, y=p.y + top) for p in negative],
        roi,
    )


def infer_refinement(
    *,
    settings: Settings,
    source_image_path: str,
    variant: str,
    device: str,
    prior: Any,
    positive_points: list[AssistPoint],
    negative_points: list[AssistPoint],
) -> tuple[AssistPrediction, dict[str, Any]]:
    from reefvision.ml.sam_image_proposals import SAM_INFERENCE_LOCK, load_runtime

    status = sam2_status(settings, variant)
    if not status["ready"]:
        raise ValidationError(f"Choose/download SAM 2.1 {variant}: {status['reason']}")
    positive, negative, roi = guiding_prompts(prior)
    height, width = prior.shape
    for point in [*positive_points, *negative_points]:
        if not 0 <= point.x < width or not 0 <= point.y < height:
            raise ValidationError("Refinement prompts must lie inside the source image")
    positive.extend(PixelPoint(x=p.x, y=p.y) for p in positive_points)
    negative.extend(PixelPoint(x=p.x, y=p.y) for p in negative_points)
    with SAM_INFERENCE_LOCK:
        provider = TransformersSam2AssistProvider()
        provider._model, provider._processor, provider._device = load_runtime(
            str(status["path"]), device
        )
        prepared = provider.prepare_image(resolve_managed_project_path(settings, source_image_path))
        try:
            result = provider.predict_from_points(prepared, positive, negative, roi)
        finally:
            prepared.close()
    return result, {
        "provider_name": "sam2",
        "variant": variant,
        "checkpoint_sha256": status["weight_sha256"],
        "checkpoint_revision": status["revision"],
        "prompt_mode": "geometry_guided_points_and_roi",
        "positive_points": [{"x": p.x, "y": p.y} for p in positive],
        "negative_points": [{"x": p.x, "y": p.y} for p in negative],
        "roi": {"x_min": roi.x_min, "y_min": roi.y_min, "x_max": roi.x_max, "y_max": roi.y_max},
    }

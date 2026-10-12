"""Local SAM 2 point-grid generation using the pinned Transformers API.

One image embedding per overlapping tile, three masks per point, no downloads.
The model cache and lock are shared with selected-mask refinement.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.optional_transformers_runtime import resolve_torch_device
from reefvision.schemas.sam_image_proposals import SamImageProposalsRequest

SAM_INFERENCE_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def load_runtime(model_path: str, device: str) -> tuple[Any, Any, str]:
    try:
        from transformers import Sam2Model, Sam2Processor

        resolved = str(resolve_torch_device(device))
        processor = Sam2Processor.from_pretrained(model_path, local_files_only=True)
        model = Sam2Model.from_pretrained(model_path, local_files_only=True).to(resolved).eval()
        return model, processor, resolved
    except Exception as exc:
        raise ValidationError(
            f"Could not load local SAM 2.1: {exc}. Choose/download SAM 2.1 in Model Hub; "
            "if GPU memory is exhausted, select CPU or Tiny."
        ) from exc


def tile_boxes(width: int, height: int, tile_size: int) -> list[tuple[int, int, int, int]]:
    def starts(length: int) -> list[int]:
        if length <= tile_size:
            return [0]
        values = list(range(0, length - tile_size, tile_size * 3 // 4))
        return [*values, length - tile_size]

    boxes = [
        (x, y, min(x + tile_size, width), min(y + tile_size, height))
        for y in starts(height)
        for x in starts(width)
    ]
    if len(boxes) > 16 or width * height > 64_000_000:
        raise ValidationError(
            "Image exceeds the bounded SAM budget (16 tiles / 64 million pixels). "
            "Use larger tiles or import a scientifically appropriate image crop."
        )
    return boxes


def mask_iou(first: Any, second: Any) -> float:
    import numpy as np

    intersection = int(np.count_nonzero(first & second))
    union = int(np.count_nonzero(first | second))
    return intersection / union if union else 0.0


@dataclass
class MaskCandidate:
    mask: Any
    x: int
    y: int
    score: float
    stability: float
    point: tuple[float, float] | None = None
    device: str | None = None

    @property
    def area(self) -> int:
        import numpy as np

        return int(np.count_nonzero(self.mask))


def candidate_iou(first: MaskCandidate, second: MaskCandidate) -> float:
    import numpy as np

    left, top = max(first.x, second.x), max(first.y, second.y)
    right = min(first.x + first.mask.shape[1], second.x + second.mask.shape[1])
    bottom = min(first.y + first.mask.shape[0], second.y + second.mask.shape[0])
    if right <= left or bottom <= top:
        return 0.0
    a = first.mask[top - first.y : bottom - first.y, left - first.x : right - first.x]
    b = second.mask[top - second.y : bottom - second.y, left - second.x : right - second.x]
    intersection = int(np.count_nonzero(a & b))
    union = first.area + second.area - intersection
    return intersection / union if union else 0.0


def generate_candidates(
    image: Image.Image,
    model_path: str,
    request: SamImageProposalsRequest,
    checkpoint: Callable[[str, int, int], None],
) -> Iterator[MaskCandidate]:
    """Yield genuine source-pixel masks. Check cancellation between model operations."""
    import numpy as np
    import torch

    boxes = tile_boxes(image.width, image.height, request.tile_size)
    total = len(boxes) * request.points_per_side**2
    if total > 256:
        raise ValidationError(
            "SAM point budget exceeds 256; reduce points per side or use larger tiles"
        )
    checkpoint("loading", 0, total)
    model, processor, device = load_runtime(model_path, request.device)
    completed = 0
    for x1, y1, x2, y2 in boxes:
        checkpoint("encoding_tile", completed, total)
        tile = image.crop((x1, y1, x2, y2))
        inputs = processor(images=tile, return_tensors="pt").to(device)
        with torch.inference_mode():
            embeddings = model.get_image_embeddings(inputs["pixel_values"])
        # Sam2Processor maps prompt coordinates independently to its square input.
        input_height, input_width = inputs["pixel_values"].shape[-2:]
        for row in range(request.points_per_side):
            for column in range(request.points_per_side):
                checkpoint("extracting_candidates", completed, total)
                px = (column + 0.5) / request.points_per_side
                py = (row + 0.5) / request.points_per_side
                points = torch.tensor([[[[px * input_width, py * input_height]]]], device=device)
                labels = torch.ones((1, 1, 1), dtype=torch.int64, device=device)
                try:
                    with torch.inference_mode():
                        output = model(
                            image_embeddings=embeddings,
                            input_points=points,
                            input_labels=labels,
                            multimask_output=True,
                        )
                    logits = processor.post_process_masks(
                        output.pred_masks.detach().cpu(),
                        inputs["original_sizes"].cpu(),
                        binarize=False,
                    )[0]
                    masks = logits.reshape(-1, tile.height, tile.width).numpy()
                    scores = output.iou_scores.detach().cpu().reshape(-1).tolist()
                except Exception as exc:
                    raise ValidationError(
                        f"SAM generation failed: {exc}. Retry with CPU, Tiny, or smaller tiles."
                    ) from exc
                for logits_array, score in zip(masks, scores, strict=True):
                    if not np.isfinite(score) or score < request.confidence_threshold:
                        continue
                    low_area = int(np.count_nonzero(logits_array > -1.0))
                    stability = (
                        int(np.count_nonzero(logits_array > 1.0)) / low_area if low_area else 0.0
                    )
                    binary = logits_array > 0
                    if (
                        stability < request.stability_threshold
                        or binary.sum() < request.min_region_area
                    ):
                        continue
                    # A boundary cut by an internal tile edge is not a complete object.
                    if (
                        (x1 > 0 and binary[:, 0].any())
                        or (y1 > 0 and binary[0, :].any())
                        or (x2 < image.width and binary[:, -1].any())
                        or (y2 < image.height and binary[-1, :].any())
                    ):
                        continue
                    yield MaskCandidate(
                        binary,
                        x1,
                        y1,
                        min(1.0, max(0.0, float(score))),
                        stability,
                        (x1 + px * tile.width, y1 + py * tile.height),
                        device,
                    )
                completed += 1
                checkpoint("filtering", completed, total)
        del embeddings, inputs

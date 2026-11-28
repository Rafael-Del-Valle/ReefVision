"""Window placement and class-aware suppression in original image coordinates."""

from collections import defaultdict
from collections.abc import Iterator
from itertools import islice, product

from reefvision.ml.providers import DetectionPrediction
from reefvision.schemas.models import DetectionTiling


def _starts(length: int, tile: int, overlap: float) -> list[int]:
    last = max(0, length - tile)
    stride = max(1, round(tile * (1 - overlap)))
    return [*range(0, last, stride), last]


def tile_batches(
    size: tuple[int, int], settings: DetectionTiling
) -> Iterator[list[tuple[int, int, int, int]]]:
    width, height = size
    origins = product(
        _starts(height, settings.height, settings.overlap_y),
        _starts(width, settings.width, settings.overlap_x),
    )
    while batch := list(islice(origins, settings.batch_size)):
        yield [
            (x, y, min(x + settings.width, width), min(y + settings.height, height))
            for y, x in batch
        ]


def merge_detections(
    predictions: list[DetectionPrediction], threshold: float
) -> list[DetectionPrediction]:
    # Keep coordinates on CPU during global suppression, including after CUDA inference.
    # Grouping by class prevents overlap between different taxa from suppressing either.
    import torch
    from torchvision.ops import nms  # type: ignore[import-untyped]

    groups: dict[int | str, list[int]] = defaultdict(list)
    for index, item in enumerate(predictions):
        groups[item.class_index if item.class_index is not None else item.label].append(index)

    selected: list[int] = []
    for indices in groups.values():
        boxes = [predictions[i].box for i in indices]
        bounds = torch.tensor(
            [(b.x_min, b.y_min, b.x_max, b.y_max) for b in boxes], dtype=torch.float64
        )
        scores = torch.tensor([predictions[i].confidence for i in indices], dtype=torch.float64)
        selected.extend(indices[i] for i in nms(bounds, scores, threshold).tolist())
    return [predictions[i] for i in sorted(selected, key=lambda i: (-predictions[i].confidence, i))]

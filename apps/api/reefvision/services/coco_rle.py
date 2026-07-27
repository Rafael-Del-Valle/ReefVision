"""Pure-Python COCO compact RLE encoding and request normalization.

The string codec follows the reference COCO mask API's ``rleToString`` and
``rleFrString`` implementation. Raster order remains COCO column-major.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from reefvision.domain.errors import ValidationError


def decode_compact_counts(value: str | bytes) -> list[int]:
    """Decode a COCO compact counts string into non-negative run lengths."""

    try:
        text = value.decode("ascii") if isinstance(value, bytes) else value
    except UnicodeDecodeError as exc:
        raise ValidationError("Compressed COCO RLE counts must be ASCII") from exc
    if not isinstance(text, str) or not text:
        raise ValidationError("Compressed COCO RLE counts must be a non-empty string")

    counts: list[int] = []
    position = 0
    while position < len(text):
        decoded = 0
        shift = 0
        more = True
        while more:
            if position >= len(text):
                raise ValidationError("Compressed COCO RLE ended inside a run length")
            code = ord(text[position]) - 48
            position += 1
            if code < 0 or code > 0x3F:
                raise ValidationError("Compressed COCO RLE contains an invalid character")
            decoded |= (code & 0x1F) << shift
            more = bool(code & 0x20)
            shift += 5
            if shift > 65:
                raise ValidationError("Compressed COCO RLE run length is too large")
            if not more and code & 0x10:
                decoded |= -1 << shift
        if len(counts) > 2:
            decoded += counts[-2]
        if decoded < 0:
            raise ValidationError("Compressed COCO RLE decoded to a negative run length")
        counts.append(decoded)
    return counts


def encode_compact_counts(counts: Sequence[int]) -> str:
    """Encode non-negative run lengths using the reference COCO string codec."""

    normalized = [int(value) for value in counts]
    if not normalized or any(value < 0 for value in normalized):
        raise ValidationError("COCO RLE counts must be a non-empty non-negative sequence")
    output: list[str] = []
    for index, raw_value in enumerate(normalized):
        value = raw_value - normalized[index - 2] if index > 2 else raw_value
        more = True
        while more:
            code = value & 0x1F
            value >>= 5
            more = value != (-1 if code & 0x10 else 0)
            if more:
                code |= 0x20
            output.append(chr(code + 48))
    return "".join(output)


def _expanded_segmentation(segmentation: Any) -> Any:
    if not isinstance(segmentation, dict):
        return segmentation
    counts = segmentation.get("counts")
    size = segmentation.get("size")
    if not isinstance(counts, (str, bytes)):
        return segmentation
    if not isinstance(size, list) or len(size) != 2:
        raise ValidationError("Compressed COCO RLE masks require a [height, width] size")
    try:
        height, width = int(size[0]), int(size[1])
    except (TypeError, ValueError) as exc:
        raise ValidationError("Compressed COCO RLE dimensions must be integers") from exc
    if height <= 0 or width <= 0:
        raise ValidationError("Compressed COCO RLE dimensions must be positive")
    decoded = decode_compact_counts(counts)
    if sum(decoded) != height * width:
        raise ValidationError(
            "Compressed COCO RLE counts do not cover the declared mask dimensions"
        )
    return {**segmentation, "size": [height, width], "counts": decoded}


def expand_compact_rle_document(document: dict[str, Any]) -> dict[str, Any]:
    """Return a copy whose annotation segmentations use uncompressed counts."""

    expanded = deepcopy(document)
    annotations = expanded.get("annotations")
    if not isinstance(annotations, list):
        return expanded
    for annotation in annotations:
        if isinstance(annotation, dict) and "segmentation" in annotation:
            annotation["segmentation"] = _expanded_segmentation(annotation["segmentation"])
    return expanded

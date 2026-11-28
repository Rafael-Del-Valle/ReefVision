"""Screen full-frame, upright images across the splits of one frozen dataset."""

from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.storage.projects import filesystem_io_path

RULE_ID = "cross_split_similar_images"
MAX_HASH_DISTANCE = 3
MAX_MEAN_RGB_DIFFERENCE = 8.0
MAX_ASPECT_RATIO_CHANGE = 0.01
MAX_CANDIDATES = 2_000_000
MAX_FINDINGS = 10_000


@dataclass(frozen=True)
class SplitImage:
    id: str
    split: str
    filename: str
    path: Path
    digest: str
    width: int
    height: int


@dataclass(frozen=True)
class Signature:
    image: SplitImage
    difference_hash: int
    rgb: bytes


def _signature(image: SplitImage, check_cancelled: Callable[[], None]) -> Signature:
    try:
        with filesystem_io_path(image.path).open("rb") as stream:
            digest = sha256()
            for index, chunk in enumerate(iter(lambda: stream.read(1024 * 1024), b"")):
                if index % 16 == 0:
                    check_cancelled()
                digest.update(chunk)
            if digest.hexdigest() != image.digest:
                raise ValidationError(f"Frozen image checksum changed: {image.filename}")
            stream.seek(0)
            with Image.open(stream) as original:
                if original.size != (image.width, image.height):
                    raise ValidationError(f"Frozen image dimensions changed: {image.filename}")
                # Downsample before converting high-resolution inputs to several color channels.
                original.thumbnail((512, 512), Image.Resampling.LANCZOS)
                thumb = original.convert("RGBA").resize((16, 16), Image.Resampling.BOX)
                background = Image.new("RGBA", thumb.size, "white")
                rgb = Image.alpha_composite(background, thumb).convert("RGB")
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValidationError(f"Cannot read frozen image {image.filename}: {exc}") from exc
    gray = rgb.convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    bits = 0
    for row in range(8):
        for column in range(8):
            pos = 9 * row + column
            bits = (bits << 1) | (gray[pos] > gray[pos + 1])
    return Signature(image, bits, rgb.tobytes())


def similar_pairs(
    images: Iterable[SplitImage], check_cancelled: Callable[[], None]
) -> Iterator[tuple[SplitImage, SplitImage, int, float]]:
    # With a distance of at most three, at least one of four disjoint 16-bit bands matches.
    index: dict[tuple[int, int, str], list[int]] = defaultdict(list)
    known: list[Signature] = []
    comparisons = findings = 0
    splits = {"train", "validation", "test"}
    for image in images:
        check_cancelled()
        current = _signature(image, check_cancelled)
        bands = [(i, (current.difference_hash >> (16 * i)) & 0xFFFF) for i in range(4)]
        candidates: set[int] = set()
        for band, value in bands:
            for other_split in splits - {image.split}:
                candidates.update(index.get((band, value, other_split), ()))
        comparisons += len(candidates)
        if comparisons > MAX_CANDIDATES:
            raise ValidationError(
                "Comparison limit reached. Screen a smaller dataset spanning the same splits."
            )
        for count, idx in enumerate(sorted(candidates)):
            if count % 256 == 0:
                check_cancelled()
            previous = known[idx]
            distance = (current.difference_hash ^ previous.difference_hash).bit_count()
            if distance > MAX_HASH_DISTANCE:
                continue
            left = image.width * previous.image.height
            right = previous.image.width * image.height
            if abs(left - right) > MAX_ASPECT_RATIO_CHANGE * max(left, right):
                continue
            color_difference = sum(
                abs(a - b) for a, b in zip(current.rgb, previous.rgb, strict=True)
            ) / len(current.rgb)
            if color_difference <= MAX_MEAN_RGB_DIFFERENCE:
                findings += 1
                if findings > MAX_FINDINGS:
                    raise ValidationError(
                        "Finding limit reached. Screen a smaller dataset spanning the same splits."
                    )
                yield previous.image, image, distance, color_difference
        for band, value in bands:
            index[band, value, image.split].append(len(known))
        known.append(current)

"""Source-pixel appearance crops read from the unchanged managed recordings."""

import hashlib
import math
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from reefvision.config import Settings
from reefvision.db.models import VideoAsset
from reefvision.domain.errors import ValidationError
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.video_media import load_exact_video_frames


def verified_media(
    settings: Settings, relative_path: str, checksum: str, size: int | None = None
) -> Path:
    path = resolve_managed_project_path(settings, relative_path)
    try:
        observed = hash_model_file(path)
    except OSError as exc:
        raise ValidationError("Pinned appearance media is missing or unreadable") from exc
    if observed[0] != checksum or (size is not None and observed[1] != size):
        raise ValidationError("Pinned appearance media no longer matches its recorded SHA-256")
    return path


def source_crops(
    settings: Settings,
    video: VideoAsset,
    requests: list[tuple[str, int, list[float]]],
    progress: Callable[[], None],
) -> dict[str, tuple[Image.Image, list[int], str]]:
    path = verified_media(settings, video.managed_path, video.sha256)
    frames = load_exact_video_frames(
        path, video, [frame for _, frame, _ in requests], cancellation_check=progress
    )
    result = {}
    for identifier, index, box in requests:
        if len(box) != 4 or any(not math.isfinite(value) for value in box):
            raise ValidationError("Appearance source has an invalid source-pixel box")
        x, y, width, height = box
        bounds = (math.floor(x), math.floor(y), math.ceil(x + width), math.ceil(y + height))
        if not (
            width > 0
            and height > 0
            and 0 <= bounds[0] < bounds[2] <= video.width_px
            and 0 <= bounds[1] < bounds[3] <= video.height_px
        ):
            raise ValidationError("Appearance crop lies outside the original video frame")
        crop = frames[index].crop(bounds).convert("RGB")
        result[identifier] = (crop, list(bounds), hashlib.sha256(crop.tobytes()).hexdigest())
    return result

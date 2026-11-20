"""Read bounded raster bytes for exact source-pixel comparisons."""

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.segmentation_metric_masks import MAX_MASK_PNG_BYTES


def read_comparison_raster(settings: Settings, relative_path: str) -> bytes:
    path = resolve_managed_project_path(settings, relative_path)
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_MASK_PNG_BYTES + 1)
    except OSError as exc:
        raise ValidationError("Managed mask pixels are missing or unreadable") from exc
    if len(payload) > MAX_MASK_PNG_BYTES:
        raise ValidationError("Managed mask exceeds the supported evaluation size")
    return payload

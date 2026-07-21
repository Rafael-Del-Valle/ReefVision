"""Safe managed storage operations for raster mask annotations."""

from __future__ import annotations

import base64
import binascii
import os
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image, UnidentifiedImageError

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.projects import resolve_managed_project_path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class StoredPredictionMask:
    """Metadata for one atomically published proposal mask."""

    relative_path: str
    path: Path
    content_sha256: str
    area_pixels: int
    x_min: float
    y_min: float
    x_max: float
    y_max: float


def _validated_binary_png(
    payload: bytes,
    *,
    expected_width: int,
    expected_height: int,
    error_prefix: str,
) -> tuple[bytes, int, tuple[int, int, int, int]]:
    if not payload.startswith(PNG_SIGNATURE):
        raise ValidationError(f"{error_prefix} is not a PNG image")
    try:
        with Image.open(BytesIO(payload)) as image:
            image.load()
            if image.size != (expected_width, expected_height):
                raise ValidationError(f"{error_prefix} dimensions do not match the source image")
            grayscale = image.convert("L")
            binary = grayscale.point(lambda value: 255 if value else 0, mode="L")
            bounds = binary.getbbox()
            if bounds is None:
                raise ValidationError(f"{error_prefix} is empty")
            histogram = binary.histogram()
            area_pixels = int(histogram[255])
            normalized = BytesIO()
            binary.save(normalized, format="PNG", optimize=True)
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError(f"{error_prefix} is not a readable PNG image") from exc
    if area_pixels <= 0:
        raise ValidationError(f"{error_prefix} is empty")
    return normalized.getvalue(), area_pixels, bounds


def write_prediction_mask_png(
    settings: Settings,
    *,
    project_storage_root: str,
    proposal_id: str,
    png_bytes: bytes,
    expected_width: int,
    expected_height: int,
) -> StoredPredictionMask:
    """Validate and atomically publish a restart-safe prediction mask PNG."""

    payload, area_pixels, bounds = _validated_binary_png(
        png_bytes,
        expected_width=expected_width,
        expected_height=expected_height,
        error_prefix="Prediction mask output",
    )
    destination = _prediction_mask_path(
        settings,
        project_storage_root=project_storage_root,
        proposal_id=proposal_id,
    )
    destination_directory = destination.parent
    destination_directory.mkdir(parents=True, exist_ok=True)
    temporary = destination_directory / f".{uuid4().hex}.tmp"
    relative_path = destination.relative_to(settings.resolved_data_dir).as_posix()
    content_sha256 = sha256(payload).hexdigest()
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    x_min, y_min, x_max, y_max = bounds
    return StoredPredictionMask(
        relative_path=relative_path,
        path=destination,
        content_sha256=content_sha256,
        area_pixels=area_pixels,
        x_min=float(x_min),
        y_min=float(y_min),
        x_max=float(x_max),
        y_max=float(y_max),
    )


def _project_mask_path(
    settings: Settings,
    *,
    project_storage_root: str,
    relative_path: str,
    required_directory: str,
) -> Path:
    normalized = Path(relative_path.replace("\\", "/"))
    if (
        normalized.is_absolute()
        or ".." in normalized.parts
        or normalized.suffix.casefold() != ".png"
    ):
        raise ValidationError("Mask access requires a managed project-relative PNG path")
    required_root = _managed_mask_root(
        settings,
        project_storage_root=project_storage_root,
        required_directory=required_directory,
    )
    path = resolve_managed_project_path(settings, relative_path)
    if not path.is_relative_to(required_root):
        raise ValidationError(
            f"Mask path must remain inside this project's {required_directory} directory"
        )
    return path


def _managed_mask_root(
    settings: Settings,
    *,
    project_storage_root: str,
    required_directory: str,
) -> Path:
    """Resolve a mask subdirectory without following it outside its project."""

    project_root = resolve_managed_project_path(settings, project_storage_root)
    required_root = (project_root / required_directory).resolve()
    if not required_root.is_relative_to(project_root):
        raise ValidationError("Managed mask storage may not escape its owning project")
    return required_root


def _prediction_mask_path(
    settings: Settings,
    *,
    project_storage_root: str,
    proposal_id: str,
) -> Path:
    try:
        canonical_proposal_id = str(UUID(proposal_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationError("Prediction mask identifiers must be UUIDs") from exc
    if canonical_proposal_id != proposal_id:
        raise ValidationError("Prediction mask identifiers must use canonical UUIDs")
    prediction_root = _managed_mask_root(
        settings,
        project_storage_root=project_storage_root,
        required_directory="prediction-masks",
    )
    destination = (
        prediction_root / canonical_proposal_id[:2] / f"{canonical_proposal_id}.png"
    ).resolve()
    if not destination.is_relative_to(prediction_root):
        raise ValidationError("Prediction mask identifiers may not escape managed storage")
    return destination


def _mask_annotation_path(
    settings: Settings,
    *,
    project_storage_root: str,
    image_id: str,
    mask_annotation_id: str,
) -> Path:
    for value, label in (
        (image_id, "Image"),
        (mask_annotation_id, "Mask annotation"),
    ):
        normalized = Path(value.replace("\\", "/"))
        if normalized.is_absolute() or len(normalized.parts) != 1 or normalized.name != value:
            raise ValidationError(f"{label} identifiers must be managed path components")
    mask_root = _managed_mask_root(
        settings,
        project_storage_root=project_storage_root,
        required_directory="masks",
    )
    destination = (mask_root / image_id / f"{mask_annotation_id}.png").resolve()
    if not destination.is_relative_to(mask_root):
        raise ValidationError("Mask annotation identifiers may not escape managed storage")
    return destination


def resolve_prediction_mask_png(
    settings: Settings,
    *,
    project_storage_root: str,
    proposal_id: str,
    relative_path: str,
) -> Path:
    """Resolve only the canonical managed PNG path for one prediction proposal."""

    path = _project_mask_path(
        settings,
        project_storage_root=project_storage_root,
        relative_path=relative_path,
        required_directory="prediction-masks",
    )
    expected = _prediction_mask_path(
        settings,
        project_storage_root=project_storage_root,
        proposal_id=proposal_id,
    )
    expected_relative = expected.relative_to(settings.resolved_data_dir).as_posix()
    if path != expected or relative_path != expected_relative:
        raise ValidationError("Prediction mask path does not match its proposal")
    return path


def _remove_mask_and_empty_parent(path: Path) -> None:
    path.unlink(missing_ok=True)
    with suppress(OSError):
        path.parent.rmdir()


def remove_prediction_mask_png(
    settings: Settings,
    *,
    project_storage_root: str,
    proposal_id: str,
    relative_path: str,
) -> None:
    """Remove one managed proposal mask and its empty shard directory."""

    path = resolve_prediction_mask_png(
        settings,
        project_storage_root=project_storage_root,
        proposal_id=proposal_id,
        relative_path=relative_path,
    )
    _remove_mask_and_empty_parent(path)


def remove_mask_annotation_png(
    settings: Settings,
    *,
    project_storage_root: str,
    image_id: str,
    mask_annotation_id: str,
    relative_path: str,
) -> None:
    """Remove one managed annotation mask after its database transaction rolls back."""

    path = _project_mask_path(
        settings,
        project_storage_root=project_storage_root,
        relative_path=relative_path,
        required_directory="masks",
    )
    expected = _mask_annotation_path(
        settings,
        project_storage_root=project_storage_root,
        image_id=image_id,
        mask_annotation_id=mask_annotation_id,
    )
    expected_relative = expected.relative_to(settings.resolved_data_dir).as_posix()
    if path != expected or relative_path != expected_relative:
        raise ValidationError("Mask annotation path does not match its annotation")
    _remove_mask_and_empty_parent(path)


def write_mask_png(
    settings: Settings,
    *,
    project_storage_root: str,
    image_id: str,
    mask_annotation_id: str,
    png_base64: str,
    expected_width: int,
    expected_height: int,
) -> tuple[str, Path, int, float, float, float, float]:
    """Validate and atomically store a PNG beneath the managed project directory."""

    try:
        payload = base64.b64decode(png_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("Assist mask output is not valid base64 data") from exc
    if not payload.startswith(PNG_SIGNATURE):
        raise ValidationError("Assist mask output is not a PNG image")

    try:
        with Image.open(BytesIO(payload)) as image:
            image.load()
            if image.size != (expected_width, expected_height):
                raise ValidationError("Assist mask dimensions do not match the source image")
            grayscale = image.convert("L")
            bounds = grayscale.getbbox()
            if bounds is None:
                raise ValidationError("Assist mask output is empty")
            histogram = grayscale.histogram()
            area_pixels = int(sum(histogram[1:]))
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Assist mask output is not a readable PNG image") from exc
    if area_pixels <= 0:
        raise ValidationError("Assist mask output is empty")

    destination = _mask_annotation_path(
        settings,
        project_storage_root=project_storage_root,
        image_id=image_id,
        mask_annotation_id=mask_annotation_id,
    )
    destination_directory = destination.parent
    destination_directory.mkdir(parents=True, exist_ok=True)
    temporary = destination_directory / f".{uuid4().hex}.tmp"
    relative_path = destination.relative_to(settings.resolved_data_dir).as_posix()
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    x_min, y_min, x_max, y_max = bounds
    return (
        relative_path,
        destination,
        area_pixels,
        float(x_min),
        float(y_min),
        float(x_max),
        float(y_max),
    )

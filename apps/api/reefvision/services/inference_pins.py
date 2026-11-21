"""Verify exact original bytes and local weights for a pinned inference request."""

from collections.abc import Sequence
from uuid import UUID

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, ModelRegistration
from reefvision.domain.errors import ConflictError
from reefvision.schemas.models import InferenceSourcePins
from reefvision.services.model_runtime import verify_checkpoint
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path


def verify_inference_pins(
    settings: Settings,
    model: ModelRegistration,
    images: Sequence[ImageAsset],
    pins: InferenceSourcePins,
) -> None:
    if {row.id for row in images} != {str(key) for key in pins.images} or any(
        row.project_id != model.project_id for row in images
    ):
        raise ConflictError("Inference source pins must match every selected project image.")
    verify_checkpoint(settings, model, pins.checkpoint_sha256, model.file_size_bytes)
    for row in images:
        expected = pins.images[UUID(row.id)]
        if row.sha256 != expected:
            raise ConflictError("The original image differs from the supplied checksum.")
        try:
            actual, _ = hash_model_file(resolve_managed_project_path(settings, row.managed_path))
        except OSError as exc:
            raise ConflictError("The pinned original image is unavailable.") from exc
        if actual != expected:
            raise ConflictError("The original image bytes differ from the supplied checksum.")

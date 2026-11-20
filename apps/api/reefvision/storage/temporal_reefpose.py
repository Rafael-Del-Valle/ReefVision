"""Managed atomic temporal checkpoint storage."""

from __future__ import annotations

import os
import tempfile
from typing import Any

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path


def save_temporal_checkpoint(
    settings: Settings, relative_path: str, state: dict[str, Any]
) -> tuple[str, int]:
    import torch

    path = resolve_managed_project_path(settings, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix=".pt", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            torch.save(state, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return hash_model_file(path)


def discard_temporal_checkpoint(settings: Settings, relative_path: str) -> None:
    resolve_managed_project_path(settings, relative_path).unlink(missing_ok=True)


def read_temporal_checkpoint(
    settings: Settings, relative_path: str, expected_sha256: str | None = None
) -> dict[str, Any] | None:
    import torch

    path = resolve_managed_project_path(settings, relative_path)
    if not path.is_file():
        if expected_sha256 is None:
            return None
        raise ValidationError("Temporal checkpoint file is unavailable")
    if expected_sha256 is not None and hash_model_file(path)[0] != expected_sha256:
        raise ValidationError("Temporal checkpoint checksum does not match the registry")
    try:
        with path.open("rb") as source:
            state = torch.load(source, map_location="cpu", weights_only=True)
    except Exception as exc:
        raise ValidationError("Temporal checkpoint could not be read safely") from exc
    if not isinstance(state, dict):
        raise ValidationError("Temporal checkpoint payload is invalid")
    return state

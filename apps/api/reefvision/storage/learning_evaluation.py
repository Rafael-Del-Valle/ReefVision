"""Managed content integrity checks for reproducible holdout evaluation."""

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path


def verify_learning_content(settings: Settings, relative_path: str, expected_sha256: str) -> None:
    try:
        checksum, _ = hash_model_file(resolve_managed_project_path(settings, relative_path))
    except OSError as exc:
        raise ValidationError("Learning evaluation content is missing or unreadable") from exc
    if checksum != expected_sha256:
        raise ValidationError("Learning evaluation content checksum changed")

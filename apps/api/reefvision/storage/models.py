"""Safe managed model-checkpoint filesystem operations."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.images import stream_to_staging
from reefvision.storage.projects import resolve_managed_project_path

SUPPORTED_MODEL_EXTENSIONS = {".pt", ".pth", ".zip"}


def project_model_directories(
    settings: Settings,
    project_storage_root: str,
) -> dict[str, Path]:
    root = resolve_managed_project_path(settings, project_storage_root)
    directories = {
        "models": root / "models",
        "staging": root / ".model-imports",
    }
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=True)
    return directories


def safe_model_name(filename: str | None) -> str:
    if not filename:
        return "unnamed-model"
    return Path(filename.replace("\\", "/")).name or "unnamed-model"


def ensure_supported_model_extension(filename: str) -> None:
    if Path(filename).suffix.lower() not in SUPPORTED_MODEL_EXTENSIONS:
        raise ValidationError(
            "Supported model types are trusted local .pt/.pth checkpoints or "
            "ReefVision semantic/SLEAP-NN .zip bundles"
        )


def stage_model_upload(
    source: BinaryIO,
    destination: Path,
    max_upload_bytes: int,
) -> tuple[str, int]:
    sha256, size = stream_to_staging(source, destination)
    if size > max_upload_bytes:
        destination.unlink(missing_ok=True)
        raise ValidationError("Model file exceeds the configured upload limit")
    return sha256, size


def commit_staged_model(staged_path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValidationError("Managed model destination already exists")
    os.replace(staged_path, destination)


def hash_model_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def copy_model_file(source_path: Path, destination: Path) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValidationError("Managed model destination already exists")
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    total = 0
    try:
        with source_path.open("rb") as source, temporary.open("xb") as output:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                total += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        return digest.hexdigest(), total
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

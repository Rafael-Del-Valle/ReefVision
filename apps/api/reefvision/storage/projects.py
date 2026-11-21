"""Safe managed project-directory operations."""

from __future__ import annotations

import os
from pathlib import Path

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError


def filesystem_io_path(path: Path) -> Path:
    """Use an extended Windows path for filesystem operations, never stored metadata."""
    if os.name != "nt" or not path.is_absolute():
        return path
    text = str(path)
    if text.startswith(("\\\\?\\", "\\\\.\\")):
        return path
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


def resolve_managed_project_path(settings: Settings, relative_path: str) -> Path:
    """Resolve a stored relative project path and prevent data-root escape."""

    data_root = settings.resolved_data_dir
    candidate = (data_root / relative_path).resolve()
    if not candidate.is_relative_to(data_root):
        raise ValidationError("Project storage path escapes the ReefVision data root")
    return candidate


def create_managed_project_directory(settings: Settings, project_id: str) -> str:
    """Create and return a portable data-root-relative project directory."""

    relative_path = f"projects/{project_id}"
    destination = resolve_managed_project_path(settings, relative_path)
    destination.mkdir(parents=True, exist_ok=False)
    return relative_path


def remove_empty_project_directory(settings: Settings, relative_path: str) -> None:
    """Remove a newly created empty directory after a failed transaction."""

    destination = resolve_managed_project_path(settings, relative_path)
    try:
        destination.rmdir()
    except OSError:
        return

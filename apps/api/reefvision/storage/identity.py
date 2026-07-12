"""Stable local-user identity helpers for desktop-first workflows."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from reefvision.config import Settings

LOCAL_USER_IDENTITY_FILENAME = "local-user-id.txt"


def _identity_path(settings: Settings) -> Path:
    settings.ensure_directories()
    return settings.resolved_data_dir / LOCAL_USER_IDENTITY_FILENAME


def get_local_user_identity(settings: Settings) -> str:
    """Return a stable local identity stored inside the ReefVision data directory."""

    identity_path = _identity_path(settings)
    if identity_path.is_file():
        identity = identity_path.read_text(encoding="utf-8").strip()
        if identity:
            return identity

    identity = f"local-user:{uuid4()}"
    temp_path = identity_path.with_suffix(".tmp")
    temp_path.write_text(f"{identity}\n", encoding="utf-8")
    temp_path.replace(identity_path)
    return identity

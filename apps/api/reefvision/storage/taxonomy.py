"""Source-byte checks for original survey media."""

from reefvision.config import Settings
from reefvision.storage.backups import hash_file
from reefvision.storage.projects import resolve_managed_project_path


def source_sha256(settings: Settings, managed_path: str) -> str:
    return hash_file(resolve_managed_project_path(settings, managed_path))[0]

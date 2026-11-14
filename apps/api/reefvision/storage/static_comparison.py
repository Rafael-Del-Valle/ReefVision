"""Check frozen media against its hash, reusing verified unchanged bytes."""

from functools import lru_cache
from pathlib import Path

from reefvision.config import Settings
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path


@lru_cache(maxsize=16384)
def _verified_sha256(path: Path, stamp: tuple[int, int, int, int]) -> str:
    digest, _ = hash_model_file(path)
    if _file_stamp(path) != stamp:
        raise ValidationError("Frozen comparison content changed during verification")
    return digest


def _file_stamp(path: Path) -> tuple[int, int, int, int]:
    info = path.stat()
    return info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def verify_static_content(
    settings: Settings,
    relative_path: str,
    expected_sha256: str,
    *,
    fresh: bool = False,
) -> Path:
    """Return the managed path only when it holds the frozen bytes."""
    path = resolve_managed_project_path(settings, relative_path)
    try:
        stamp = _file_stamp(path)
        if fresh:
            digest, _ = hash_model_file(path)
            if _file_stamp(path) != stamp:
                raise ValidationError("Frozen comparison content changed during verification")
        else:
            digest = _verified_sha256(path, stamp)
    except FileNotFoundError as exc:
        raise NotFoundError("Frozen comparison media or checkpoint file is missing") from exc
    except OSError as exc:
        raise ValidationError("Frozen comparison media or checkpoint is unavailable") from exc
    if digest != expected_sha256:
        raise ValidationError("Frozen comparison media or checkpoint checksum changed")
    return path

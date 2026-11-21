"""Read-only storage checks for managed training."""

import shutil
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from reefvision.domain.errors import ValidationError


def free_training_space_gib(data_dir: Path) -> float:
    return shutil.disk_usage(data_dir).free / (1024**3)


def verify_pose_checkpoint_digest(
    manifest: dict[str, Any], selected_path: str, sha256: str
) -> None:
    """Authenticate a selected checkpoint using the evidence recorded at completion."""
    if "result_checkpoint_sha256" in manifest:
        expected = manifest["result_checkpoint_sha256"]
    else:
        legacy_key = (
            "last_checkpoint_sha256"
            if Path(selected_path).name == "last.pt"
            else "best_checkpoint_sha256"
        )
        expected = manifest.get(legacy_key)
        if expected in (None, ""):
            return
    if expected != sha256:
        raise ValidationError("Trained pose checkpoint checksum changed after completion")


def intact_torch_checkpoint(path: Path) -> bool:
    """Check pinned PyTorch ZIP serialization and CRCs without executing pickle.

    This proves container integrity, not model quality or checkpoint trust.
    """
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            return (
                any(name.endswith("/data.pkl") for name in names)
                and any("/data/" in name for name in names)
                and all(item.file_size > 0 for item in archive.infolist())
                and archive.testzip() is None
            )
    except (OSError, BadZipFile, EOFError, RuntimeError, ZlibError):
        return False

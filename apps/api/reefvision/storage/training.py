"""Read-only storage checks for managed training."""

import shutil
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError


def free_training_space_gib(data_dir: Path) -> float:
    return shutil.disk_usage(data_dir).free / (1024**3)


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

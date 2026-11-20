"""Storage probe for the managed profile used by local workflow schedules."""

import shutil
from pathlib import Path


def available_storage_bytes(data_dir: Path) -> int | None:
    try:
        return shutil.disk_usage(data_dir).free
    except OSError:
        return None

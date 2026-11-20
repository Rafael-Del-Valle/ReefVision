"""Copy the frozen backend selected for the standard Windows installer."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

# PyInstaller collects wheel metadata for literal importlib.metadata.version() calls
# even when the optional module itself is excluded from the frozen application.
UNBUNDLED_METADATA = re.compile(
    r"sleap(?:[-_.](?:io|nn))?(?:-[0-9][^/]*)?\.(?:dist|egg)-info", re.IGNORECASE
)


def stage(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    runtime = source / "_internal"
    if not runtime.is_dir() or not (source / "reefvision-api.exe").is_file():
        raise ValueError(f"Expected a frozen ReefVision Windows backend at {source}")

    def exclude_metadata(directory: str, names: list[str]) -> list[str]:
        if Path(directory) != runtime:
            return []
        return [name for name in names if UNBUNDLED_METADATA.fullmatch(name)]

    shutil.copytree(source, destination, ignore=exclude_metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    stage(args.source, args.destination)

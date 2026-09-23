"""Development-only dataset location; not imported by application code."""

import os
from pathlib import Path

from reefvision.storage.telemetry import find_paired_srt


def get_whaledrone_root() -> Path | None:
    configured = os.environ.get("REEFVISION_WHALEDRONE_ROOT", "").strip()
    if not configured:
        return None
    try:
        root = Path(os.path.expandvars(configured)).expanduser().resolve()
        repository = Path(__file__).resolve().parents[4]
        if root.is_relative_to(repository) or not root.is_dir():
            return None
        return root
    except (OSError, RuntimeError):
        return None


def find_whaledrone_srt(root: Path, video: Path) -> Path | None:
    """Dataset-only layout adapter: current releases separate videos/ and telemetry/."""
    paired = find_paired_srt(video)
    if paired is not None:
        return paired
    telemetry_directory = root / "telemetry"
    if telemetry_directory.is_dir():
        return find_paired_srt(telemetry_directory / video.name)
    return None

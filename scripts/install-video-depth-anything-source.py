#!/usr/bin/env python3
"""Install the pinned Apache-2.0 Video Depth Anything source used by ReefVision."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

UPSTREAM_REPOSITORY = "DepthAnything/Video-Depth-Anything"
UPSTREAM_COMMIT = "4f5ae23172ba60fd7bc11ef671cca678842c7072"
ARCHIVE_URL = (
    "https://github.com/DepthAnything/Video-Depth-Anything/archive/"
    f"{UPSTREAM_COMMIT}.zip"
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_destination() -> Path:
    return (
        repository_root()
        / ".desktop"
        / "provider-runtime"
        / "video-depth-anything"
        / "source"
    )


def install(destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="reefvision-vda-") as temporary:
        temporary_root = Path(temporary)
        archive = temporary_root / "video-depth-anything.zip"
        with urllib.request.urlopen(ARCHIVE_URL, timeout=120) as response:
            archive.write_bytes(response.read())

        with zipfile.ZipFile(archive, "r") as bundle:
            bundle.extractall(temporary_root / "extract")

        candidates = [
            item
            for item in (temporary_root / "extract").iterdir()
            if item.is_dir() and item.name.startswith("Video-Depth-Anything-")
        ]
        if len(candidates) != 1:
            raise RuntimeError("Pinned Video Depth Anything archive layout is unexpected")
        source = candidates[0]

        license_path = source / "LICENSE"
        if not license_path.is_file():
            raise RuntimeError("Pinned Video Depth Anything source is missing LICENSE")
        license_text = license_path.read_text(encoding="utf-8", errors="replace")
        if "Apache License" not in license_text or "Version 2.0" not in license_text:
            raise RuntimeError("Pinned Video Depth Anything source license is not Apache-2.0")

        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination)

    # Upstream imports EasyDict just to construct a mapping unpacked via **.
    # Replace that optional dependency with the equivalent built-in dict.
    # Keep this compatibility patch reproducible and refuse unexpected sources.
    temporal = destination / "video_depth_anything" / "dpt_temporal.py"
    source_text = temporal.read_text(encoding="utf-8")
    import_line = "from easydict import EasyDict\n"
    old_constructor = "motion_module_kwargs = EasyDict("
    if source_text.count(import_line) != 1 or source_text.count(old_constructor) != 1:
        raise RuntimeError("Pinned Video Depth Anything source changed unexpectedly")
    patched = source_text.replace(import_line, "").replace(
        old_constructor, "motion_module_kwargs = dict("
    )
    temporal.write_text(patched, encoding="utf-8")
    patched_sha256 = hashlib.sha256(temporal.read_bytes()).hexdigest()

    manifest = {
        "provider": "video_depth_anything",
        "repository": UPSTREAM_REPOSITORY,
        "commit": UPSTREAM_COMMIT,
        "source_url": ARCHIVE_URL,
        "license": "Apache-2.0",
        "reefvision_compatibility_patch": {
            "file": "video_depth_anything/dpt_temporal.py",
            "description": "Replace EasyDict mapping with builtin dict; keep **kwargs behavior",
            "upstream_behavior_preserved": True,
            "patched_file_sha256": patched_sha256,
        },
        "installed_at_utc": datetime.now(UTC).isoformat(),
    }
    (parent / "source-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=default_destination())
    args = parser.parse_args()
    installed = install(args.destination)
    print(f"Pinned Video Depth Anything source installed: {installed}")
    print(f"Commit: {UPSTREAM_COMMIT}")
    print("License: Apache-2.0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

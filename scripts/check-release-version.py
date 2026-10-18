"""Verify current public ReefVision versions without changing historical releases."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

EXPECTED_VERSION = "1.0.3"


def check_versions(root: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for filename in (
        "package.json",
        "apps/web/package.json",
        "apps/web/package-lock.json",
        "apps/web/src-tauri/tauri.conf.json",
    ):
        payload = json.loads((root / filename).read_text(encoding="utf-8"))
        versions[filename] = payload["version"]
        if filename.endswith("package-lock.json"):
            versions[filename + " root"] = payload["packages"][""]["version"]
    for filename, key in (
        ("pyproject.toml", "project"),
        ("apps/web/src-tauri/Cargo.toml", "package"),
    ):
        versions[filename] = tomllib.loads((root / filename).read_text(encoding="utf-8"))[key][
            "version"
        ]
    lock = tomllib.loads((root / "apps/web/src-tauri/Cargo.lock").read_text(encoding="utf-8"))
    versions["Cargo.lock"] = next(
        p["version"] for p in lock["package"] if p["name"] == "reefvision-desktop"
    )
    sources = {
        "apps/api/reefvision/__init__.py": r'__version__\s*=\s*"([^"]+)"',
        "scripts/lib/reefvision-commands.ps1": r'ReefVisionCommandVersion\s*=\s*"([^"]+)"',
        "apps/web/src/App.tsx": (
            r'ONBOARDING_DISMISS_KEY\s*=\s*"reefvision\.onboarding\.dismissed\.([^"]+)"'
        ),
    }
    for filename, pattern in sources.items():
        match = re.search(pattern, (root / filename).read_text(encoding="utf-8"))
        if match is None:
            raise RuntimeError(f"Missing public version source: {filename}")
        versions[filename] = match.group(1)
    mismatches = {source: value for source, value in versions.items() if value != EXPECTED_VERSION}
    if mismatches:
        raise RuntimeError(f"Release versions must all be {EXPECTED_VERSION}: {mismatches}")
    return versions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    versions = check_versions(args.root)
    print(f"Release version {EXPECTED_VERSION}: {len(versions)} public sources agree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

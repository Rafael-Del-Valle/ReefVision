from __future__ import annotations

import json
import tomllib
from pathlib import Path

from reefvision import __version__

EXPECTED_VERSION = "1.6.0"


def test_authoritative_version_sources_match_release_line() -> None:
    root = Path(__file__).resolve().parents[4]

    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    workspace_package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    web_package = json.loads((root / "apps" / "web" / "package.json").read_text(encoding="utf-8"))
    web_lock = json.loads((root / "apps" / "web" / "package-lock.json").read_text(encoding="utf-8"))
    tauri_config = json.loads(
        (root / "apps" / "web" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    cargo_toml = tomllib.loads(
        (root / "apps" / "web" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    )
    cargo_lock = tomllib.loads(
        (root / "apps" / "web" / "src-tauri" / "Cargo.lock").read_text(encoding="utf-8")
    )

    cargo_lock_version = next(
        package["version"]
        for package in cargo_lock["package"]
        if package["name"] == "reefvision-desktop"
    )

    authoritative_versions = {
        "python_package": __version__,
        "pyproject": pyproject["project"]["version"],
        "workspace_package": workspace_package["version"],
        "web_package": web_package["version"],
        "web_lockfile": web_lock["version"],
        "web_lockfile_root_package": web_lock["packages"][""]["version"],
        "tauri_config": tauri_config["version"],
        "cargo_toml": cargo_toml["package"]["version"],
        "cargo_lock": cargo_lock_version,
    }

    assert authoritative_versions
    assert set(authoritative_versions.values()) == {EXPECTED_VERSION}

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from reefvision import __version__

EXPECTED_VERSION = "1.0.3"


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

    command_source = (root / "scripts" / "lib" / "reefvision-commands.ps1").read_text(
        encoding="utf-8"
    )
    command_match = re.search(
        r'\$script:ReefVisionCommandVersion\s*=\s*"([^"]+)"',
        command_source,
    )
    assert command_match is not None

    app_source = (root / "apps" / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    onboarding_match = re.search(
        r'ONBOARDING_DISMISS_KEY\s*=\s*"reefvision\.onboarding\.dismissed\.([^"]+)"',
        app_source,
    )
    assert onboarding_match is not None

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
        "command_tools": command_match.group(1),
        "onboarding_key": onboarding_match.group(1),
    }

    assert authoritative_versions
    assert set(authoritative_versions.values()) == {EXPECTED_VERSION}


def test_desktop_staging_paths_match_tauri_version() -> None:
    """Prevent Windows build scripts from staging resources for an older release."""
    root = Path(__file__).resolve().parents[4]
    tauri_config = json.loads(
        (root / "apps" / "web" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    expected_stage = f"release-{tauri_config['version']}"
    resources = tauri_config["bundle"]["resources"]
    assert resources, "The packaged Windows backend resources must be declared"
    assert all(expected_stage in path for path in resources)

    for script_name in ("build-desktop.ps1", "build-desktop-backend.ps1"):
        script = (root / "scripts" / script_name).read_text(encoding="utf-8")
        stages = set(re.findall(r"release-\d+\.\d+\.\d+", script))
        assert stages == {expected_stage}, (
            f"{script_name} stages {sorted(stages)!r}; expected {expected_stage}"
        )

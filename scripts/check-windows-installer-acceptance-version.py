"""Verify that the Windows clean-install job targets the packaged Tauri version.

Run before MSI packaging to catch expensive version-mismatch failures.
This check does not execute an installer or initiate model downloads.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def check_workflow(workflow: str, version: str) -> list[str]:
    errors: list[str] = []
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        return [f"Invalid Tauri version: {version!r}"]

    marker = "  windows-clean-install-acceptance:"
    if workflow.count(marker) != 1:
        return ["Expected exactly one Windows clean-install job"]
    job = workflow.split(marker, 1)[1]
    expected_msi = f"ReefVision_{version}_x64_en-US.msi"
    slug = version.replace(".", "-")
    checks = {
        "MSI filename": (
            set(re.findall(r"ReefVision_\d+\.\d+\.\d+_x64_en-US\.msi", job)),
            {expected_msi},
        ),
        "ProductVersion": (
            set(re.findall(r"MSI ProductVersion must be (\d+\.\d+\.\d+)\.", job)),
            {version},
        ),
        "artifact staging directory": (
            set(re.findall(r"reefvision-(\d+-\d+-\d+)-installer", job)),
            {slug},
        ),
        "disposable acceptance root": (
            set(re.findall(r"reefvision-(\d+-\d+-\d+)-disposable-acceptance", job)),
            {slug},
        ),
        "evidence artifact": (
            set(re.findall(r"ReefVision-(\d+\.\d+\.\d+)-Windows-Clean-Install-Evidence", job)),
            {version},
        ),
    }
    for label, (actual, expected) in checks.items():
        if actual != expected:
            errors.append(f"{label}: found {sorted(actual)!r}, expected {sorted(expected)!r}")
    if f"Install, launch, persist and uninstall {version} on fresh Windows" not in job:
        errors.append("Clean-install job label does not match Tauri version")
    if "-LiveSam2Acceptance" in job:
        errors.append("Default clean-install job must not opt into network model downloads")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    config = json.loads(
        (root / "apps/web/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )
    workflow = (root / ".github/workflows/build-desktop.yml").read_text(
        encoding="utf-8"
    )
    errors = check_workflow(workflow, str(config["version"]))
    if errors:
        for error in errors:
            print(f"Windows acceptance version gate: {error}", file=sys.stderr)
        return 1
    print(f"Windows clean-install version gate passed: {config['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Regression coverage for the pre-packaging Windows MSI acceptance guard."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "windows_installer_acceptance_version_103",
    ROOT / "scripts" / "check-windows-installer-acceptance-version.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_workflow(version: str = "1.0.3") -> str:
    slug = version.replace(".", "-")
    return f"""name: Build Windows Desktop
  historical_document: docs/RELEASE_1.0.2.md
  windows-clean-install-acceptance:
    name: Install, launch, persist and uninstall {version} on fresh Windows
    steps:
      - run: |
          $folder = 'reefvision-{slug}-installer'
          $msi = 'ReefVision_{version}_x64_en-US.msi'
          if ($msi.Name -ne 'ReefVision_{version}_x64_en-US.msi') {{ throw 'bad' }}
          throw 'MSI ProductVersion must be {version}.'
          -AcceptanceRoot 'C:\\reefvision-{slug}-disposable-acceptance'
      - name: ReefVision-{version}-Windows-Clean-Install-Evidence
"""


def test_matching_installer_and_acceptance_version_pass() -> None:
    assert MODULE.check_workflow(valid_workflow(), "1.0.3") == []


def test_historical_release_notes_outside_acceptance_job_are_allowed() -> None:
    assert MODULE.check_workflow(
        valid_workflow().replace("RELEASE_1.0.2.md", "RELEASE_1.0.0.md"), "1.0.3"
    ) == []


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("ReefVision_1.0.3_x64_en-US.msi", "ReefVision_1.0.2_x64_en-US.msi"),
        ("MSI ProductVersion must be 1.0.3.", "MSI ProductVersion must be 1.0.2."),
        ("reefvision-1-0-3-installer", "reefvision-1-0-2-installer"),
        ("uninstall 1.0.3", "uninstall 1.0.2"),
        ("ReefVision-1.0.3-Windows-Clean-Install-Evidence", "ReefVision-1.0.2-Windows-Clean-Install-Evidence"),
        ("reefvision-1-0-3-disposable-acceptance", "reefvision-1-0-2-disposable-acceptance"),
    ],
)
def test_stale_version_reference_is_rejected(original: str, replacement: str) -> None:
    assert MODULE.check_workflow(valid_workflow().replace(original, replacement), "1.0.3")


def test_default_acceptance_rejects_implicit_live_model_downloads() -> None:
    workflow = valid_workflow().replace(
        "      - name: ReefVision-1.0.3-Windows-Clean-Install-Evidence",
        "          -LiveSam2Acceptance\n      - name: ReefVision-1.0.3-Windows-Clean-Install-Evidence",
    )
    assert any("network model downloads" in error for error in MODULE.check_workflow(workflow, "1.0.3"))


def test_missing_clean_install_job_is_rejected() -> None:
    assert any("exactly one" in error for error in MODULE.check_workflow("name: Build Windows Desktop", "1.0.3"))


def test_invalid_release_version_is_rejected() -> None:
    assert any("Invalid Tauri version" in error for error in MODULE.check_workflow(valid_workflow(), "1.0.3-rc1"))


def test_mixed_msi_versions_are_rejected() -> None:
    workflow = valid_workflow() + "      # ReefVision_1.0.2_x64_en-US.msi\n"
    assert any("MSI filename" in error for error in MODULE.check_workflow(workflow, "1.0.3"))

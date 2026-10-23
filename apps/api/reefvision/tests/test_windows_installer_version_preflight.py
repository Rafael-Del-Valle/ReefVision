"""Regression coverage for Windows installer version preflight (no network or MSI execution)."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
check_workflow = runpy.run_path(
    str(ROOT / "scripts/check-windows-installer-acceptance-version.py")
)["check_workflow"]


def fixture(version: str = "1.0.3") -> str:
    slug = version.replace(".", "-")
    return f"""name: Build Windows Desktop
jobs:
  build-windows-installer:
    steps:
      - uses: actions/setup-python@v5
      - name: Verify installer version before packaging
        run: python scripts/check-windows-installer-acceptance-version.py
      - name: Build MSI desktop installer with bundled checkpoints
  windows-clean-install-acceptance:
    name: Install, launch, persist and uninstall {version} on fresh Windows
    steps:
      - name: Retrieve exact MSI
        path: reefvision-{slug}-installer
      - name: Check version
        run: |
          if ($msi.Name -ne 'ReefVision_{version}_x64_en-US.msi') {{ throw 'wrong MSI' }}
          if ($versionRecord.StringData(1) -ne '{version}') {{
            throw 'MSI ProductVersion must be {version}.'
          }}
      - name: Isolated installation
        run: ./scripts/acceptance-windows-clean-install.ps1 -AcceptanceRoot 'C:\\reefvision-{slug}-disposable-acceptance' -DisposableTest
      - uses: actions/upload-artifact@v4
        with:
          name: ReefVision-{version}-Windows-Clean-Install-Evidence
"""


def test_matching_offline_installer_contract() -> None:
    assert check_workflow(fixture(), "1.0.3") == []


@pytest.mark.parametrize(
    ("old", "new", "diagnostic"),
    [
        ("ReefVision_1.0.3_x64_en-US.msi", "ReefVision_1.0.2_x64_en-US.msi", "MSI filename"),
        ("StringData(1) -ne '1.0.3'", "StringData(1) -ne '1.0.2'", "ProductVersion comparison"),
        ("MSI ProductVersion must be 1.0.3.", "MSI ProductVersion must be 1.0.2.", "ProductVersion"),
        ("reefvision-1-0-3-installer", "reefvision-1-0-2-installer", "artifact staging directory"),
        ("reefvision-1-0-3-disposable-acceptance", "reefvision-1-0-2-disposable-acceptance", "disposable acceptance root"),
        ("ReefVision-1.0.3-Windows-Clean-Install-Evidence", "ReefVision-1.0.2-Windows-Clean-Install-Evidence", "evidence artifact"),
        ("-DisposableTest", "-DisposableTest -LiveSam2Acceptance", "network model downloads"),
        ("run: python scripts/check-windows-installer-acceptance-version.py", "run: echo bypass", "preflight must run"),
        ("uninstall 1.0.3", "uninstall 1.0.2", "job label"),
    ],
)
def test_rejects_drift_or_online_checkpoint_acquisition(
    old: str, new: str, diagnostic: str
) -> None:
    changed = fixture().replace(old, new)
    assert changed != fixture()
    assert any(diagnostic in error for error in check_workflow(changed, "1.0.3"))


def test_preflight_must_run_before_packaging() -> None:
    original = fixture()
    moved = original.replace(
        "      - name: Verify installer version before packaging\n"
        "        run: python scripts/check-windows-installer-acceptance-version.py\n"
        "      - name: Build MSI desktop installer with bundled checkpoints",
        "      - name: Build MSI desktop installer with bundled checkpoints\n"
        "      - name: Verify installer version before packaging\n"
        "        run: python scripts/check-windows-installer-acceptance-version.py",
    )
    assert any("before MSI packaging" in error for error in check_workflow(moved, "1.0.3"))

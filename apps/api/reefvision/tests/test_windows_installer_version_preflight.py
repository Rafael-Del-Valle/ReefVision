"""Dynamic Windows installer preflight regression coverage."""

from __future__ import annotations

import pathlib
import runpy

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[4]
check_workflow = runpy.run_path(
    str(ROOT / "scripts/check-windows-installer-acceptance-version.py")
)["check_workflow"]


def fixture() -> str:
    workflow = r"""name: Build Windows Desktop
jobs:
  build-windows-installer:
    outputs:
      release-version: ${{ steps.package-version.outputs.release-version }}
      release-slug: ${{ steps.package-version.outputs.release-slug }}
    steps:
      - uses: actions/setup-python@v5
      - name: Resolve package version
        id: package-version
        run: |
          $config = Get-Content apps/web/src-tauri/tauri.conf.json -Raw | ConvertFrom-Json
          $releaseVersion = [string]$config.version
          "release-version=$releaseVersion" >> $env:GITHUB_OUTPUT
          "release-slug=$($releaseVersion.Replace('.', '-'))" >> $env:GITHUB_OUTPUT
      - name: Check Windows installer version before packaging
        run: python scripts/check-windows-installer-acceptance-version.py
      - name: Build MSI desktop installer with bundled checkpoints
  windows-clean-install-acceptance:
    name: JOB_LABEL
    needs: build-windows-installer
    env:
      REEFVISION_RELEASE_VERSION: ${{ needs.build-windows-installer.outputs.release-version }}
      REEFVISION_RELEASE_SLUG: ${{ needs.build-windows-installer.outputs.release-slug }}
      REEFVISION_PREVIOUS_RELEASE_VERSION: "1.0.2"
      REEFVISION_PREVIOUS_RELEASE_SOURCE_COMMIT: "8d5d10e06b831859cd6e208a7a564780c5f2bd5a"
      REEFVISION_PREVIOUS_PROVENANCE_SHA256: >-
        d20a3df535a0be4f2eadcf6d3e512d1487bc161645e698790505a9c860c2bb60
    steps:
      - uses: actions/download-artifact@v4
        with:
          pattern: ReefVision-Windows-Installer-Part-*
          merge-multiple: true
          path: DOWNLOAD_PATH
      - run: |
          $releaseVersion = $env:REEFVISION_RELEASE_VERSION
          $releaseSlug = $env:REEFVISION_RELEASE_SLUG
          $previousVersion = $env:REEFVISION_PREVIOUS_RELEASE_VERSION
          $previousSourceCommit = $env:REEFVISION_PREVIOUS_RELEASE_SOURCE_COMMIT
          $previousProvenanceHash = $env:REEFVISION_PREVIOUS_PROVENANCE_SHA256
          $folder = Join-Path $env:RUNNER_TEMP "reefvision-$releaseSlug-installer"
          $expectedMsiName = "ReefVision_${releaseVersion}_x64_en-US.msi"
          gh release download "v$previousVersion"
          if ($versionRecord.StringData(1) -ne $releaseVersion) { throw 'bad version' }
          $provenancePath = Join-Path $folder 'build-provenance.json'
          $provenance = Get-Content $provenancePath -Raw | ConvertFrom-Json
          if ($provenance.version -ne $releaseVersion) { throw 'bad provenance version' }
          if ($provenance.source_commit -ne $env:GITHUB_SHA) { throw 'bad source commit' }
          if ($provenance.source_tree_clean -ne $true) { throw 'dirty source' }
          if ($provenance.msi_verified -ne $true) { throw 'unverified MSI' }
          $manifestByName = @{}
          $actualHash = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
          if ($previousProvenance.version -ne $previousVersion) { throw 'bad previous version' }
          if ($previousActualProvenanceHash -ne $previousProvenanceHash) { throw 'bad manifest' }
          if ($previousProvenance.source_commit -ne $previousSourceCommit) {
            throw 'bad previous commit'
          }
          if ($previousActualHash -ne $previousExpectedHash) { throw 'bad previous hash' }
          ./scripts/acceptance-windows-clean-install.ps1 `
            -InstallerPath $msi `
            -AcceptanceRoot "C:\reefvision-$releaseSlug-fresh-install-acceptance" `
            -SkipUpgrade `
            -DisposableTest
          ./scripts/acceptance-windows-clean-install.ps1 `
            -InstallerPath $msi `
            -PreviousInstallerPath $previousMsi `
            -PreviousInstallerSupportsIsolatedAcceptance `
            -AcceptanceRoot "C:\reefvision-$releaseSlug-upgrade-acceptance" `
            -DisposableTest
      - uses: actions/upload-artifact@v4
        with:
          name: EVIDENCE_NAME
"""
    job_label = (
        "Fresh install, upgrade, launch, persist and uninstall "
        "${{ needs.build-windows-installer.outputs.release-version }} on disposable Windows"
    )
    evidence_name = (
        "ReefVision-${{ needs.build-windows-installer.outputs.release-version }}-"
        "Windows-Fresh-Install-And-Upgrade-Evidence"
    )
    download_path = (
        "${{ runner.temp }}/reefvision-"
        "${{ needs.build-windows-installer.outputs.release-slug }}-installer"
    )
    return (
        workflow.replace("JOB_LABEL", job_label)
        .replace("EVIDENCE_NAME", evidence_name)
        .replace("DOWNLOAD_PATH", download_path)
    )


def test_matching_offline_installer_contract() -> None:
    assert check_workflow(fixture(), "1.0.3") == []


def test_split_installer_artifacts_are_reassembled_before_acceptance() -> None:
    workflow = fixture()
    assert "pattern: ReefVision-Windows-Installer-Part-*" in workflow
    assert "merge-multiple: true" in workflow


@pytest.mark.parametrize(
    ("old", "new", "diagnostic"),
    [
        (
            '"ReefVision_${releaseVersion}_x64_en-US.msi"',
            '"ReefVision_1.0.2_x64_en-US.msi"',
            "hardcoded release version",
        ),
        (
            '"reefvision-$releaseSlug-installer"',
            '"reefvision-1-0-2-installer"',
            "hardcoded release version",
        ),
        (
            '"C:\\reefvision-$releaseSlug-fresh-install-acceptance"',
            '"C:\\reefvision-1-0-2-fresh-install-acceptance"',
            "hardcoded release version",
        ),
        (
            "${{ needs.build-windows-installer.outputs.release-version }} on disposable Windows",
            "1.0.2 on disposable Windows",
            "hardcoded release version",
        ),
        (
            "ReefVision-${{ needs.build-windows-installer.outputs.release-version }}-"
            "Windows-Fresh-Install-And-Upgrade-Evidence",
            "ReefVision-1.0.2-Windows-Fresh-Install-And-Upgrade-Evidence",
            "hardcoded release version",
        ),
        ("-DisposableTest", "-DisposableTest -LiveSam2Acceptance", "network model downloads"),
        (
            "run: python scripts/check-windows-installer-acceptance-version.py",
            "run: echo bypass",
            "preflight must run",
        ),
    ],
)
def test_rejects_version_drift_or_online_checkpoint_acquisition(
    old: str, new: str, diagnostic: str
) -> None:
    changed = fixture().replace(old, new)
    assert changed != fixture()
    assert any(diagnostic in error for error in check_workflow(changed, "1.0.3"))


def test_preflight_must_run_before_packaging() -> None:
    original = fixture()
    moved = original.replace(
        "      - name: Check Windows installer version before packaging\n"
        "        run: python scripts/check-windows-installer-acceptance-version.py\n"
        "      - name: Build MSI desktop installer with bundled checkpoints",
        "      - name: Build MSI desktop installer with bundled checkpoints\n"
        "      - name: Check Windows installer version before packaging\n"
        "        run: python scripts/check-windows-installer-acceptance-version.py",
    )
    assert any("before MSI packaging" in error for error in check_workflow(moved, "1.0.3"))

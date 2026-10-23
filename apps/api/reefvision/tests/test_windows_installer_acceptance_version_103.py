"""Regression coverage for the pre-packaging Windows MSI acceptance guard."""

from __future__ import annotations

import importlib.util
import json
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


def test_repository_workflow_matches_tauri_version() -> None:
    config = json.loads(
        (ROOT / "apps" / "web" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    workflow = (ROOT / ".github" / "workflows" / "build-desktop.yml").read_text(encoding="utf-8")

    assert MODULE.check_workflow(workflow, str(config["version"])) == []


def test_repository_workflow_runs_provenance_verified_102_upgrade() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-desktop.yml").read_text(encoding="utf-8")
    clean_job = workflow.split("  windows-clean-install-acceptance:", 1)[1]

    assert 'REEFVISION_PREVIOUS_RELEASE_VERSION: "1.0.2"' in clean_job
    assert "REEFVISION_PREVIOUS_PROVENANCE_SHA256" in clean_job
    assert 'gh release download "v$previousVersion"' in clean_job
    assert "$previousProvenance.version -ne $previousVersion" in clean_job
    assert "$previousActualHash -ne $previousExpectedHash" in clean_job
    assert "-PreviousInstallerPath $previousMsi" in clean_job
    assert "-PreviousInstallerSupportsIsolatedAcceptance" in clean_job
    assert "-SkipUpgrade" not in clean_job


def valid_workflow() -> str:
    workflow = r"""name: Build Windows Desktop
  historical_document: docs/RELEASE_1.0.2.md
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
          if ($releaseVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'bad version' }
          "release-version=$releaseVersion" >> $env:GITHUB_OUTPUT
          "release-slug=$($releaseVersion.Replace('.', '-'))" >> $env:GITHUB_OUTPUT
      - name: Check Windows installer version before packaging
        run: python scripts/check-windows-installer-acceptance-version.py
      - name: Build MSI desktop installer with bundled checkpoints
        run: npm run build:desktop
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
      - run: |
          $releaseVersion = $env:REEFVISION_RELEASE_VERSION
          $releaseSlug = $env:REEFVISION_RELEASE_SLUG
          $previousVersion = $env:REEFVISION_PREVIOUS_RELEASE_VERSION
          $previousSourceCommit = $env:REEFVISION_PREVIOUS_RELEASE_SOURCE_COMMIT
          $previousProvenanceHash = $env:REEFVISION_PREVIOUS_PROVENANCE_SHA256
          $folder = Join-Path $env:RUNNER_TEMP "reefvision-$releaseSlug-installer"
          $expectedMsiName = "ReefVision_${releaseVersion}_x64_en-US.msi"
          gh release download "v$previousVersion"
          if ($msi[0].Name -ne $expectedMsiName) { throw 'bad' }
          if ($versionRecord.StringData(1) -ne $releaseVersion) { throw 'bad' }
          $provenancePath = Join-Path $folder 'build-provenance.json'
          $provenance = Get-Content $provenancePath -Raw | ConvertFrom-Json
          if ($provenance.version -ne $releaseVersion) { throw 'bad provenance version' }
          if ($provenance.source_commit -ne $env:GITHUB_SHA) { throw 'bad source commit' }
          if ($provenance.source_tree_clean -ne $true) { throw 'dirty source' }
          if ($provenance.msi_verified -ne $true) { throw 'unverified msi' }
          $manifestByName = @{}
          $actualHash = (
            Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256
          ).Hash.ToLowerInvariant()
          if ($previousProvenance.version -ne $previousVersion) { throw 'bad previous version' }
          if ($previousActualProvenanceHash -ne $previousProvenanceHash) { throw 'bad manifest' }
          if ($previousProvenance.source_commit -ne $previousSourceCommit) {
            throw 'bad previous commit'
          }
          if ($previousActualHash -ne $previousExpectedHash) { throw 'bad previous hash' }
          -PreviousInstallerPath $previousMsi
          -PreviousInstallerSupportsIsolatedAcceptance
          -AcceptanceRoot "C:\reefvision-$releaseSlug-disposable-acceptance"
      - name: Upload evidence
        uses: actions/upload-artifact@v4
        with:
          name: EVIDENCE_NAME
"""
    job_label = (
        "Install, launch, persist and uninstall "
        "${{ needs.build-windows-installer.outputs.release-version }} on fresh Windows"
    )
    evidence_name = (
        "ReefVision-${{ needs.build-windows-installer.outputs.release-version }}-"
        "Windows-Clean-Install-Evidence"
    )
    return workflow.replace("JOB_LABEL", job_label).replace("EVIDENCE_NAME", evidence_name)


def test_matching_installer_and_acceptance_version_pass() -> None:
    assert MODULE.check_workflow(valid_workflow(), "1.0.3") == []


def test_historical_release_notes_outside_acceptance_job_are_allowed() -> None:
    assert (
        MODULE.check_workflow(
            valid_workflow().replace("RELEASE_1.0.2.md", "RELEASE_1.0.0.md"), "1.0.3"
        )
        == []
    )


@pytest.mark.parametrize(
    "stale_reference",
    [
        "ReefVision_1.0.2_x64_en-US.msi",
        "MSI ProductVersion must be 1.0.2.",
        "reefvision-1-0-2-installer",
        "Install, launch, persist and uninstall 1.0.2 on fresh Windows",
        "ReefVision-1.0.2-Windows-Clean-Install-Evidence",
        "reefvision-1-0-2-disposable-acceptance",
    ],
)
def test_stale_version_reference_is_rejected(stale_reference: str) -> None:
    workflow = valid_workflow() + f"      # {stale_reference}\n"
    assert any(
        "hardcoded release version" in error for error in MODULE.check_workflow(workflow, "1.0.3")
    )


def test_default_acceptance_rejects_implicit_live_model_downloads() -> None:
    workflow = valid_workflow().replace(
        "      - name: Upload evidence",
        "          -LiveSam2Acceptance\n      - name: Upload evidence",
    )
    assert any(
        "network model downloads" in error for error in MODULE.check_workflow(workflow, "1.0.3")
    )


def test_missing_clean_install_job_is_rejected() -> None:
    assert any(
        "exactly one" in error
        for error in MODULE.check_workflow("name: Build Windows Desktop", "1.0.3")
    )


@pytest.mark.parametrize(
    "required_fragment",
    [
        "REEFVISION_PREVIOUS_RELEASE_VERSION",
        "REEFVISION_PREVIOUS_RELEASE_SOURCE_COMMIT",
        "REEFVISION_PREVIOUS_PROVENANCE_SHA256",
        'gh release download "v$previousVersion"',
        "$previousActualProvenanceHash -ne $previousProvenanceHash",
        "$previousProvenance.version -ne $previousVersion",
        "$previousProvenance.source_commit -ne $previousSourceCommit",
        "$previousActualHash -ne $previousExpectedHash",
        "-PreviousInstallerPath $previousMsi",
        "-PreviousInstallerSupportsIsolatedAcceptance",
    ],
)
def test_missing_upgrade_guard_is_rejected(required_fragment: str) -> None:
    workflow = valid_workflow().replace(required_fragment, "REMOVED")
    assert any("upgrade" in error.lower() for error in MODULE.check_workflow(workflow, "1.0.3"))


def test_skipped_upgrade_is_rejected() -> None:
    workflow = valid_workflow().replace(
        "-PreviousInstallerSupportsIsolatedAcceptance",
        "-PreviousInstallerSupportsIsolatedAcceptance -SkipUpgrade",
    )
    assert any("must not be skipped" in error for error in MODULE.check_workflow(workflow, "1.0.3"))


def test_invalid_release_version_is_rejected() -> None:
    assert any(
        "Invalid Tauri version" in error
        for error in MODULE.check_workflow(valid_workflow(), "1.0.3-rc1")
    )


def test_mixed_msi_versions_are_rejected() -> None:
    workflow = valid_workflow() + "      # ReefVision_1.0.2_x64_en-US.msi\n"
    assert any(
        "hardcoded release version" in error for error in MODULE.check_workflow(workflow, "1.0.3")
    )


@pytest.mark.parametrize(
    "required_fragment",
    [
        "source_commit",
        "source_tree_clean",
        "msi_verified",
        "Get-FileHash",
        "build-provenance.json",
    ],
)
def test_missing_provenance_guard_is_rejected(required_fragment: str) -> None:
    workflow = valid_workflow().replace(required_fragment, "REMOVED")
    assert any("provenance" in error.lower() for error in MODULE.check_workflow(workflow, "1.0.3"))

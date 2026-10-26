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


def test_cab_upload_partitions_are_complete_and_bounded() -> None:
    """Every generated cabinet must be uploaded without oversized artifact parts."""
    workflow = (ROOT / ".github" / "workflows" / "build-desktop.yml").read_text(encoding="utf-8")
    build_job = workflow.split("  build-windows-installer:", 1)[1].split(
        "  windows-clean-install-acceptance:", 1
    )[0]
    assert "$actual.Count -notin @(5, 6)" in build_job
    assert '$expected = @(1..$actual.Count | ForEach-Object { "rv$_.cab" })' in build_job
    assert "if ($bytes -ge 2GB)" in build_job
    assert "MSI before artifact upload" in build_job
    assert MODULE.check_cab_artifact_partition(workflow) == []


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
    assert clean_job.count("-SkipUpgrade") == 1
    assert clean_job.count("-InstallerPath $msi") == 2
    assert '"C:\\reefvision-$releaseSlug-fresh-install-acceptance"' in clean_job
    assert '"C:\\reefvision-$releaseSlug-upgrade-acceptance"' in clean_job


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
          -InstallerPath $msi
          -AcceptanceRoot "C:\reefvision-$releaseSlug-fresh-install-acceptance"
          -SkipUpgrade
          -DisposableTest
          -InstallerPath $msi
          -PreviousInstallerPath $previousMsi
          -PreviousInstallerSupportsIsolatedAcceptance
          -AcceptanceRoot "C:\reefvision-$releaseSlug-upgrade-acceptance"
          -DisposableTest
      - name: Upload evidence
        uses: actions/upload-artifact@v4
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
        "Fresh install, upgrade, launch, persist and uninstall 1.0.2 on disposable Windows",
        "ReefVision-1.0.2-Windows-Fresh-Install-And-Upgrade-Evidence",
        "reefvision-1-0-2-fresh-install-acceptance",
        "reefvision-1-0-2-upgrade-acceptance",
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


def test_missing_candidate_only_fresh_install_is_rejected() -> None:
    workflow = valid_workflow().replace("-SkipUpgrade", "REMOVED")
    assert any(
        "fresh install" in error.lower() for error in MODULE.check_workflow(workflow, "1.0.3")
    )


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


CAB_WORKFLOW = (ROOT / ".github/workflows/build-desktop.yml").read_text(encoding="utf-8")


def test_windows_cab_guard_accepts_five_or_six_contiguous_cabinets() -> None:
    """CAB counts vary with payload size; the MSI Media table remains authoritative."""
    assert "$actual.Count -notin @(5, 6)" in CAB_WORKFLOW
    assert '$expected = @(1..$actual.Count | ForEach-Object { "rv$_.cab" })' in CAB_WORKFLOW
    assert "MSI-declared cabinet payload" in CAB_WORKFLOW

    modified = CAB_WORKFLOW.replace(
        "$lastPartitionCabs = @($actual | Where-Object { $_ -in @('rv5.cab', 'rv6.cab') })",
        "$lastPartitionCabs = @('rv5.cab', 'rv6.cab')",
        1,
    )
    assert any(
        "derive its final size-check partition" in error
        for error in MODULE.check_cab_artifact_partition(modified)
    )


def test_windows_cab_artifact_manifest_preflight_matches_real_workflow() -> None:
    assert MODULE.check_cab_artifact_partition(CAB_WORKFLOW) == []


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("msi/rv4.cab", "msi/rv3.cab"),
        ("msi/rv6.cab", "msi/rv7.cab"),
        ("name: ReefVision-Windows-Installer-Part-3", "name: ReefVision-Windows-Installer-Part-2"),
        ("pattern: ReefVision-Windows-Installer-Part-*", "pattern: unrelated-*"),
        ("merge-multiple: true", "merge-multiple: false"),
        ("msi/*.msi", "msi/incorrect.msi"),
    ],
)
def test_windows_cab_preflight_rejects_missing_or_duplicated_artifacts(
    original: str, replacement: str
) -> None:
    assert original in CAB_WORKFLOW
    modified = CAB_WORKFLOW.replace(original, replacement, 1)
    assert MODULE.check_cab_artifact_partition(modified)


def test_windows_cab_preflight_requires_missing_file_upload_failure() -> None:
    assert "if-no-files-found: error" in CAB_WORKFLOW
    modified = CAB_WORKFLOW.replace("if-no-files-found: error", "if-no-files-found: warn", 1)
    assert any(
        "must reject missing upload files" in error
        for error in MODULE.check_cab_artifact_partition(modified)
    )


def test_windows_cab_preflight_rejects_removed_msi_media_verification() -> None:
    for required in (
        "$database.OpenView('SELECT `Cabinet` FROM `Media`')",
        "$missing = @($requiredCabs | Where-Object { $_ -notin $actualCabs })",
        "$unexpected = @($actualCabs | Where-Object { $_ -notin $requiredCabs })",
    ):
        assert required in CAB_WORKFLOW
        modified = CAB_WORKFLOW.replace(required, "# removed", 1)
        assert any(
            "must verify MSI Media table" in error
            for error in MODULE.check_cab_artifact_partition(modified)
        )

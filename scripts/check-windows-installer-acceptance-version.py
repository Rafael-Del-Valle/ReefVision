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
    hardcoded_patterns = (
        r"ReefVision_\d+\.\d+\.\d+_x64_en-US\.msi",
        r"MSI ProductVersion must be \d+\.\d+\.\d+\.",
        r"reefvision-\d+-\d+-\d+-(?:installer|fresh-install-acceptance|upgrade-acceptance)",
        r"Fresh install, upgrade, launch, persist and uninstall "
        r"\d+\.\d+\.\d+ on disposable Windows",
        r"ReefVision-\d+\.\d+\.\d+-Windows-Fresh-Install-And-Upgrade-Evidence",
    )
    hardcoded = sorted(
        {match.group(0) for pattern in hardcoded_patterns for match in re.finditer(pattern, job)}
    )
    if hardcoded:
        errors.append(
            f"Clean-install job contains hardcoded release version references: {hardcoded!r}"
        )

    build_marker = "  build-windows-installer:"
    if workflow.count(build_marker) != 1:
        errors.append("Expected exactly one Windows installer build job")
        build_job = ""
    else:
        build_job = workflow.split(build_marker, 1)[1].split(marker, 1)[0]

    required_build_fragments = (
        "release-version: ${{ steps.package-version.outputs.release-version }}",
        "release-slug: ${{ steps.package-version.outputs.release-slug }}",
        "id: package-version",
        "apps/web/src-tauri/tauri.conf.json",
        "ConvertFrom-Json",
        "release-version=$releaseVersion",
        "release-slug=$($releaseVersion.Replace('.', '-'))",
        "$env:GITHUB_OUTPUT",
    )
    for fragment in required_build_fragments:
        if fragment not in build_job:
            errors.append(f"Dynamic package version output is missing: {fragment}")

    required_clean_fragments = (
        "Fresh install, upgrade, launch, persist and uninstall "
        "${{ needs.build-windows-installer.outputs.release-version }} on disposable Windows",
        "REEFVISION_RELEASE_VERSION: ${{ needs.build-windows-installer.outputs.release-version }}",
        "REEFVISION_RELEASE_SLUG: ${{ needs.build-windows-installer.outputs.release-slug }}",
        '"reefvision-$releaseSlug-installer"',
        '"ReefVision_${releaseVersion}_x64_en-US.msi"',
        "$versionRecord.StringData(1) -ne $releaseVersion",
        '"C:\\reefvision-$releaseSlug-fresh-install-acceptance"',
        "ReefVision-${{ needs.build-windows-installer.outputs.release-version }}-"
        "Windows-Fresh-Install-And-Upgrade-Evidence",
    )
    for fragment in required_clean_fragments:
        if fragment not in job:
            errors.append(f"Dynamic clean-install version use is missing: {fragment}")

    required_provenance_fragments = (
        "build-provenance.json",
        "$provenance.version -ne $releaseVersion",
        "$provenance.source_commit -ne $env:GITHUB_SHA",
        "$provenance.source_tree_clean -ne $true",
        "$provenance.msi_verified -ne $true",
        "$manifestByName",
        "Get-FileHash",
    )
    for fragment in required_provenance_fragments:
        if fragment not in job:
            errors.append(f"Installer provenance guard is missing: {fragment}")

    required_upgrade_fragments = (
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
        '"C:\\reefvision-$releaseSlug-upgrade-acceptance"',
    )
    for fragment in required_upgrade_fragments:
        if fragment not in job:
            errors.append(f"Previous-release upgrade guard is missing: {fragment}")
    if job.count("-InstallerPath $msi") != 2:
        errors.append("Fresh install and upgrade must each invoke the candidate installer")
    if job.count("-SkipUpgrade") != 1:
        errors.append("Candidate-only fresh install must skip the upgrade phase exactly once")
    if job.count("-DisposableTest") != 2:
        errors.append("Fresh install and upgrade must each run in disposable mode")

    if "-LiveSam2Acceptance" in job:
        errors.append("Default clean-install job must not opt into network model downloads")
    if build_job:
        invocation = "run: python scripts/check-windows-installer-acceptance-version.py"
        packaging = "- name: Build MSI desktop installer with bundled checkpoints"
        if build_job.count(invocation) != 1:
            errors.append("Version preflight must run exactly once in Windows build job")
        elif packaging not in build_job or build_job.index(invocation) > build_job.index(packaging):
            errors.append("Version preflight must run before MSI packaging")
        elif "actions/setup-python@v5" not in build_job[: build_job.index(invocation)]:
            errors.append("Version preflight must run after Python setup")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "apps/web/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    workflow = (root / ".github/workflows/build-desktop.yml").read_text(encoding="utf-8")
    errors = check_workflow(workflow, str(config["version"]))
    if errors:
        for error in errors:
            print(f"Windows acceptance version gate: {error}", file=sys.stderr)
        return 1
    print(f"Windows clean-install version gate passed: {config['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

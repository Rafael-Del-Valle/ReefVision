"""Verify that the Windows clean-install job targets the packaged Tauri version.

Run before MSI packaging to catch expensive version-mismatch failures.
This check does not execute an installer or initiate model downloads.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _job_section(workflow: str, job_name: str) -> str:
    marker = f"  {job_name}:"
    if workflow.count(marker) != 1:
        return ""
    section = workflow.split(marker, 1)[1]
    next_job = re.search(r"(?m)^  [a-z0-9][a-z0-9-]*:\s*$", section)
    return section[: next_job.start()] if next_job is not None else section


def _check_split_release_candidate_workflow(workflow: str, version: str) -> list[str]:
    """Validate the 1.1+ split fresh-install and published-upgrade jobs."""

    errors: list[str] = []
    build_job = _job_section(workflow, "build-windows-installer")
    clean_job = _job_section(workflow, "windows-clean-install-acceptance")
    upgrade_job = _job_section(workflow, "windows-upgrade-acceptance")
    if not build_job:
        errors.append("Expected exactly one Windows installer build job")
    if not clean_job:
        errors.append("Expected exactly one Windows clean-install job")
    if not upgrade_job:
        errors.append("Expected exactly one Windows upgrade job")
    if errors:
        return errors

    required_build_fragments = (
        "release-version: ${{ steps.package-version.outputs.release-version }}",
        "release-slug: ${{ steps.package-version.outputs.release-slug }}",
        "id: package-version",
        "apps/web/src-tauri/tauri.conf.json",
        "ConvertFrom-Json",
        "release-version=$releaseVersion",
        "release-slug=$($releaseVersion.Replace('.', '-'))",
        "$env:GITHUB_OUTPUT",
        "SOURCE_COMMIT: ${{ github.event.pull_request.head.sha || github.sha }}",
    )
    for fragment in required_build_fragments:
        if fragment not in build_job:
            errors.append(f"Dynamic package version output is missing: {fragment}")

    invocation = "run: python scripts/check-windows-installer-acceptance-version.py"
    packaging = "npm run build:desktop"
    if build_job.count(invocation) != 1:
        errors.append("Version preflight must run exactly once in Windows build job")
    elif packaging not in build_job or build_job.index(invocation) > build_job.index(packaging):
        errors.append("Version preflight must run before MSI packaging")
    elif "actions/setup-python@v5" not in build_job[: build_job.index(invocation)]:
        errors.append("Version preflight must run after Python setup")

    current_slug = version.replace(".", "-")
    required_clean_fragments = (
        f"Fresh install, launch, persist and uninstall {version} on disposable Windows",
        "SOURCE_COMMIT: ${{ github.event.pull_request.head.sha || github.sha }}",
        f"pattern: ReefVision-{version}-RC-Installer-Part-*",
        "merge-multiple: true",
        "./scripts/verify-windows-installer-payload.ps1",
        f"-Version '{version}'",
        f"-ExpectedFilename 'ReefVision_{version}_x64_en-US.msi'",
        "-SourceCommit $env:SOURCE_COMMIT -RequireProvenance",
        "./scripts/acceptance-windows-clean-install.ps1",
        f"-ExpectedVersion '{version}'",
        f"-AcceptanceRoot 'C:\\reefvision-{current_slug}-disposable-acceptance'",
        "-SkipUpgrade -DisposableTest -KeepArtifacts",
    )
    for fragment in required_clean_fragments:
        if fragment not in clean_job:
            errors.append(f"Clean-install release guard is missing: {fragment}")

    upgrade_match = re.search(
        rf"name: Upgrade (\d+\.\d+\.\d+) to {re.escape(version)} and preserve the project",
        upgrade_job,
    )
    previous_version = upgrade_match.group(1) if upgrade_match is not None else ""
    if not previous_version:
        errors.append("Published previous-release upgrade version is missing")
    required_upgrade_fragments = (
        "SOURCE_COMMIT: ${{ github.event.pull_request.head.sha || github.sha }}",
        f"pattern: ReefVision-{version}-RC-Installer-Part-*",
        "merge-multiple: true",
        "./scripts/verify-windows-installer-payload.ps1",
        f"-Version '{version}'",
        f"-ExpectedFilename 'ReefVision_{version}_x64_en-US.msi'",
        "-SourceCommit $env:SOURCE_COMMIT -RequireProvenance",
        "gh release download v1.0.3",
        "Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256",
        "fc5dfd8ce3fd8e4d1ea9d3040d139aff1304c472b42d671262ef0077c119505d",
        "$manifest.version -ne '1.0.3'",
        "$manifest.source_commit -ne 'e94dad6a3bece7b776bf45776bc5d06cfbc2c0dc'",
        "$manifest.source_tree_clean -ne $true",
        "$manifest.msi_verified -ne $true",
        "Compare-Object $expected $actual",
        "-PreviousInstallerPath $previousMsi",
        "-PreviousInstallerSupportsIsolatedAcceptance",
        f"-ExpectedVersion '{version}'",
        f"-AcceptanceRoot 'C:\\reefvision-{current_slug}-upgrade-acceptance'",
        "-DisposableTest -KeepArtifacts",
    )
    for fragment in required_upgrade_fragments:
        if fragment not in upgrade_job:
            errors.append(f"Previous-release upgrade guard is missing: {fragment}")

    clean_versions = set(re.findall(r"\d+\.\d+\.\d+", clean_job))
    unexpected_clean = clean_versions - {version}
    if unexpected_clean:
        errors.append(
            f"Clean-install job contains stale release versions: {sorted(unexpected_clean)!r}"
        )
    upgrade_versions = set(re.findall(r"\d+\.\d+\.\d+", upgrade_job))
    allowed_upgrade_versions = {version, previous_version} if previous_version else {version}
    unexpected_upgrade = upgrade_versions - allowed_upgrade_versions
    if unexpected_upgrade:
        errors.append(
            f"Upgrade job contains unexpected release versions: {sorted(unexpected_upgrade)!r}"
        )
    if "-LiveSam2Acceptance" in clean_job or "-LiveSam2Acceptance" in upgrade_job:
        errors.append("Default Windows acceptance must not opt into network model downloads")
    return errors


def check_workflow(workflow: str, version: str) -> list[str]:
    errors: list[str] = []
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        return [f"Invalid Tauri version: {version!r}"]

    if "  windows-upgrade-acceptance:" in workflow:
        return _check_split_release_candidate_workflow(workflow, version)

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


def check_cab_artifact_partition(workflow: str) -> list[str]:
    """Fail before MSI packaging if an external CAB cannot reach the install runner.

    WiX currently emits five or six external cabinets as dependency sizes vary.
    Verify the three artifact manifests explicitly, require the build-time size
    check to use the actual final CAB set, and reject missing/duplicated parts.
    """
    errors: list[str] = []
    build_marker = "  build-windows-installer:"
    acceptance_marker = "  windows-clean-install-acceptance:"
    if build_marker not in workflow or acceptance_marker not in workflow:
        return ["Missing Windows build or clean-install job for CAB partition preflight"]

    build_job = workflow.split(build_marker, 1)[1].split(acceptance_marker, 1)[0]
    acceptance_job = workflow.split(acceptance_marker, 1)[1]
    if "Partition verified installer for artifact transport" in build_job:
        dynamic_checks = (
            "$payload = ./scripts/verify-windows-installer-payload.ps1",
            "-SourceCommit $env:SOURCE_COMMIT -RequireProvenance",
            "$parts = [System.Collections.Generic.List[object]]::new()",
            "foreach ($entry in $payload.files)",
            "if ($entry.size_bytes -ge 2GB)",
            "if ($partBytes + $entry.size_bytes -ge 2GB)",
            "if ($parts.Count -gt 4)",
            '"part$($i + 1)<<EOF" >> $env:GITHUB_OUTPUT',
        )
        if any(marker not in build_job for marker in dynamic_checks):
            errors.append(
                "Windows build must partition every verified payload file below the transport limit"
            )

        artifact_version_match = re.search(
            r"name: ReefVision-(\d+\.\d+\.\d+)-RC-Installer-Part-1", build_job
        )
        artifact_version = artifact_version_match.group(1) if artifact_version_match else ""
        if not artifact_version:
            errors.append("Installer artifact part 1 must identify the release version")
        for part in range(1, 5):
            name = f"name: ReefVision-{artifact_version}-RC-Installer-Part-{part}"
            path = f"path: ${{{{ steps.payload.outputs.part{part} }}}}"
            if build_job.count(name) != 1 or build_job.count(path) != 1:
                errors.append(
                    f"Installer artifact part {part} must map to payload output part{part}"
                )
            if part > 1 and f"if: steps.payload.outputs.part{part} != ''" not in build_job:
                errors.append(
                    f"Optional installer artifact part {part} must be conditionally uploaded"
                )
        artifact_steps = re.split(r"(?m)^      - uses: actions/upload-artifact@v4\s*$", build_job)[
            1:
        ]
        installer_steps = [step for step in artifact_steps if "RC-Installer-Part-" in step]
        if len(installer_steps) != 4:
            errors.append(
                f"Expected four installer artifact upload slots; found {len(installer_steps)}"
            )
        for index, step in enumerate(installer_steps, start=1):
            if "if-no-files-found: error" not in step:
                errors.append(f"Installer artifact part {index} must reject missing upload files")

        clean_job = _job_section(workflow, "windows-clean-install-acceptance")
        upgrade_job = _job_section(workflow, "windows-upgrade-acceptance")
        for label, job in (("Clean-install", clean_job), ("Upgrade", upgrade_job)):
            if f"pattern: ReefVision-{artifact_version}-RC-Installer-Part-*" not in job or (
                "merge-multiple: true" not in job
            ):
                errors.append(f"{label} runner must download and merge all installer parts")
            candidate_verification = re.search(
                r"(?m)^\s*\$\w+ = \./scripts/verify-windows-installer-payload\.ps1 "
                r"[^\r\n]*-SourceCommit \$env:SOURCE_COMMIT -RequireProvenance\s*$",
                job,
            )
            if candidate_verification is None:
                errors.append(
                    f"{label} runner must verify MSI Media, provenance, and every external CAB"
                )
        return errors

    expected = {
        "ReefVision-Windows-Installer-Part-1": {"rv1.cab", "rv2.cab"},
        "ReefVision-Windows-Installer-Part-2": {"rv3.cab", "rv4.cab"},
        "ReefVision-Windows-Installer-Part-3": {"rv5.cab", "rv6.cab"},
    }
    uploads = [
        step
        for step in re.split(r"(?m)^      - name: ", build_job)
        if step.startswith("Upload Windows installer ")
    ]
    if len(uploads) != len(expected):
        errors.append(f"Expected three installer artifact uploads; found {len(uploads)}")

    seen: set[str] = set()
    for step in uploads:
        names = re.findall(
            r"(?m)^          name: (ReefVision-Windows-Installer-Part-\d+)\s*$",
            step,
        )
        if len(names) != 1 or names[0] not in expected or names[0] in seen:
            errors.append(f"Invalid or duplicate installer artifact name: {names!r}")
            continue
        name = names[0]
        seen.add(name)
        cabs = re.findall(
            r"(?m)^            apps/web/src-tauri/target/x86_64-pc-windows-msvc/"
            r"release/bundle/msi/(rv\d+\.cab)\s*$",
            step,
        )
        if len(cabs) != len(set(cabs)) or set(cabs) != expected[name]:
            errors.append(
                f"{name} CAB manifest mismatch: found {cabs!r}, expected {sorted(expected[name])!r}"
            )
        msi_paths = re.findall(
            r"(?m)^            apps/web/src-tauri/target/x86_64-pc-windows-msvc/"
            r"release/bundle/msi/\*\.msi\s*$",
            step,
        )
        if len(msi_paths) != (1 if name.endswith("Part-1") else 0):
            errors.append(f"{name} MSI manifest must appear only in Part-1")
        if "if-no-files-found: error" not in step:
            errors.append(f"{name} must reject missing upload files")

    if seen != set(expected):
        errors.append(f"Installer artifact parts mismatch: found {sorted(seen)!r}")
    dynamic_partition_checks = (
        "$actual.Count -notin @(5, 6)",
        '$expected = @(1..$actual.Count | ForEach-Object { "rv$_.cab" })',
        "$lastPartitionCabs = @($actual | Where-Object { $_ -in @('rv5.cab', 'rv6.cab') })",
        "@{ Name = 'Part-3'; Files = $lastPartitionCabs }",
    )
    if any(marker not in build_job for marker in dynamic_partition_checks):
        errors.append(
            "Windows build must derive its final size-check partition from the actual CAB set"
        )
    if (
        "pattern: ReefVision-Windows-Installer-Part-*" not in acceptance_job
        or "merge-multiple: true" not in acceptance_job
    ):
        errors.append("Clean-install runner must download and merge all installer parts")
    # Upload manifests alone are insufficient: independently compare the MSI
    # Media table to the exact CAB set before running an installer.
    media_checks = (
        "$database.OpenView('SELECT `Cabinet` FROM `Media`')",
        "$missing = @($requiredCabs | Where-Object { $_ -notin $actualCabs })",
        "$unexpected = @($actualCabs | Where-Object { $_ -notin $requiredCabs })",
        "if ($missing.Count -gt 0 -or $unexpected.Count -gt 0 -or "
        "$actualCabs.Count -ne $requiredCabs.Count)",
    )
    if any(marker not in acceptance_job for marker in media_checks):
        errors.append("Clean-install runner must verify MSI Media table against all external CABs")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "apps/web/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    workflow = (root / ".github/workflows/build-desktop.yml").read_text(encoding="utf-8")
    errors = check_workflow(workflow, str(config["version"]))
    errors.extend(check_cab_artifact_partition(workflow))
    if errors:
        for error in errors:
            print(f"Windows acceptance version gate: {error}", file=sys.stderr)
        return 1
    print(f"Windows clean-install version gate passed: {config['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

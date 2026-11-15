"""Check the Windows installer workflow against the packaged Tauri version.

Run before MSI packaging to catch expensive version-mismatch failures.
This check does not execute an installer or initiate model downloads.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_BUILD_JOB = "build-windows-installer"
_CLEAN_JOB = "windows-clean-install-acceptance"
_UPGRADE_JOB = "windows-upgrade-acceptance"
_BASELINE_VERSION = "1.0.3"
_BASELINE_REPOSITORY = "Rafael-Del-Valle/ReefVision"
_BASELINE_COMMIT = "e94dad6a3bece7b776bf45776bc5d06cfbc2c0dc"
_BASELINE_MANIFEST_SHA256 = "fc5dfd8ce3fd8e4d1ea9d3040d139aff1304c472b42d671262ef0077c119505d"
_PREFLIGHT = "run: python scripts/check-windows-installer-acceptance-version.py"
_VERIFIER = "./scripts/verify-windows-installer-payload.ps1"
_SOURCE_COMMIT = "${{ github.event.pull_request.head.sha || github.sha }}"
_ROOT = Path(__file__).resolve().parents[1]


def _job(workflow: str, name: str) -> str:
    jobs = re.findall(rf"(?ms)^  {re.escape(name)}:\s*\n(.*?)(?=^  [\w-]+:|\Z)", workflow)
    return jobs[0] if len(jobs) == 1 else ""


def _split_workflow(workflow: str) -> bool:
    return f"  {_UPGRADE_JOB}:" in workflow or _VERIFIER in workflow


def _missing(text: str, fragments: tuple[str, ...], message: str) -> list[str]:
    # Comments cannot stand in for executable guards or workflow settings.
    active = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return [f"{message}: {fragment}" for fragment in fragments if fragment not in active]


def _check_preflight_order(build_job: str, packaging: str) -> list[str]:
    if build_job.count(_PREFLIGHT) != 1:
        return ["Version preflight must run exactly once in Windows build job"]
    if packaging not in build_job or build_job.index(_PREFLIGHT) > build_job.index(packaging):
        return ["Version preflight must run before MSI packaging"]
    if "actions/setup-python@v5" not in build_job[: build_job.index(_PREFLIGHT)]:
        return ["Version preflight must run after Python setup"]
    return []


def _check_split_workflow(workflow: str, version: str) -> list[str]:
    build = _job(workflow, _BUILD_JOB)
    clean = _job(workflow, _CLEAN_JOB)
    upgrade = _job(workflow, _UPGRADE_JOB)
    if not (build and clean and upgrade):
        return ["Expected exactly one Windows build, clean-install, and upgrade job each"]

    msi = f"ReefVision_{version}_x64_en-US.msi"
    slug = version.replace(".", "-")
    verified_candidate = (
        f"{_VERIFIER} -InstallerDirectory $folder -Version '{version}' "
        f"-ExpectedFilename '{msi}' -SourceCommit $env:SOURCE_COMMIT -RequireProvenance"
    )
    errors = _check_preflight_order(build, f"- name: Build weight-free {version} desktop installer")
    for name, job in ((_BUILD_JOB, build), (_CLEAN_JOB, clean), (_UPGRADE_JOB, upgrade)):
        errors.extend(
            _missing(
                job,
                (
                    f"ref: {_SOURCE_COMMIT}",
                    f"SOURCE_COMMIT: {_SOURCE_COMMIT}",
                    verified_candidate,
                ),
                f"{name} candidate provenance guard is missing",
            )
        )
        if "-LiveSam2Acceptance" in job:
            errors.append(f"{name} must not opt into network model downloads")

    for name, job, label, msi_assignment, root, evidence in (
        (
            _CLEAN_JOB,
            clean,
            f"Fresh install, launch, persist and uninstall {version} on disposable Windows",
            f"$msi = Join-Path $folder '{msi}'",
            "disposable-acceptance",
            "Clean-Install",
        ),
        (
            _UPGRADE_JOB,
            upgrade,
            f"Upgrade {_BASELINE_VERSION} to {version} "
            "and preserve the project on disposable Windows",
            rf"$msi = Join-Path $env:RUNNER_TEMP 'reefvision-{slug}-installer\{msi}'",
            "upgrade-acceptance",
            "Upgrade",
        ),
    ):
        errors.extend(
            _missing(
                job,
                (
                    f"name: {label}",
                    f"needs: {_BUILD_JOB}",
                    f"$folder = Join-Path $env:RUNNER_TEMP 'reefvision-{slug}-installer'",
                    msi_assignment,
                    "-InstallerPath $msi",
                    f"-ExpectedVersion '{version}'",
                    rf"-AcceptanceRoot 'C:\reefvision-{slug}-{root}'",
                    "-DisposableTest",
                    f"name: ReefVision-{version}-RC-Windows-{evidence}-Evidence",
                ),
                f"{name} candidate installer wiring is missing",
            )
        )
        if job.count("-InstallerPath $msi") != 1:
            errors.append(f"{name} must exercise the candidate installer exactly once")
        if (
            verified_candidate in job
            and "-InstallerPath $msi" in job
            and job.index(verified_candidate) > job.index("-InstallerPath $msi")
        ):
            errors.append(f"{name} must verify candidate provenance before installation")

    if clean.count("-SkipUpgrade") != 1 or "-SkipUpgrade" in upgrade:
        errors.append("Candidate-only fresh install must skip the upgrade phase exactly once")
    baseline_msi = f"ReefVision_{_BASELINE_VERSION}_x64_en-US.msi"
    download = f"gh release download v{_BASELINE_VERSION} --repo {_BASELINE_REPOSITORY}"
    baseline_folder = rf"reefvision-{_BASELINE_VERSION.replace('.', '-')}-installer"
    baseline_checks = "if (Compare-Object $expected $actual) { throw "
    errors.extend(
        _missing(
            upgrade,
            (
                f"{download} --pattern build-provenance.json --dir $previous",
                f"{download} --pattern '{baseline_msi}' --pattern 'rv*.cab' --dir $previous",
                "$digest = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash",
                f"$digest -ine '{_BASELINE_MANIFEST_SHA256}'",
                f"$manifest.version -ne '{_BASELINE_VERSION}'",
                f"$manifest.source_commit -ne '{_BASELINE_COMMIT}'",
                "$manifest.source_tree_clean -ne $true",
                "$manifest.msi_verified -ne $true",
                f"{_VERIFIER} -InstallerDirectory $previous -Version '{_BASELINE_VERSION}' "
                f"-ExpectedFilename '{baseline_msi}'",
                '$expected = @($manifest.files | ForEach-Object { "$($_.name) $($_.sha256)" }',
                '$actual = @($payload.files | ForEach-Object { "$($_.name) $($_.sha256)" }',
                baseline_checks,
                f"$previous = Join-Path $env:RUNNER_TEMP '{baseline_folder}'",
                rf"$previousMsi = Join-Path $env:RUNNER_TEMP '{baseline_folder}\{baseline_msi}'",
                "-PreviousInstallerPath $previousMsi",
                "-PreviousInstallerSupportsIsolatedAcceptance",
            ),
            "Previous-release upgrade baseline guard is missing",
        )
    )
    if (
        baseline_checks in upgrade
        and "-PreviousInstallerPath $previousMsi" in upgrade
        and upgrade.index(baseline_checks) > upgrade.index("-PreviousInstallerPath $previousMsi")
    ):
        errors.append("The upgrade baseline must be verified before installation")
    return errors


def check_workflow(workflow: str, version: str) -> list[str]:
    errors: list[str] = []
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        return [f"Invalid Tauri version: {version!r}"]

    if _split_workflow(workflow):
        return _check_split_workflow(workflow, version)

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
        errors.extend(
            _check_preflight_order(
                build_job, "- name: Build MSI desktop installer with bundled checkpoints"
            )
        )
    return errors


def _check_split_cab_partition(workflow: str, version: str, verifier: str) -> list[str]:
    build = _job(workflow, _BUILD_JOB)
    errors = _missing(
        build,
        (
            f"$payload = {_VERIFIER} ",
            "$parts[0].Add((Join-Path $folder 'build-provenance.json'))",
            "foreach ($entry in $payload.files) {",
            "if ($entry.size_bytes -ge 2GB) { throw ",
            "if ($partBytes + $entry.size_bytes -ge 2GB) {",
            "$parts[$parts.Count - 1].Add((Join-Path $folder $entry.name))",
            "$partBytes += $entry.size_bytes",
            "if ($parts.Count -gt 4) { throw ",
            "for ($i = 0; $i -lt $parts.Count; $i++)",
            '"part$($i + 1)<<EOF" >> $env:GITHUB_OUTPUT',
            "$parts[$i] | ForEach-Object { $_ >> $env:GITHUB_OUTPUT }",
        ),
        "Windows build must partition the verified MSI Media payload into bounded artifacts",
    )
    artifact_prefix = f"ReefVision-{version}-RC-Installer-Part-"
    upload_steps = [
        step
        for step in re.split(r"(?m)^      - ", build)
        if step.startswith("uses: actions/upload-artifact@")
        and re.search(r"(?m)^          name: .*Installer-Part-", step)
    ]
    if len(upload_steps) != 4:
        errors.append(
            f"Expected four possible installer artifact uploads; found {len(upload_steps)}"
        )
    for part, step in enumerate(upload_steps, 1):
        path = f"path: ${{{{ steps.payload.outputs.part{part} }}}}"
        required = (f"name: {artifact_prefix}{part}", path, "if-no-files-found: error")
        if part > 1:
            required += (f"if: steps.payload.outputs.part{part} != ''",)
        if not set(required) <= {line.strip() for line in step.splitlines()}:
            errors.append(f"Installer artifact part {part} is misconfigured: expected {required!r}")

    download_path = (
        "path: ${{ runner.temp }}" + f"/reefvision-{version.replace('.', '-')}-installer"
    )
    for name in (_CLEAN_JOB, _UPGRADE_JOB):
        job = _job(workflow, name)
        downloads = [
            step
            for step in re.split(r"(?m)^      - ", job)
            if "uses: actions/download-artifact@" in step
        ]
        if len(downloads) != 1:
            errors.append(f"{name} must have exactly one installer artifact download step")
        elif not {
            f"pattern: {artifact_prefix}*",
            "merge-multiple: true",
            download_path,
        } <= {line.strip() for line in downloads[0].splitlines()}:
            errors.append(f"{name} must download and merge all installer parts")

    errors.extend(
        _missing(
            verifier,
            (
                "$msi.Count -ne 1",
                "$msi[0].Name -cne $ExpectedFilename",
                "$identity.ProductVersion -ne $ProductVersion",
                "$database.OpenView('SELECT `DiskId`, `Cabinet` FROM `Media` ORDER BY `DiskId`')",
                "$external.Count -ne $cabs.Count",
                "@($external | Sort-Object -Unique).Count -ne $external.Count",
                "$name -notin $cabs.Name",
                "sha256 = Get-ReefVisionArtifactSha256 -Path $item.FullName",
                "if ($RequireProvenance) {",
                "build-provenance.json",
                "$manifest.version -ne $Version",
                "$manifest.source_commit -ne $SourceCommit",
                "$manifest.source_tree_clean -ne $true",
                "$manifest.msi_verified -ne $true",
                "identity = $manifest.msi.identity",
                "media = $manifest.msi.media",
                "files = $manifest.files",
                "-cne ($expected | ConvertTo-Json -Depth 8 -Compress)",
            ),
            "The shared installer verifier is missing a Media or provenance guard",
        )
    )
    return errors


def check_cab_artifact_partition(
    workflow: str, version: str | None = None, verifier: str | None = None
) -> list[str]:
    """Fail before MSI packaging if an external CAB cannot reach the install runner.

    Current jobs partition the shared verifier's complete MSI Media payload
    by file size. The historical workflow declares fixed CAB ranges.
    """
    if _split_workflow(workflow):
        if version is None:
            version = str(
                json.loads(
                    (_ROOT / "apps/web/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
                )["version"]
            )
        if verifier is None:
            verifier = (_ROOT / "scripts/verify-windows-installer-payload.ps1").read_text(
                encoding="utf-8"
            )
        return _check_split_cab_partition(workflow, version, verifier)

    errors: list[str] = []
    build_marker = "  build-windows-installer:"
    acceptance_marker = "  windows-clean-install-acceptance:"
    if build_marker not in workflow or acceptance_marker not in workflow:
        return ["Missing Windows build or clean-install job for CAB partition preflight"]

    build_job = workflow.split(build_marker, 1)[1].split(acceptance_marker, 1)[0]
    acceptance_job = workflow.split(acceptance_marker, 1)[1]
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
    root = _ROOT
    config = json.loads((root / "apps/web/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    workflow = (root / ".github/workflows/build-desktop.yml").read_text(encoding="utf-8")
    errors = check_workflow(workflow, str(config["version"]))
    errors.extend(check_cab_artifact_partition(workflow, str(config["version"])))
    if errors:
        for error in errors:
            print(f"Windows acceptance version gate: {error}", file=sys.stderr)
        return 1
    print(f"Windows clean-install version gate passed: {config['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

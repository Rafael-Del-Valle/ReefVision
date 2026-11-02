"""Verify that the Windows clean-install job targets the packaged Tauri version.

Run before MSI packaging to catch expensive version-mismatch failures.
This check does not execute an installer or initiate model downloads.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _strip_inline_comment(line: str) -> str:
    """Remove unquoted YAML/PowerShell comments without altering quoted hashes.

    A disabled guard after `#` must not satisfy the installer preflight.
    Keep hash characters inside quoted paths, URLs, and PowerShell messages.
    """
    quote: str | None = None
    index = 0
    while index < len(line):
        char = line[index]
        if quote is not None:
            if char == "`" and quote == '"' and index + 1 < len(line):
                index += 2  # PowerShell escape within double quotes.
                continue
            if char == quote:
                if index + 1 < len(line) and line[index + 1] == quote:
                    index += 2  # YAML/PowerShell doubled quote.
                    continue
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "#" and (
            index == 0 or line[index - 1].isspace() or line[index - 1] == ";"
        ):
            return line[:index].rstrip()
        index += 1
    return line


def _active_workflow_text(workflow: str) -> str:
    """Ignore disabled YAML/PowerShell guards in release preflight checks."""
    # A disabled guard must not count as executable merely because its
    # literal source text survives in a YAML comment, inline comment or <# #>.
    without_blocks = re.sub(r"<#.*?(?:#>|$)", "", workflow, flags=re.DOTALL)
    return "\n".join(
        active
        for line in without_blocks.splitlines()
        if (active := _strip_inline_comment(line)).strip()
    )


def check_workflow(workflow: str, version: str) -> list[str]:
    workflow = _active_workflow_text(workflow)
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

    # Fail before packaging if checkout drift or a dirty source tree could
    # invalidate the source_commit claim in the installer provenance.
    source_step_marker = "      - name: Verify installer build uses exact clean source revision"
    if build_job.count(source_step_marker) != 1:
        errors.append("Installer exact-head clean checkout assertion is missing")
    else:
        source_start = build_job.index(source_step_marker)
        next_step = build_job.find("\n      - ", source_start + len(source_step_marker))
        source_step = build_job[source_start : next_step if next_step >= 0 else None]
        required_source_checks = (
            "$actual = (git rev-parse HEAD).Trim()",
            "if ($actual -ne $env:GITHUB_SHA)",
            'throw "Installer checkout SHA $actual does not match workflow SHA $env:GITHUB_SHA"',
            "$dirty = @(git status --porcelain --untracked-files=all)",
            "if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0)",
            'throw "Installer source checkout must be clean before packaging."',
        )
        guard_missing = any(fragment not in source_step for fragment in required_source_checks)
        step_disabled = re.search(r"(?m)^        (?:if|continue-on-error):", source_step)
        if guard_missing or step_disabled:
            errors.append("Installer exact-head clean checkout guard is disabled or incomplete")
        bootstrap = build_job.find("      - name: Bootstrap build environment")
        if (
            "actions/checkout@v4" not in build_job[:source_start]
            or bootstrap < 0
            or source_start >= bootstrap
        ):
            errors.append("Installer exact-head clean checkout must run before bootstrap")

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
    workflow = _active_workflow_text(workflow)
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

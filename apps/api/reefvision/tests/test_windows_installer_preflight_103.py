"""Fail-closed Windows MSI/CAB packaging preflight regressions for 1.0.3.

These tests inspect source workflow contracts only. They do not build,
install, publish, download models, or alter scientific data.
"""

from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).resolve().parents[4]
GATE = runpy.run_path(str(ROOT / "scripts/check-windows-installer-acceptance-version.py"))
CHECK_WORKFLOW = GATE["check_workflow"]
CHECK_CABS = GATE["check_cab_artifact_partition"]
WORKFLOW = (ROOT / ".github/workflows/build-desktop.yml").read_text(encoding="utf-8")
VERSION = "1.0.3"


def test_real_windows_installer_workflow_passes_preflight() -> None:
    """The version, source provenance, CAB partition and upgrade contract agree."""
    assert CHECK_WORKFLOW(WORKFLOW, VERSION) == []
    assert CHECK_CABS(WORKFLOW) == []


@pytest.mark.parametrize(
    ("original", "replacement", "expected"),
    [
        (
            "$provenance.source_commit -ne $env:GITHUB_SHA",
            "$provenance.source_commit -ne 'unverified'",
            "Installer provenance guard is missing",
        ),
        (
            "            -PreviousInstallerSupportsIsolatedAcceptance `",
            "            # previous installer isolation check removed",
            "Previous-release upgrade guard is missing",
        ),
        (
            "            -SkipUpgrade `",
            "            -LiveSam2Acceptance `\n            -SkipUpgrade `",
            "Default clean-install job must not opt into network model downloads",
        ),
    ],
)
def test_release_preflight_rejects_provenance_or_offline_policy_regressions(
    original: str, replacement: str, expected: str
) -> None:
    assert original in WORKFLOW, "Test fixture no longer matches the real workflow"
    altered = WORKFLOW.replace(original, replacement, 1)
    assert any(expected in error for error in CHECK_WORKFLOW(altered, VERSION))


@pytest.mark.parametrize(
    ("original", "replacement", "expected"),
    [
        (
            "release/bundle/msi/rv4.cab",
            "release/bundle/msi/rv7.cab",
            "CAB manifest mismatch",
        ),
        (
            "          merge-multiple: true",
            "          merge-multiple: false",
            "download and merge all installer parts",
        ),
    ],
)
def test_cab_preflight_rejects_missing_or_unmerged_payloads(
    original: str, replacement: str, expected: str
) -> None:
    assert original in WORKFLOW, "Test fixture no longer matches the real workflow"
    altered = WORKFLOW.replace(original, replacement, 1)
    assert any(expected in error for error in CHECK_CABS(altered))


@pytest.mark.parametrize("style", ["line", "block"])
def test_release_preflight_rejects_commented_out_guards(style: str) -> None:
    """A PowerShell comment containing the guard is not executable provenance."""
    guard = next(
        line
        for line in WORKFLOW.splitlines()
        if "$provenance.source_commit -ne $env:GITHUB_SHA" in line
        and not line.lstrip().startswith("#")
    )
    indent = guard[: len(guard) - len(guard.lstrip())]
    disabled = (
        f"{indent}# {guard.lstrip()}"
        if style == "line"
        else f"{indent}<#\n{guard}\n{indent}#>"
    )
    altered = WORKFLOW.replace(guard, disabled, 1)
    assert any(
        "Installer provenance guard is missing" in error
        for error in CHECK_WORKFLOW(altered, VERSION)
    )


@pytest.mark.parametrize(
    ("active", "disabled", "expected"),
    [
        (
            "          if-no-files-found: error",
            "          # if-no-files-found: error",
            "must reject missing upload files",
        ),
        (
            "          merge-multiple: true",
            "          # merge-multiple: true",
            "download and merge all installer parts",
        ),
    ],
)
def test_cab_preflight_rejects_commented_out_artifact_guards(
    active: str, disabled: str, expected: str
) -> None:
    assert active in WORKFLOW, "Test fixture no longer matches the real workflow"
    altered = WORKFLOW.replace(active, disabled, 1)
    assert any(expected in error for error in CHECK_CABS(altered))


def test_release_preflight_rejects_inline_commented_provenance_guard() -> None:
    """A provenance comparison mentioned after # is not an active check."""
    guard = next(
        line
        for line in WORKFLOW.splitlines()
        if "$provenance.source_commit -ne $env:GITHUB_SHA" in line
        and not line.lstrip().startswith("#")
    )
    indent = guard[: len(guard) - len(guard.lstrip())]
    altered = WORKFLOW.replace(
        guard, f"{indent}Write-Output 'guard disabled' # {guard.lstrip()}", 1
    )
    assert any(
        "Installer provenance guard is missing" in error
        for error in CHECK_WORKFLOW(altered, VERSION)
    )


@pytest.mark.parametrize(
    ("active", "disabled", "expected"),
    [
        (
            "          if-no-files-found: error",
            "          if-no-files-found: ignore # if-no-files-found: error",
            "must reject missing upload files",
        ),
        (
            "          merge-multiple: true",
            "          merge-multiple: false # merge-multiple: true",
            "download and merge all installer parts",
        ),
    ],
)
def test_cab_preflight_rejects_inline_commented_artifact_guards(
    active: str, disabled: str, expected: str
) -> None:
    """A commented-out safeguard cannot satisfy the installer contract."""
    assert active in WORKFLOW, "Test fixture no longer matches the real workflow"
    altered = WORKFLOW.replace(active, disabled, 1)
    assert any(expected in error for error in CHECK_CABS(altered))


@pytest.mark.parametrize(
    "line",
    [
        'Write-Output "https://example.test/#fragment"',
        "Write-Output 'QC # retained'",
        'Write-Output "escaped `" # retained"',
        'name: "Installer #1"',
    ],
)
def test_preflight_comment_filter_preserves_quoted_hashes(line: str) -> None:
    """Legitimate quoted hashes must survive comment normalization."""
    assert GATE["_strip_inline_comment"](line) == line


def test_preflight_comment_filter_removes_powershell_semicolon_comment() -> None:
    assert GATE["_strip_inline_comment"]("Write-Output ok;# disabled guard") == (
        "Write-Output ok;"
    )

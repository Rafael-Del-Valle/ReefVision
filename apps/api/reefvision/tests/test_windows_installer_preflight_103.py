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

"""Check pinned predecessor MSI upgrade wiring without running an installer."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "windows_validated_upgrade_acceptance",
    ROOT / "scripts/check-windows-installer-acceptance-version.py",
)
assert SPEC is not None and SPEC.loader is not None
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)

WORKFLOW = (ROOT / ".github/workflows/build-desktop.yml").read_text(encoding="utf-8")
JOB = "windows-validated-14-upgrade-acceptance"
DIRECT_PREDECESSOR_JOB = "windows-validated-15-upgrade-acceptance"
VERSION = "1.6.0"


def test_direct_validated_15_upgrade_keeps_the_accepted_baseline() -> None:
    assert PREFLIGHT._job(WORKFLOW, DIRECT_PREDECESSOR_JOB), (
        "Windows must exercise the original validated 1.5 MSI"
    )
    assert PREFLIGHT.check_workflow(WORKFLOW, VERSION) == []
    assert PREFLIGHT.check_cab_artifact_partition(WORKFLOW, VERSION) == []


def test_direct_validated_14_upgrade_is_separate_from_existing_roles() -> None:
    upgrade = PREFLIGHT._job(WORKFLOW, JOB)
    assert upgrade, "Windows must directly upgrade the validated 1.4 candidate"
    assert PREFLIGHT.check_workflow(WORKFLOW, VERSION) == []
    assert PREFLIGHT.check_cab_artifact_partition(WORKFLOW, VERSION) == []
    assert "gh release download v1.0.3" in PREFLIGHT._job(WORKFLOW, "windows-upgrade-acceptance")
    lineage = PREFLIGHT._job(WORKFLOW, "windows-lineage-acceptance")
    assert all(
        f"profile: {profile}\n" in lineage
        for profile in (
            "validated-1.3",
            "draft-1.4-0038",
            "draft-1.4-0039",
        )
    )
    assert "name: Installed 1.6 lineage" in lineage
    assert "*.reefvision.zip" not in upgrade and "*.pt" not in upgrade


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ('REEFVISION_1_4_RUN: "44697377337"', 'REEFVISION_1_4_RUN: "1"'),
        ("fb2276c87e1c17393200984d804f54b6c0f21dbf", "0" * 40),
        ("86a17ecd0f6a84e9f4811795210b0ea3389b88eab02a2e87d0d1a7f735a819d0", "0" * 64),
        (
            "-ExpectedInitialSchemaRevision 'b14_condition_0041'",
            "-ExpectedInitialSchemaRevision '0039'",
        ),
        (
            "-ExpectedSchemaRevision 'b16_integrated_0001'",
            "-ExpectedSchemaRevision 'b15_integrated_0002'",
        ),
        ("foreach ($part in 1..2)", "foreach ($part in 1..1)"),
        ("-PreviousInstallerSupportsIsolatedAcceptance", "-SkipUpgrade"),
        (".artifacts/windows-validated-14-upgrade-payload.json", ".artifacts/**/*.zip"),
        (
            "            .artifacts/windows-validated-14-upgrade-payload.json",
            "            .artifacts/windows-validated-14-upgrade-payload.json\n"
            "            ${{ runner.temp }}/**/*.pt",
        ),
    ],
)
def test_direct_upgrade_preflight_rejects_drift(original: str, replacement: str) -> None:
    upgrade = PREFLIGHT._job(WORKFLOW, JOB)
    assert original in upgrade
    changed = WORKFLOW.replace(upgrade, upgrade.replace(original, replacement))
    assert any(JOB in error for error in PREFLIGHT.check_workflow(changed, VERSION))


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ('REEFVISION_1_5_RUN: "44748544977"', 'REEFVISION_1_5_RUN: "1"'),
        ("b846f57e916ef53abc9a2d25ece9927eb9dfb582", "0" * 40),
        ("152d0f93c35b2bcd9440e569a5d2afba4bd00849935a7c4c3961c83c43e49bbb", "0" * 64),
        (
            "-ExpectedInitialSchemaRevision 'b15_integrated_0002'",
            "-ExpectedInitialSchemaRevision 'b15_integrated_0001'",
        ),
        (".Count -ne 5", ".Count -ne 4"),
        ("-PreviousInstallerSupportsIsolatedAcceptance", "-SkipUpgrade"),
    ],
)
def test_direct_validated_15_upgrade_rejects_a_different_baseline(
    original: str, replacement: str
) -> None:
    upgrade = PREFLIGHT._job(WORKFLOW, DIRECT_PREDECESSOR_JOB)
    assert original in upgrade
    changed = WORKFLOW.replace(upgrade, upgrade.replace(original, replacement))
    assert any(
        DIRECT_PREDECESSOR_JOB in error for error in PREFLIGHT.check_workflow(changed, VERSION)
    )


def test_clean_install_requires_the_first_use_journey() -> None:
    changed = WORKFLOW.replace("-FirstUseAcceptance ", "")
    assert any("first-use" in error for error in PREFLIGHT.check_workflow(changed, VERSION))


def test_clean_install_requires_the_workspace_journeys() -> None:
    changed = WORKFLOW.replace("-WorkspaceWorkflowAcceptance ", "")
    assert any("workspace" in error for error in PREFLIGHT.check_workflow(changed, VERSION))

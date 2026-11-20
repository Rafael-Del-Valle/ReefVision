"""Check the pinned 1.4 → 1.5 MSI upgrade without running an installer."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "windows_installer_acceptance_v15",
    ROOT / "scripts/check-windows-installer-acceptance-version.py",
)
assert SPEC is not None and SPEC.loader is not None
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)

WORKFLOW = (ROOT / ".github/workflows/build-desktop.yml").read_text(encoding="utf-8")
JOB = "windows-validated-14-upgrade-acceptance"


def test_direct_validated_14_upgrade_is_separate_from_existing_roles() -> None:
    upgrade = PREFLIGHT._job(WORKFLOW, JOB)
    assert upgrade, "Windows must directly upgrade the validated 1.4 candidate to 1.5"
    assert PREFLIGHT.check_workflow(WORKFLOW, "1.5.0") == []
    assert PREFLIGHT.check_cab_artifact_partition(WORKFLOW, "1.5.0") == []
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
    assert "name: Installed 1.5 lineage" in lineage
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
            "-ExpectedSchemaRevision 'b15_integrated_0002'",
            "-ExpectedSchemaRevision 'b15_integrated_0001'",
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
    assert any(JOB in error for error in PREFLIGHT.check_workflow(changed, "1.5.0"))

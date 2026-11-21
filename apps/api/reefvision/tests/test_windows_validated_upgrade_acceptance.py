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
VALIDATED_15_JOB = "windows-validated-15-upgrade-acceptance"
VALIDATED_16_JOB = "windows-validated-16-upgrade-acceptance"
DIRECT_PREDECESSOR_JOB = "windows-validated-17-upgrade-acceptance"
VALIDATED_18_JOB = "windows-validated-18-upgrade-acceptance"
VERSION = "1.9.0"


@pytest.mark.parametrize(
    "required",
    [
        'REEFVISION_1_8_RUN: "44853957856"',
        'REEFVISION_1_8_BUILD_JOB: "136691608332"',
        "e3e8ffb6395c9f2675ffc10397c2401388e63ee8",
        "5f9bf934e2fe442ec7c9da5817ddd7fe7bb03ad30035708429d8d1f70b1361f6",
        "78d52066848afc6aeac975765359ba13cd3d0e2e8b79ef1b90307eecd03c35ed",
        "14687728605",
        "fc577bc4f464e33f2b46725ec6501831f968af5daa060f1149a2513f61cb3310",
        "$partMatches[0].digest -cne $pin.digest",
        ".Count -ne 6",
        "-ExpectedInitialSchemaRevision 'b18_spectral_0002'",
        "-ExpectedSchemaRevision 'b19_registration_0001'",
        "-VerifyPreviousInstallerRejectsUpgradedProfile",
    ],
)
def test_19_direct_upgrade_requires_original_18_msi_and_rollback(required: str) -> None:
    job = PREFLIGHT._job(WORKFLOW, VALIDATED_18_JOB)
    assert job, "Windows must exercise a direct original 1.8 to 1.9 upgrade"
    assert required in job
    assert PREFLIGHT.check_workflow(WORKFLOW, "1.9.0") == []
    changed = WORKFLOW.replace(job, job.replace(required, "altered-1.8-upgrade-contract"))
    assert any(VALIDATED_18_JOB in error for error in PREFLIGHT.check_workflow(changed, "1.9.0"))


@pytest.mark.parametrize(
    "pin",
    [
        'REEFVISION_1_7_RUN: "44827326113"',
        'REEFVISION_1_7_BUILD_JOB: "136603186182"',
        "3e37524e28c4b7dde8ffbe203120d3b8e7fe2ee9",
        "f751aa96ebdece355f7b25cdfaf6c0e8641c354c481efec434bb1b8235533bf3",
        "90faf157f5dc8489d64f31f92c9b105471e24621bc732d96b91132763ef290cc",
        "$binaryJob.conclusion -ne 'success'",
        "$binaryJob.head_sha -cne $env:REEFVISION_1_7_SOURCE",
        "[string]$binaryJob.run_id -cne $env:REEFVISION_1_7_RUN",
        "-ExpectedInitialSchemaRevision 'b17_monitor_0003'",
    ],
)
def test_direct_17_upgrade_authenticates_manufacturing_job_and_payload(pin: str) -> None:
    job = PREFLIGHT._job(WORKFLOW, DIRECT_PREDECESSOR_JOB)
    assert pin in job
    assert PREFLIGHT.check_workflow(WORKFLOW, VERSION) == []
    changed = WORKFLOW.replace(job, job.replace(pin, "altered-1.7-pin"))
    assert any(
        DIRECT_PREDECESSOR_JOB in error for error in PREFLIGHT.check_workflow(changed, VERSION)
    )


def test_direct_validated_16_upgrade_is_pinned_and_exercises_rollback() -> None:
    job = PREFLIGHT._job(WORKFLOW, VALIDATED_16_JOB)
    assert job, "Windows must directly upgrade the original validated 1.6 MSI"
    assert 'REEFVISION_1_6_RUN: "44798678615"' in job
    assert "3a9ce1622e4f9e230e2ee14432ee7d2f32510870" in job
    assert "d4e53ebfebdf8201526fa7f58acd31392eceba6cdee12b5145e55313452ffb3c" in job
    assert "3b596ee3ba5e9188776cd3208245c277a72013877677c9a16e359ee6da04c3be" in job
    assert "-ExpectedInitialSchemaRevision 'b16_integrated_0001'" in job
    assert "-ExpectedSchemaRevision 'b19_registration_0001'" in job
    assert "-VerifyPreviousInstallerRejectsUpgradedProfile" in job
    assert PREFLIGHT.check_workflow(WORKFLOW, VERSION) == []
    assert PREFLIGHT.check_cab_artifact_partition(WORKFLOW, VERSION) == []


def test_direct_validated_15_upgrade_keeps_the_accepted_baseline() -> None:
    assert PREFLIGHT._job(WORKFLOW, VALIDATED_15_JOB), (
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
    assert "name: Installed 1.9 lineage" in lineage
    assert PREFLIGHT._job(WORKFLOW, "windows-qc-history-acceptance")
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
            "-ExpectedSchemaRevision 'b19_registration_0001'",
            "-ExpectedSchemaRevision 'b16_integrated_0001'",
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
    upgrade = PREFLIGHT._job(WORKFLOW, VALIDATED_15_JOB)
    assert original in upgrade
    changed = WORKFLOW.replace(upgrade, upgrade.replace(original, replacement))
    assert any(VALIDATED_15_JOB in error for error in PREFLIGHT.check_workflow(changed, VERSION))


@pytest.mark.parametrize("job_name", [VALIDATED_15_JOB, VALIDATED_16_JOB, DIRECT_PREDECESSOR_JOB])
def test_validated_upgrade_requires_independent_rollback(job_name: str) -> None:
    upgrade = PREFLIGHT._job(WORKFLOW, job_name)
    flag = "-VerifyPreviousInstallerRejectsUpgradedProfile "
    assert flag in upgrade
    changed = WORKFLOW.replace(upgrade, upgrade.replace(flag, ""))
    assert any(job_name in error for error in PREFLIGHT.check_workflow(changed, VERSION))


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ('REEFVISION_1_6_RUN: "44798678615"', 'REEFVISION_1_6_RUN: "1"'),
        ("3a9ce1622e4f9e230e2ee14432ee7d2f32510870", "0" * 40),
        ("d4e53ebfebdf8201526fa7f58acd31392eceba6cdee12b5145e55313452ffb3c", "0" * 64),
        ("3b596ee3ba5e9188776cd3208245c277a72013877677c9a16e359ee6da04c3be", "0" * 64),
        ("$baselineMsiSha -cne", "$baselineMsiSha -ceq"),
        (
            "-ExpectedInitialSchemaRevision 'b16_integrated_0001'",
            "-ExpectedInitialSchemaRevision '0039'",
        ),
        (
            "-ExpectedSchemaRevision 'b19_registration_0001'",
            "-ExpectedSchemaRevision 'b16_integrated_0001'",
        ),
    ],
)
def test_direct_validated_16_upgrade_preflight_rejects_drift(
    original: str, replacement: str
) -> None:
    upgrade = PREFLIGHT._job(WORKFLOW, VALIDATED_16_JOB)
    assert original in upgrade
    changed = WORKFLOW.replace(upgrade, upgrade.replace(original, replacement))
    assert any(VALIDATED_16_JOB in error for error in PREFLIGHT.check_workflow(changed, VERSION))


def test_clean_install_requires_the_first_use_journey() -> None:
    changed = WORKFLOW.replace("-FirstUseAcceptance ", "")
    assert any("first-use" in error for error in PREFLIGHT.check_workflow(changed, VERSION))


def test_clean_install_requires_the_workspace_journeys() -> None:
    changed = WORKFLOW.replace("-WorkspaceWorkflowAcceptance ", "")
    assert any("workspace" in error for error in PREFLIGHT.check_workflow(changed, VERSION))


def test_clean_install_requires_the_standard_account_schedule_restart() -> None:
    flag = "-ScheduleWorkflowAcceptance"
    assert flag in PREFLIGHT._job(WORKFLOW, "windows-clean-install-acceptance")
    changed = WORKFLOW.replace(flag, "")
    assert any("schedule" in error for error in PREFLIGHT.check_workflow(changed, VERSION))


def test_clean_install_requires_research_tools_and_their_scoped_receipts() -> None:
    flag = "-ResearchToolsAcceptance"
    upload = ".artifacts/windows-clean-acceptance-*/research-tools-evidence.json"
    clean = PREFLIGHT._job(WORKFLOW, "windows-clean-install-acceptance")
    assert flag in clean and upload in clean
    for required in (flag, upload):
        changed = WORKFLOW.replace(clean, clean.replace(required, ""))
        assert any(
            "1.8 research tools" in error for error in PREFLIGHT.check_workflow(changed, VERSION)
        )

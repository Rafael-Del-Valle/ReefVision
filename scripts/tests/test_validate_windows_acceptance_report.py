"""Regression tests for installed-MSI acceptance evidence verification."""

from __future__ import annotations

import copy
import hashlib
import tempfile
import importlib.util
import sys
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "validate_windows_acceptance_report.py"
SPEC = importlib.util.spec_from_file_location("validate_windows_acceptance_report", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def pass_evidence() -> dict:
    return {
        "status": "PASS",
        "detail": "Verified on isolated installed Windows desktop",
        "timestamp_utc": "2026-10-25T02:10:00Z",
    }


def upgraded_migration_evidence(version: str) -> dict:
    return {
        "application_version": version,
        "schema_status": "up_to_date",
        "current_revision": "0041",
        "expected_revision": "0041",
        "database_path_is_isolated": True,
        "timestamp_utc": "2026-10-25T02:10:00Z",
    }


def good_report() -> dict:
    result = {
        "schema_version": "reefvision-windows-clean-acceptance-1",
        "plan_only": False,
        "failure_reason": None,
        "started_at_utc": "2026-10-25T02:00:00Z",
        "completed_at_utc": "2026-10-25T02:20:00Z",
        "reefvision_version": "1.0.2",
        "installer_path": "C:/ReefVision_1.0.2_x64_en-US.msi",
        "installer_sha256": "a" * 64,
        "acceptance_root": "C:/disposable/reefvision-acceptance",
        "isolated_data_root": (
            "C:/disposable/reefvision-acceptance/reefvision-clean-a1b2c3d4e5f6/data"
        ),
        "migration": {
            "application_version": "1.0.2",
            "schema_status": "up_to_date",
            "current_revision": "0040",
            "expected_revision": "0040",
            "database_path_is_isolated": True,
        },
        "post_upgrade_migration": None,
        "upgrade_install": {"status": "SKIPPED", "detail": "SkipUpgrade requested"},
        "upgrade": {"status": "SKIPPED", "detail": "SkipUpgrade requested"},
        "sam2_live": {"status": "SKIPPED"},
        "confidence_review": {"status": "SKIPPED"},
    }
    for key in MODULE.REQUIRED_PASS:
        result[key] = pass_evidence()
    return result


class AcceptanceEvidenceTests(unittest.TestCase):
    def test_clean_install_passes_but_does_not_claim_upgrade(self) -> None:
        clean = good_report()
        MODULE.validate_report(clean, expected_version="1.0.2")
        # Distinguish the two independently required real-upgrade stages.
        with self.assertRaisesRegex(
            MODULE.AcceptanceEvidenceError, "pre-migration asset retention did not PASS"
        ):
            MODULE.validate_report(
                clean, expected_version="1.0.2", expected_upgrade="passed"
            )
        staged_only = copy.deepcopy(clean)
        staged_only["upgrade_install"] = pass_evidence()
        with self.assertRaisesRegex(MODULE.AcceptanceEvidenceError, "upgrade did not PASS"):
            MODULE.validate_report(
                staged_only, expected_version="1.0.2", expected_upgrade="passed"
            )

    def test_missing_and_skipped_required_gates_fail(self) -> None:
        for key in MODULE.REQUIRED_PASS:
            for status in ("SKIPPED", "NOT RUN", "FAIL", None):
                with self.subTest(key=key, status=status):
                    report = good_report()
                    if status is None:
                        del report[key]
                    else:
                        report[key]["status"] = status
                    with self.assertRaises(MODULE.AcceptanceEvidenceError):
                        MODULE.validate_report(report, expected_version="1.0.2")

    def test_plan_only_failure_and_incomplete_migration_fail(self) -> None:
        for field, value in (("plan_only", True), ("failure_reason", "API 500"), ("completed_at_utc", None)):
            with self.subTest(field=field):
                report = good_report()
                report[field] = value
                with self.assertRaises(MODULE.AcceptanceEvidenceError):
                    MODULE.validate_report(report, expected_version="1.0.2")
        for field, value in (("schema_status", "stale"), ("current_revision", "0038"), ("database_path_is_isolated", False)):
            with self.subTest(migration_field=field):
                report = good_report()
                report["migration"][field] = value
                with self.assertRaises(MODULE.AcceptanceEvidenceError):
                    MODULE.validate_report(report, expected_version="1.0.2")

    def test_first_launch_backend_version_must_match_installed_msi(self) -> None:
        clean = good_report()
        MODULE.validate_report(clean, expected_version="1.0.2")
        for version in (None, "", 123, "1.0.1", "1.0.3"):
            with self.subTest(clean_install_api_version=version):
                modified = copy.deepcopy(clean)
                modified["migration"]["application_version"] = version
                with self.assertRaises(MODULE.AcceptanceEvidenceError):
                    MODULE.validate_report(modified, expected_version="1.0.2")

        upgraded = good_report()
        upgraded["reefvision_version"] = "1.0.3"
        upgraded["upgrade_install"] = pass_evidence()
        upgraded["upgrade"] = pass_evidence()
        upgraded["post_upgrade_migration"] = upgraded_migration_evidence("1.0.3")
        upgraded["previous_installer_path"] = "C:/ReefVision_1.0.2.msi"
        upgraded["previous_installer_sha256"] = "b" * 64
        upgraded["previous_installer_version"] = "1.0.2"
        MODULE.validate_report(
            upgraded, expected_version="1.0.3", expected_upgrade="passed"
        )
        # In upgrade mode the first installed API must be the previous MSI,
        # not the new target. The target is verified separately after restart.
        upgraded["migration"]["application_version"] = "1.0.3"
        with self.assertRaisesRegex(
            MODULE.AcceptanceEvidenceError, "Initial installed API version"
        ):
            MODULE.validate_report(
                upgraded, expected_version="1.0.3", expected_upgrade="passed"
            )

    def test_version_hash_and_time_contract(self) -> None:
        for field, value in (("reefvision_version", "1.0.1"), ("installer_sha256", ["a" * 64]), ("started_at_utc", "2026-10-25T02:00:00-05:00")):
            with self.subTest(field=field):
                report = good_report()
                report[field] = value
                with self.assertRaises(MODULE.AcceptanceEvidenceError):
                    MODULE.validate_report(report, expected_version="1.0.2")

    def test_acceptance_data_root_must_be_disposable_and_inside_selected_root(self) -> None:
        valid = good_report()
        MODULE.validate_report(valid, expected_version="1.0.2")
        for field, value in (
            ("acceptance_root", None),
            ("acceptance_root", ""),
            ("acceptance_root", "relative/acceptance"),
            ("acceptance_root", "C:/"),
            ("acceptance_root", "C:/disposable/../reefvision-acceptance"),
            ("isolated_data_root", None),
            ("isolated_data_root", "C:/Users/researcher/AppData/Roaming/org.reefvision.desktop"),
            ("isolated_data_root", "C:/disposable/reefvision-acceptance-other/reefvision-clean-a1b2c3d4e5f6/data"),
            ("isolated_data_root", "C:/disposable/reefvision-acceptance/data"),
            ("isolated_data_root", "C:/disposable/reefvision-acceptance/reefvision-clean-invalid/data"),
            ("isolated_data_root", "C:/disposable/reefvision-acceptance/reefvision-clean-a1b2c3d4e5f6/other"),
            ("isolated_data_root", "C:/disposable/reefvision-acceptance/reefvision-clean-a1b2c3d4e5f6/../data"),
            ("isolated_data_root", "D:/disposable/reefvision-acceptance/reefvision-clean-a1b2c3d4e5f6/data"),
        ):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(valid)
                changed[field] = value
                with self.assertRaises(MODULE.AcceptanceEvidenceError):
                    MODULE.validate_report(changed, expected_version="1.0.2")

    def test_acceptance_roots_reject_nonlocal_or_ambiguous_windows_paths(self) -> None:
        report = good_report()
        unsafe_paths = (
            ("acceptance_root", r"\\server\share\acceptance"),
            ("acceptance_root", r"\\?\C:\disposable\reefvision-acceptance"),
            ("acceptance_root", "C:/disposable/CON.txt/reefvision-acceptance"),
            ("acceptance_root", "C:/disposable/reefvision-acceptance:alternate"),
            ("acceptance_root", "C:/disposable/reefvision-acceptance."),
            ("acceptance_root", "C:/disposable/reefvision-acceptance "),
            ("acceptance_root", "C:/disposable/\x01/reefvision-acceptance"),
            (
                "isolated_data_root",
                "C:/disposable/reefvision-acceptance/reefvision-clean-a1b2c3d4e5f6/data:alternate",
            ),
            (
                "isolated_data_root",
                "C:/disposable/reefvision-acceptance/reefvision-clean-a1b2c3d4e5f6/COM1.txt",
            ),
        )
        for field, value in unsafe_paths:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(report)
                changed[field] = value
                with self.assertRaises(MODULE.AcceptanceEvidenceError):
                    MODULE.validate_report(changed, expected_version="1.0.2")

    def test_acceptance_root_is_case_insensitive_for_windows_paths(self) -> None:
        report = good_report()
        report["acceptance_root"] = r"C:\\DISPOSABLE\\ReefVision-Acceptance"
        report["isolated_data_root"] = (
            r"c:\\disposable\\reefvision-acceptance\\reefvision-clean-A1B2C3D4E5F6\\DATA"
        )
        MODULE.validate_report(report, expected_version="1.0.2")

    def test_windows_installer_numeric_limits_are_enforced(self) -> None:
        for version in ("256.0.0", "1.256.0", "1.0.65536"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(MODULE.AcceptanceEvidenceError, "MSI numeric limits"):
                    MODULE.validate_report(good_report(), expected_version=version)
                report = good_report()
                report["reefvision_version"] = "2.0.0"
                report["upgrade_install"] = pass_evidence()
                report["upgrade"] = pass_evidence()
                report["post_upgrade_migration"] = upgraded_migration_evidence(report["reefvision_version"])
                report["previous_installer_path"] = "C:/previous.msi"
                report["previous_installer_sha256"] = "b" * 64
                report["previous_installer_version"] = version
                with self.assertRaisesRegex(MODULE.AcceptanceEvidenceError, "MSI numeric limits"):
                    MODULE.validate_report(report, expected_version="2.0.0", expected_upgrade="passed")

    def test_optional_review_gates_must_be_explicit(self) -> None:
        for field in MODULE.OPTIONAL_APPROVAL_GATES:
            report = good_report()
            report[field] = {"status": "NOT RUN"}
            with self.assertRaises(MODULE.AcceptanceEvidenceError):
                MODULE.validate_report(report, expected_version="1.0.2")

    def test_upgrade_requires_real_higher_version_and_previous_installer(self) -> None:
        report = good_report()
        report["reefvision_version"] = "1.0.3"
        report["upgrade_install"] = pass_evidence()
        report["upgrade"] = pass_evidence()
        report["post_upgrade_migration"] = upgraded_migration_evidence(report["reefvision_version"])
        report["previous_installer_path"] = "C:/ReefVision_1.0.2.msi"
        report["previous_installer_sha256"] = "b" * 64
        report["previous_installer_version"] = "1.0.2"
        MODULE.validate_report(report, expected_version="1.0.3", expected_upgrade="passed")
        for version in ("1.0.3", "1.0.4", "invalid"):
            changed = copy.deepcopy(report)
            changed["previous_installer_version"] = version
            with self.assertRaises(MODULE.AcceptanceEvidenceError):
                MODULE.validate_report(changed, expected_version="1.0.3", expected_upgrade="passed")

    def test_installer_hash_is_checked_against_real_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            installer = Path(folder) / "ReefVision_1.0.2_x64_en-US.msi"
            installer.write_bytes(b"disposable MSI digest fixture")
            report = good_report()
            report["installer_path"] = str(installer)
            report["installer_sha256"] = hashlib.sha256(installer.read_bytes()).hexdigest()
            MODULE.validate_report(report, expected_version="1.0.2", installer=installer)
            installer.write_bytes(b"tampered fixture")
            with self.assertRaisesRegex(MODULE.AcceptanceEvidenceError, "hash differs"):
                MODULE.validate_report(report, expected_version="1.0.2", installer=installer)

    def test_pass_evidence_must_be_dated_explained_and_within_run(self) -> None:
        invalid = (
            ("detail", ""),
            ("detail", None),
            ("timestamp_utc", None),
            ("timestamp_utc", "2026-10-25T01:59:59Z"),
            ("timestamp_utc", "2026-10-25T02:20:01Z"),
            ("timestamp_utc", "2026-10-25T02:10:00-05:00"),
        )
        for key in MODULE.REQUIRED_PASS:
            for field, value in invalid:
                with self.subTest(gate=key, field=field, value=value):
                    report = good_report()
                    report[key][field] = value
                    with self.assertRaises(MODULE.AcceptanceEvidenceError):
                        MODULE.validate_report(report, expected_version="1.0.2")

    def test_optional_live_pass_and_real_upgrade_need_run_evidence(self) -> None:
        report = good_report()
        report["sam2_live"] = pass_evidence()
        MODULE.validate_report(report, expected_version="1.0.2")
        report["sam2_live"]["timestamp_utc"] = "2026-10-24T02:10:00Z"
        with self.assertRaisesRegex(MODULE.AcceptanceEvidenceError, "outside the acceptance run"):
            MODULE.validate_report(report, expected_version="1.0.2")

        upgraded = good_report()
        upgraded["reefvision_version"] = "1.0.3"
        upgraded["upgrade_install"] = pass_evidence()
        upgraded["upgrade"] = pass_evidence()
        upgraded["post_upgrade_migration"] = upgraded_migration_evidence(upgraded["reefvision_version"])
        upgraded["previous_installer_path"] = "C:/ReefVision_1.0.2.msi"
        upgraded["previous_installer_sha256"] = "b" * 64
        upgraded["previous_installer_version"] = "1.0.2"
        MODULE.validate_report(upgraded, expected_version="1.0.3", expected_upgrade="passed")
        upgraded["upgrade"]["detail"] = "  "
        with self.assertRaisesRegex(MODULE.AcceptanceEvidenceError, "PASS evidence detail"):
            MODULE.validate_report(upgraded, expected_version="1.0.3", expected_upgrade="passed")

    def test_upgrade_requires_hashes_of_both_real_msi_files(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            previous = Path(folder) / "previous.msi"
            target = Path(folder) / "target.msi"
            previous.write_bytes(b"disposable previous MSI fixture")
            target.write_bytes(b"disposable target MSI fixture")
            report = good_report()
            report["reefvision_version"] = "1.0.3"
            report["installer_path"] = str(target)
            report["installer_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
            report["upgrade_install"] = pass_evidence()
            report["upgrade"] = pass_evidence()
            report["post_upgrade_migration"] = upgraded_migration_evidence(report["reefvision_version"])
            report["previous_installer_path"] = str(previous)
            report["previous_installer_version"] = "1.0.2"
            report["previous_installer_sha256"] = hashlib.sha256(previous.read_bytes()).hexdigest()
            MODULE.validate_report(
                report, expected_version="1.0.3", expected_upgrade="passed", installer=target
            )

            for field, value in (
                ("previous_installer_sha256", None),
                ("previous_installer_sha256", "invalid"),
                ("previous_installer_sha256", report["installer_sha256"]),
                ("previous_installer_path", str(Path(folder) / "missing.msi")),
                ("previous_installer_path", str(target)),
            ):
                with self.subTest(field=field, value=value):
                    changed = copy.deepcopy(report)
                    changed[field] = value
                    with self.assertRaises(MODULE.AcceptanceEvidenceError):
                        MODULE.validate_report(
                            changed, expected_version="1.0.3", expected_upgrade="passed",
                            installer=target
                        )

            previous.write_bytes(b"tampered previous MSI")
            with self.assertRaisesRegex(MODULE.AcceptanceEvidenceError, "Previous MSI hash differs"):
                MODULE.validate_report(
                    report, expected_version="1.0.3", expected_upgrade="passed", installer=target
                )

    def test_target_migration_evidence_must_match_upgraded_desktop(self) -> None:
        report = good_report()
        report["reefvision_version"] = "1.0.3"
        report["upgrade_install"] = pass_evidence()
        report["upgrade"] = pass_evidence()
        report["post_upgrade_migration"] = upgraded_migration_evidence("1.0.3")
        report["previous_installer_path"] = "C:/ReefVision_1.0.2.msi"
        report["previous_installer_sha256"] = "b" * 64
        report["previous_installer_version"] = "1.0.2"
        MODULE.validate_report(report, expected_version="1.0.3", expected_upgrade="passed")

        for field, value in (
            ("post_upgrade_migration", None),
            ("post_upgrade_migration", "unverifiable"),
            ("application_version", "1.0.2"),
            ("schema_status", "stale"),
            ("current_revision", "0038"),
            ("database_path_is_isolated", False),
            ("timestamp_utc", None),
            ("timestamp_utc", "2026-10-25T01:59:00Z"),
            ("timestamp_utc", "2026-10-25T02:21:00Z"),
            ("timestamp_utc", "2026-10-25T02:10:00-05:00"),
            ("timestamp_utc", "2026-10-25T02:09:00Z"),
        ):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(report)
                if field == "post_upgrade_migration":
                    changed[field] = value
                else:
                    changed["post_upgrade_migration"][field] = value
                with self.assertRaises(MODULE.AcceptanceEvidenceError):
                    MODULE.validate_report(
                        changed, expected_version="1.0.3", expected_upgrade="passed"
                    )

        # An explicitly skipped upgrade must not borrow a post-upgrade
        # migration snapshot from a separate MSI acceptance run.
        skipped = good_report()
        skipped["post_upgrade_migration"] = upgraded_migration_evidence("1.0.2")
        with self.assertRaisesRegex(
            MODULE.AcceptanceEvidenceError, "must not claim a post-upgrade migration"
        ):
            MODULE.validate_report(skipped, expected_version="1.0.2")

    def test_upgrade_skip_must_be_explicit(self) -> None:
        report = good_report()
        report["upgrade"] = {"status": "SKIPPED", "detail": "not tested"}
        with self.assertRaises(MODULE.AcceptanceEvidenceError):
            MODULE.validate_report(report, expected_version="1.0.2")

    def test_upgrade_skip_reason_must_match_across_phases(self) -> None:
        # The native offline harness selects exactly one skip policy, not an
        # installer-stage reason different from the final approval reason.
        report = good_report()
        for changed_gate in ("upgrade_install", "upgrade"):
            with self.subTest(changed_gate=changed_gate):
                inconsistent = copy.deepcopy(report)
                inconsistent[changed_gate]["detail"] = "previous installer not supplied"
                with self.assertRaisesRegex(
                    MODULE.AcceptanceEvidenceError, "skip reasons disagree"
                ):
                    MODULE.validate_report(inconsistent, expected_version="1.0.2")

        # Either legitimate skip policy remains valid when both gates agree.
        report["upgrade_install"]["detail"] = "previous installer not supplied"
        report["upgrade"]["detail"] = "previous installer not supplied"
        MODULE.validate_report(report, expected_version="1.0.2")

    def test_installed_acceptance_requires_causal_gate_timestamps(self) -> None:
        # Every mandatory status may say PASS with a valid run-window time,
        # but the observed events must still follow native installer order.
        MODULE.validate_report(good_report(), expected_version="1.0.2")
        for before, after in MODULE.CAUSAL_GATE_ORDER:
            with self.subTest(before=before, after=after):
                report = good_report()
                report[before]["timestamp_utc"] = "2026-10-25T02:12:00Z"
                report[after]["timestamp_utc"] = "2026-10-25T02:08:00Z"
                with self.assertRaisesRegex(
                    MODULE.AcceptanceEvidenceError, "causal order invalid"
                ):
                    MODULE.validate_report(report, expected_version="1.0.2")

    def test_realistic_monotonic_installed_acceptance_evidence_passes(self) -> None:
        report = good_report()
        sequence = (
            "install",
            "shortcuts",
            "first_launch",
            "frontend_backend_connectivity",
            "model_policy",
            "external_annotation_imports",
            "class_visibility_persistence",
            "upgrade",
            "restart",
            "project_persistence",
            "qc_review_coordination",
            "qc_workflow_persistence",
            "qc_workflow_replay",
            "project_exchange",
            "uninstall",
            "data_retention",
        )
        for minute, gate in enumerate(sequence, start=1):
            if gate != "upgrade":
                report[gate]["timestamp_utc"] = f"2026-10-25T02:{minute:02d}:00Z"
        MODULE.validate_report(report, expected_version="1.0.2")

    def test_real_upgrade_install_must_precede_restart(self) -> None:
        report = good_report()
        report["reefvision_version"] = "1.0.3"
        report["upgrade_install"] = pass_evidence()
        report["upgrade"] = pass_evidence()
        report["post_upgrade_migration"] = upgraded_migration_evidence(report["reefvision_version"])
        report["previous_installer_path"] = "C:/ReefVision_1.0.2.msi"
        report["previous_installer_sha256"] = "b" * 64
        report["previous_installer_version"] = "1.0.2"
        MODULE.validate_report(report, expected_version="1.0.3", expected_upgrade="passed")
        # Keep restart valid relative to every other required gate, so the
        # rejection specifically exercises the new upgrade-install ordering.
        report["upgrade_install"]["timestamp_utc"] = "2026-10-25T02:12:00Z"
        report["restart"]["timestamp_utc"] = "2026-10-25T02:10:00Z"
        with self.assertRaisesRegex(
            MODULE.AcceptanceEvidenceError, "causal order invalid"
        ):
            MODULE.validate_report(report, expected_version="1.0.3", expected_upgrade="passed")

    def test_upgrade_install_and_final_science_gate_have_distinct_times(self) -> None:
        # Matches the *actual* PowerShell harness: the MSI and byte-retention
        # check finish before restart, but the final upgraded-science verdict
        # cannot PASS until the installed QC workflow has run and assets have
        # been verified again after application migration.
        report = good_report()
        report["reefvision_version"] = "1.0.3"
        report["upgrade_install"] = pass_evidence()
        report["upgrade"] = pass_evidence()
        report["post_upgrade_migration"] = upgraded_migration_evidence(report["reefvision_version"])
        report["previous_installer_path"] = "C:/ReefVision_1.0.2.msi"
        report["previous_installer_sha256"] = "b" * 64
        report["previous_installer_version"] = "1.0.2"
        milestones = {
            "upgrade_install": "02:11:00",
            "class_visibility_persistence": "02:12:00",
            "post_upgrade_migration": "02:12:30",
            "restart": "02:13:00",
            "project_persistence": "02:13:00",
            "qc_review_coordination": "02:14:00",
            "qc_workflow_persistence": "02:15:00",
            "qc_workflow_replay": "02:16:00",
            "project_exchange": "02:17:00",
            "upgrade": "02:18:00",
            "uninstall": "02:19:00",
            "data_retention": "02:19:01",
        }
        for gate, clock in milestones.items():
            report[gate]["timestamp_utc"] = f"2026-10-25T{clock}Z"
        MODULE.validate_report(report, expected_version="1.0.3", expected_upgrade="passed")

        for gate, when in (
            ("upgrade_install", "02:09:00"),  # Before initial install
            ("upgrade_install", "02:14:00"),  # After app restart
            ("upgrade", "02:16:30"),  # Before saved workflow export
            ("upgrade", "02:19:30"),  # After uninstall
        ):
            with self.subTest(gate=gate, when=when):
                invalid = copy.deepcopy(report)
                invalid[gate]["timestamp_utc"] = f"2026-10-25T{when}Z"
                with self.assertRaisesRegex(
                    MODULE.AcceptanceEvidenceError, "causal order invalid"
                ):
                    MODULE.validate_report(
                        invalid, expected_version="1.0.3", expected_upgrade="passed"
                    )
        for invalid_gate in (
            None,
            {"status": "SKIPPED", "detail": "previous installer not supplied"},
            {"status": "PASS", "detail": "pre-migration assets checked"},
        ):
            invalid = copy.deepcopy(report)
            if invalid_gate is None:
                del invalid["upgrade_install"]
            else:
                invalid["upgrade_install"] = invalid_gate
            with self.assertRaises(MODULE.AcceptanceEvidenceError):
                MODULE.validate_report(
                    invalid, expected_version="1.0.3", expected_upgrade="passed"
                )

    def test_skipped_upgrade_cannot_claim_installer_upgrade_stage(self) -> None:
        report = good_report()
        report["upgrade_install"] = pass_evidence()
        with self.assertRaisesRegex(
            MODULE.AcceptanceEvidenceError, "must not claim real upgrade installation"
        ):
            MODULE.validate_report(report, expected_version="1.0.2")


if __name__ == "__main__":
    unittest.main()

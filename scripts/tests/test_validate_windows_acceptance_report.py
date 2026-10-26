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
        "migration": {
            "schema_status": "up_to_date",
            "current_revision": "0040",
            "expected_revision": "0040",
            "database_path_is_isolated": True,
        },
        "upgrade": {"status": "SKIPPED", "detail": "SkipUpgrade requested"},
        "sam2_live": {"status": "SKIPPED"},
        "confidence_review": {"status": "SKIPPED"},
    }
    for key in MODULE.REQUIRED_PASS:
        result[key] = {"status": "PASS", "detail": "verified"}
    return result


class AcceptanceEvidenceTests(unittest.TestCase):
    def test_clean_install_passes_but_does_not_claim_upgrade(self) -> None:
        MODULE.validate_report(good_report(), expected_version="1.0.2")
        with self.assertRaisesRegex(MODULE.AcceptanceEvidenceError, "upgrade did not PASS"):
            MODULE.validate_report(good_report(), expected_version="1.0.2", expected_upgrade="passed")

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

    def test_version_hash_and_time_contract(self) -> None:
        for field, value in (("reefvision_version", "1.0.1"), ("installer_sha256", ["a" * 64]), ("started_at_utc", "2026-10-25T02:00:00-05:00")):
            with self.subTest(field=field):
                report = good_report()
                report[field] = value
                with self.assertRaises(MODULE.AcceptanceEvidenceError):
                    MODULE.validate_report(report, expected_version="1.0.2")

    def test_windows_installer_numeric_limits_are_enforced(self) -> None:
        for version in ("256.0.0", "1.256.0", "1.0.65536"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(MODULE.AcceptanceEvidenceError, "MSI numeric limits"):
                    MODULE.validate_report(good_report(), expected_version=version)
                report = good_report()
                report["reefvision_version"] = "2.0.0"
                report["upgrade"] = {"status": "PASS"}
                report["previous_installer_path"] = "C:/previous.msi"
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
        report["upgrade"] = {"status": "PASS"}
        report["previous_installer_path"] = "C:/ReefVision_1.0.2.msi"
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

    def test_upgrade_skip_must_be_explicit(self) -> None:
        report = good_report()
        report["upgrade"] = {"status": "SKIPPED", "detail": "not tested"}
        with self.assertRaises(MODULE.AcceptanceEvidenceError):
            MODULE.validate_report(report, expected_version="1.0.2")


if __name__ == "__main__":
    unittest.main()

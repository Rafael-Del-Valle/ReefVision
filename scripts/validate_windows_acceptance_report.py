"""Fail closed on incomplete installed-Windows MSI acceptance evidence.

This verifies disposable installed-app evidence, not interactive GUI acceptance
or an upgrade/rollback that was explicitly skipped. It never reads user data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AcceptanceEvidenceError(ValueError):
    """Report cannot support the claimed acceptance result."""


REQUIRED_PASS = (
    "install",
    "shortcuts",
    "first_launch",
    "frontend_backend_connectivity",
    "model_policy",
    "external_annotation_imports",
    "project_persistence",
    "class_visibility_persistence",
    "qc_review_coordination",
    "qc_workflow_persistence",
    "qc_workflow_replay",
    "restart",
    "project_exchange",
    "uninstall",
    "data_retention",
)
OPTIONAL_APPROVAL_GATES = ("sam2_live", "confidence_review")
MSI_VERSION = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,5}\Z")
SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceEvidenceError(message)


def _msi_version(value: Any, label: str) -> tuple[int, int, int]:
    _require(isinstance(value, str) and MSI_VERSION.fullmatch(value) is not None, f"Invalid {label}")
    major, minor, build = (int(part) for part in value.split("."))
    _require(major <= 255 and minor <= 255 and build <= 65535, f"{label} exceeds MSI numeric limits")
    return major, minor, build


def _utc(value: Any, label: str) -> datetime:
    _require(isinstance(value, str), f"{label} must be an ISO-8601 UTC timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AcceptanceEvidenceError(f"{label} is not a valid timestamp") from exc
    _require(result.tzinfo is not None and result.utcoffset().total_seconds() == 0, f"{label} must be UTC")
    return result.astimezone(timezone.utc)


def _status(report: dict[str, Any], key: str) -> str:
    entry = report.get(key)
    _require(isinstance(entry, dict), f"Missing {key} evidence object")
    status = entry.get("status")
    _require(isinstance(status, str), f"Missing {key} status")
    return status


def validate_report(
    report: dict[str, Any],
    *,
    expected_version: str,
    expected_upgrade: str = "skipped",
    installer: Path | None = None,
) -> None:
    """Validate report claims without changing the MSI or research data."""
    _require(isinstance(report, dict), "Acceptance report must be a JSON object")
    _require(report.get("schema_version") == "reefvision-windows-clean-acceptance-1", "Unknown evidence schema")
    _require(report.get("plan_only") is False, "Plan-only evidence is not installed acceptance")
    _require(report.get("failure_reason") is None, "Acceptance report records a failure")
    start = _utc(report.get("started_at_utc"), "started_at_utc")
    end = _utc(report.get("completed_at_utc"), "completed_at_utc")
    _require(end >= start, "Acceptance completion precedes start")
    target_version = _msi_version(expected_version, "expected MSI version")
    _require(report.get("reefvision_version") == expected_version, "Reported MSI version differs from expected version")
    _require(isinstance(report.get("installer_sha256"), str) and SHA256.fullmatch(report["installer_sha256"]) is not None, "Invalid installer SHA-256")
    _require(isinstance(report.get("installer_path"), str) and report["installer_path"].lower().endswith(".msi"), "Missing MSI path")
    if installer is not None:
        _require(installer.is_file(), "Expected MSI is missing")
        with installer.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        _require(digest == report["installer_sha256"].lower(), "Installed MSI hash differs from report")
        _require(installer.resolve() == Path(report["installer_path"]).resolve(), "MSI path differs from report")

    migration = report.get("migration")
    _require(isinstance(migration, dict), "Missing packaged migration evidence")
    _require(migration.get("schema_status") == "up_to_date", "Installed database is not migrated")
    _require(migration.get("database_path_is_isolated") is True, "Installed database is not isolated")
    _require(
        isinstance(migration.get("current_revision"), str)
        and bool(migration["current_revision"])
        and migration["current_revision"] == migration.get("expected_revision"),
        "Installed migration revision does not match expected revision",
    )
    for key in REQUIRED_PASS:
        _require(_status(report, key) == "PASS", f"Required installed acceptance gate {key} did not PASS")
    for key in OPTIONAL_APPROVAL_GATES:
        _require(_status(report, key) in {"PASS", "SKIPPED"}, f"Invalid optional researcher-approval gate {key}")

    upgrade = _status(report, "upgrade")
    _require(expected_upgrade in {"passed", "skipped"}, "Unknown expected upgrade policy")
    if expected_upgrade == "passed":
        _require(upgrade == "PASS", "Real MSI upgrade did not PASS")
        _require(bool(report.get("previous_installer_path")) and bool(report.get("previous_installer_version")), "Missing previous MSI evidence")
        previous_version = _msi_version(report["previous_installer_version"], "previous MSI version")
        _require(previous_version < target_version, "Target MSI is not newer than previous MSI")
    else:
        _require(upgrade == "SKIPPED", "Clean-install-only report must not claim upgrade acceptance")
        _require(
            report["upgrade"].get("detail") in {"SkipUpgrade requested", "previous installer not supplied"},
            "Upgrade skip lacks explicit reason",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-upgrade", choices=("passed", "skipped"), default="skipped")
    parser.add_argument("--installer", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8-sig"))
        validate_report(
            report,
            expected_version=args.expected_version,
            expected_upgrade=args.expected_upgrade,
            installer=args.installer,
        )
    except (OSError, json.JSONDecodeError, AcceptanceEvidenceError) as exc:
        parser.exit(2, f"INVALID INSTALLED-WINDOWS ACCEPTANCE: {exc}\n")
    print(f"Installed-Windows acceptance evidence verified ({args.expected_upgrade} upgrade); interactive GUI and rollback are separate gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

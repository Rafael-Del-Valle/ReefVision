#!/usr/bin/env python3
"""Compare two offline inspector reports; never authorize a migration.

Generate both reports with inspect-alembic-0038-sqlite.py --hash-affected-rows
and --model-data-root, using consistent offline database and model copies.
An inspector exit of 2 may still yield useful evidence for manual review.
This comparison checks retained values, not the correctness of new schema.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _fingerprint_matches(before: object, after: object) -> bool:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    digest = before.get("sha256")
    columns = before.get("columns")
    count = before.get("row_count")
    return (
        isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
        and isinstance(columns, list)
        and bool(columns)
        and type(count) is int
        and count >= 0
        and before == after
    )


def compare_reports(before: dict, after: dict) -> dict:
    issues = []
    table_results = {}
    for label, report in (("baseline", before), ("candidate", after)):
        if (
            report.get("schema_version") != "reefvision-sqlite-lineage-forensics-0001"
            or report.get("affected_table_content_fingerprint_algorithm")
            != "reefvision-sqlite-row-multiset-v1"
        ):
            issues.append(f"{label}: incompatible evidence format")
        if report.get("sqlite_integrity_check_ok") is not True or report.get(
            "foreign_key_violations"
        ) != 0:
            issues.append(f"{label}: database integrity not established")
        # Identical event rows can still acquire cross-project parent links
        # or lose required constraints after reconciliation. SQLite integrity
        # and foreign-key checks alone do not establish QC event semantics.
        row_counts = report.get("affected_table_row_counts")
        if isinstance(row_counts, dict) and "review_queue_item_events" in row_counts:
            for field in ("qc_event_scope_violations", "qc_event_type_violations"):
                value = report.get(field)
                if type(value) is not int or value != 0:
                    issues.append(f"{label}: {field} not established as zero")
            for field in (
                "qc_request_key_unique",
                "qc_required_columns_not_null",
                "qc_event_foreign_keys_valid",
                "qc_event_primary_key_valid",
            ):
                if report.get(field) is not True:
                    issues.append(f"{label}: {field} not established")
            if report.get("review_event_check") not in (
                "coordination", "triage", "triage_complete"
            ):
                issues.append(f"{label}: QC event CHECK not established")
        count = report.get("model_registry_row_count")
        checkpoint = report.get("model_registry_checkpoint_evidence")
        if (
            type(count) is not int
            or count <= 0
            or report.get("model_registry_checkpoint_files_verified") is not True
            or not isinstance(checkpoint, dict)
            or checkpoint.get("counts") != {"verified": count}
        ):
            issues.append(f"{label}: populated registry checkpoint evidence missing")

    baseline = before.get("affected_table_content_fingerprints")
    candidate = after.get("affected_table_content_fingerprints")
    counts = before.get("affected_table_row_counts")
    candidate_counts = after.get("affected_table_row_counts")
    projections = after.get("metric_0039_content_fingerprints")
    if not all(isinstance(value, dict) for value in (baseline, candidate, counts, candidate_counts)):
        issues.append("Affected-table content evidence missing")
    elif not baseline or set(baseline) != set(counts) or set(candidate) != set(candidate_counts):
        issues.append("Affected-table evidence incomplete")
    else:
        if not any(type(count) is int and count > 0 for count in counts.values()):
            issues.append("Baseline contains no populated affected table")
        for table, fingerprint in sorted(baseline.items()):
            current = candidate.get(table)
            status = "not_preserved_or_not_comparable"
            if (
                isinstance(fingerprint, dict)
                and fingerprint.get("row_count") == counts[table]
                and counts[table] == candidate_counts.get(table)
            ):
                if _fingerprint_matches(fingerprint, current):
                    status = "full_content_matches"
                elif (
                    table in {"computed_metric_definitions", "computed_metric_results"}
                    and isinstance(projections, dict)
                    and isinstance(current, dict)
                    and isinstance(current.get("columns"), list)
                    and isinstance(fingerprint.get("columns"), list)
                    and set(fingerprint["columns"]) < set(current["columns"])
                    and _fingerprint_matches(fingerprint, projections.get(table))
                ):
                    status = "original_metric_columns_match"
            table_results[table] = status
            if status == "not_preserved_or_not_comparable":
                issues.append(f"{table}: retained content not established")

    registry_before = before.get("model_registry_metadata_fingerprint")
    registry_after = after.get("model_registry_metadata_fingerprint")
    if (
        not _fingerprint_matches(registry_before, registry_after)
        or registry_before.get("row_count") != before.get("model_registry_row_count")
        or registry_after.get("row_count") != after.get("model_registry_row_count")
    ):
        issues.append("Registered-model metadata preservation not established")
    return {
        "retained_content_matches": not issues,
        "table_results": table_results,
        "issues": issues,
        "automatic_migration_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        before = json.loads(args.baseline.read_text(encoding="utf-8"))
        after = json.loads(args.candidate.read_text(encoding="utf-8"))
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError("Expected two JSON report objects")
        result = compare_reports(before, after)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["retained_content_matches"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

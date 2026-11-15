#!/usr/bin/env python3
"""Validate and render ReefVision's canonical release feature inventory."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "docs" / "roadmap" / "REEFVISION_2_0_FEATURE_INVENTORY.json"
DEFAULT_RENDER = ROOT / "docs" / "roadmap" / "REEFVISION_2_0_FEATURE_INVENTORY.md"

FEATURE_STATUSES = {"verified", "in_progress", "blocked", "explicitly_deferred"}
CHECK_STATUSES = {"verified", "in_progress", "blocked", "not_applicable"}
WORKFLOW_VALUES = {"required", "not_applicable", "deferred"}
EVIDENCE_KINDS = (
    "source",
    "browser",
    "windows_installed",
    "physical_hardware",
    "representative_data",
)
FEATURE_FIELDS = (
    "id",
    "title",
    "target_version",
    "source_refs",
    "dependencies",
    "user_facing",
    "entry_point",
    "workflow_builder",
    "acceptance_checks",
    "applicable_evidence",
    "evidence",
    "status",
    "missing_input",
    "defer_reason",
    "notes",
)


def load_inventory(path: Path) -> dict[str, object]:
    """Load an inventory document from UTF-8 JSON."""

    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("inventory root must be a JSON object")
    return document


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def validate_inventory(document: object) -> list[str]:
    """Return deterministic human-readable validation errors."""

    errors: list[str] = []
    if not isinstance(document, Mapping):
        return ["inventory root must be an object"]

    for field in ("schema_version", "candidate_target", "updated_at", "sources", "features"):
        if field not in document:
            errors.append(f"inventory is missing required field '{field}'")

    sources = _list(document.get("sources"))
    source_ids = {
        source.get("id")
        for source in sources
        if isinstance(source, Mapping) and _nonempty_string(source.get("id"))
    }
    features = _list(document.get("features"))

    feature_ids = [
        feature.get("id")
        for feature in features
        if isinstance(feature, Mapping) and _nonempty_string(feature.get("id"))
    ]
    for duplicate in sorted(_duplicates(feature_ids)):
        errors.append(f"duplicate feature id '{duplicate}'")
    known_feature_ids = set(feature_ids)

    check_ids: list[str] = []
    for feature in features:
        if not isinstance(feature, Mapping):
            errors.append("feature record must be an object")
            continue
        feature_id = feature.get("id") if _nonempty_string(feature.get("id")) else "<missing-id>"
        for field in FEATURE_FIELDS:
            if field not in feature:
                errors.append(f"feature '{feature_id}' is missing required field '{field}'")

        status = feature.get("status")
        if status not in FEATURE_STATUSES:
            errors.append(f"feature '{feature_id}' has invalid status '{status}'")
        workflow_builder = feature.get("workflow_builder")
        if workflow_builder not in WORKFLOW_VALUES:
            errors.append(
                f"feature '{feature_id}' has invalid workflow_builder value '{workflow_builder}'"
            )

        if feature.get("user_facing") is True and not _nonempty_string(feature.get("entry_point")):
            errors.append(f"user-facing feature '{feature_id}' requires an entry_point")
        if status == "blocked" and not _nonempty_string(feature.get("missing_input")):
            errors.append(f"blocked feature '{feature_id}' requires an exact missing_input")
        if status == "explicitly_deferred" and not _nonempty_string(feature.get("defer_reason")):
            errors.append(f"deferred feature '{feature_id}' requires a defer_reason")

        for dependency in _list(feature.get("dependencies")):
            if dependency not in known_feature_ids:
                errors.append(
                    f"feature '{feature_id}' references unknown dependency '{dependency}'"
                )
        for source_ref in _list(feature.get("source_refs")):
            if source_ref not in source_ids:
                errors.append(f"feature '{feature_id}' references unknown source '{source_ref}'")

        evidence = _mapping(feature.get("evidence"))
        for kind in EVIDENCE_KINDS:
            if kind not in evidence:
                errors.append(f"feature '{feature_id}' evidence is missing category '{kind}'")
        evidence_ids: set[str] = set()
        for records in evidence.values():
            for record in _list(records):
                if isinstance(record, Mapping) and _nonempty_string(record.get("id")):
                    evidence_ids.add(record["id"])

        applicable = _list(feature.get("applicable_evidence"))
        for kind in applicable:
            if kind not in EVIDENCE_KINDS:
                errors.append(f"feature '{feature_id}' has unknown evidence category '{kind}'")
            elif status == "verified" and not _list(evidence.get(kind)):
                errors.append(f"verified feature '{feature_id}' lacks {kind} evidence")

        checks = _list(feature.get("acceptance_checks"))
        if not checks:
            errors.append(f"feature '{feature_id}' requires at least one acceptance check")
        for check in checks:
            if not isinstance(check, Mapping):
                errors.append(f"feature '{feature_id}' has a non-object acceptance check")
                continue
            check_id = check.get("id")
            if _nonempty_string(check_id):
                check_ids.append(check_id)
            else:
                errors.append(f"feature '{feature_id}' has an acceptance check without an id")
                check_id = "<missing-check-id>"
            check_status = check.get("status")
            if check_status not in CHECK_STATUSES:
                errors.append(f"acceptance check '{check_id}' has invalid status '{check_status}'")
            if status == "verified" and check_status not in {"verified", "not_applicable"}:
                errors.append(
                    f"verified feature '{feature_id}' has unresolved acceptance check '{check_id}'"
                )
            check_evidence = _list(check.get("evidence"))
            if check_status == "verified" and not check_evidence:
                errors.append(f"verified acceptance check '{check_id}' requires evidence")
            for evidence_ref in check_evidence:
                if evidence_ref not in evidence_ids:
                    errors.append(
                        f"acceptance check '{check_id}' references unknown evidence "
                        f"'{evidence_ref}'"
                    )

    for duplicate in sorted(_duplicates(check_ids)):
        errors.append(f"duplicate acceptance check id '{duplicate}'")
    return errors


def _escape_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _version_key(value: object) -> tuple[int, ...]:
    text = str(value)
    if text.startswith("post-"):
        return (999,)
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return (998,)


def render_inventory(document: dict[str, object]) -> str:
    """Render a deterministic review view without mutating the document."""

    features = sorted(
        _list(document.get("features")),
        key=lambda feature: (
            _version_key(_mapping(feature).get("target_version")),
            str(_mapping(feature).get("id", "")),
        ),
    )
    counts = {status: 0 for status in sorted(FEATURE_STATUSES)}
    for feature in features:
        status = _mapping(feature).get("status")
        if status in counts:
            counts[status] += 1

    lines = [
        "# ReefVision 2.0 Feature Inventory",
        "",
        "> Generated from `REEFVISION_2_0_FEATURE_INVENTORY.json`. Do not edit by hand.",
        "",
        f"Updated: `{document.get('updated_at', '')}`",
        f"Candidate target: `{document.get('candidate_target', '')}`",
        "",
        "## Status summary",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {status} | {counts[status]} |" for status in sorted(counts))
    lines.extend(
        [
            "",
            "## Features",
            "",
            "| Version | Feature | Status | Entry point or boundary |",
            "| --- | --- | --- | --- |",
        ]
    )
    for raw_feature in features:
        feature = _mapping(raw_feature)
        boundary = feature.get("entry_point") or feature.get("notes") or "Non-UI contract"
        lines.append(
            "| "
            + " | ".join(
                _escape_cell(value)
                for value in (
                    feature.get("target_version", ""),
                    feature.get("title", ""),
                    feature.get("status", ""),
                    boundary,
                )
            )
            + " |"
        )

    lines.extend(["", "## Feature evidence", ""])
    for raw_feature in features:
        feature = _mapping(raw_feature)
        dependencies = ", ".join(f"`{item}`" for item in _list(feature.get("dependencies")))
        lines.extend(
            [
                f"### {feature.get('id', '')}: {feature.get('title', '')}",
                "",
                f"- Target: `{feature.get('target_version', '')}`",
                f"- Status: `{feature.get('status', '')}`",
                f"- Dependencies: {dependencies or 'None'}",
                f"- Entry point: {feature.get('entry_point') or 'Not user-facing'}",
                f"- Workflow Builder: `{feature.get('workflow_builder', '')}`",
            ]
        )
        if _nonempty_string(feature.get("missing_input")):
            lines.append(f"- Missing input: {feature['missing_input']}")
        if _nonempty_string(feature.get("defer_reason")):
            lines.append(f"- Deferral: {feature['defer_reason']}")
        lines.extend(["", "Acceptance checks:", ""])
        for check in _list(feature.get("acceptance_checks")):
            check_map = _mapping(check)
            lines.append(
                f"- **{check_map.get('status', '')}** — {check_map.get('description', '')} "
                f"(`{check_map.get('id', '')}`)"
            )
        lines.extend(["", "Evidence:", ""])
        evidence = _mapping(feature.get("evidence"))
        for kind in EVIDENCE_KINDS:
            records = _list(evidence.get(kind))
            if not records:
                lines.append(f"- `{kind}`: none recorded")
                continue
            for record in records:
                record_map = _mapping(record)
                lines.append(
                    f"- `{kind}`: {record_map.get('description', '')} "
                    f"— `{record_map.get('artifact', '')}` (`{record_map.get('id', '')}`)"
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--render", type=Path, default=DEFAULT_RENDER)
    parser.add_argument("--check-render", action="store_true")
    args = parser.parse_args(argv)

    try:
        document = load_inventory(args.inventory)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"inventory load failed: {exc}", file=sys.stderr)
        return 2

    errors = validate_inventory(document)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    rendered = render_inventory(document)
    if args.check_render:
        try:
            current = args.render.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"rendered inventory unavailable: {exc}", file=sys.stderr)
            return 1
        if current != rendered:
            print(
                "rendered inventory is stale; run the validator without --check-render",
                file=sys.stderr,
            )
            return 1
    else:
        args.render.parent.mkdir(parents=True, exist_ok=True)
        args.render.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"validated {len(_list(document.get('features')))} feature records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

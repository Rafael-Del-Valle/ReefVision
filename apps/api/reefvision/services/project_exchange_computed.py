"""Validate and remap computed scientific evidence without rewriting source provenance."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from math import isclose
from typing import Any

from pydantic import ValidationError as SchemaError

from reefvision.domain.computed_metrics import (
    FORMULA_ENGINE_VERSION,
    MetricExpressionError,
    MetricQuantity,
    evaluate_expression,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.computed_metrics import ComputedMetricDefinitionCreate
from reefvision.schemas.scientific_data import ScientificRecordResponse
from reefvision.services.computed_metrics import ComputedMetricService
from reefvision.services.scientific_data import content_hash

COMPUTED_SECTIONS = {"computed_metric_definitions", "computed_metric_results"}


def _definition_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "expression": row["expression"],
        "formula_version": row["formula_version"],
        "inputs": row["input_spec_json"],
        "output_unit": row["output_unit"],
    }


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _snapshot(
    row: dict[str, Any],
    *,
    project_id: str,
    calibration_current: bool | None,
    environmental_snapshot_current: bool | None,
) -> dict[str, Any]:
    return ScientificRecordResponse.model_validate(
        {
            **row["payload_json"],
            "id": row["id"],
            "project_id": project_id,
            "content_sha256": row["content_sha256"],
            "calibration_current": calibration_current,
            "environmental_snapshot_current": environmental_snapshot_current,
        }
    ).model_dump(mode="json")


def _same_number(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return left == right
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    return isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)


def validate_computed_exchange_records(
    project_id: str, sections: dict[str, list[dict[str, Any]]]
) -> None:
    """Reject computed rows that cannot be reproduced from archived scientific inputs."""

    definitions = {row["id"]: row for row in sections.get("computed_metric_definitions", [])}
    scientific = {row["id"]: row for row in sections.get("scientific_records", [])}
    try:
        compiled_by_id: dict[str, Any] = {}
        for identifier, row in definitions.items():
            if row.get("project_id") != project_id:
                raise ValidationError("Foreign project reference in computed metric definitions")
            if row.get("formula_version") != FORMULA_ENGINE_VERSION:
                raise ValidationError(
                    f"Unsupported computed metric formula version: {row.get('formula_version')}"
                )
            if content_hash(_definition_payload(row)) != row.get("definition_sha256"):
                raise ValidationError("Computed metric definition checksum mismatch")
            payload = ComputedMetricDefinitionCreate.model_validate(
                {
                    "name": row["name"],
                    "expression": row["expression"],
                    "inputs": row["input_spec_json"],
                    "output_unit": row["output_unit"],
                }
            )
            compiled_by_id[identifier] = ComputedMetricService._compile_definition(payload)

        for row in sections.get("computed_metric_results", []):
            if row.get("project_id") != project_id:
                raise ValidationError("Foreign project reference in computed metric results")
            payload = row["payload_json"]
            if not isinstance(payload, dict) or content_hash(payload) != row.get("content_sha256"):
                raise ValidationError("Computed metric result checksum mismatch")
            definition_id = row.get("definition_id")
            if not isinstance(definition_id, str):
                raise ValidationError("Computed metric result definition ID is invalid")
            definition = definitions.get(definition_id)
            if definition is None or payload.get("definition_id") != definition_id:
                raise ValidationError("Computed metric result refers to a missing definition")
            for field, definition_field in (
                ("definition_name", "name"),
                ("expression", "expression"),
                ("formula_version", "formula_version"),
                ("definition_sha256", "definition_sha256"),
            ):
                if payload.get(field) != definition.get(definition_field):
                    raise ValidationError("Computed metric result definition snapshot mismatch")
            bindings = payload.get("input_record_ids")
            snapshots = payload.get("input_snapshot")
            if not isinstance(bindings, dict) or not isinstance(snapshots, dict):
                raise ValidationError("Computed metric result input inventory is invalid")
            specs = definition["input_spec_json"]
            symbols = {item["symbol"] for item in specs}
            if set(bindings) != symbols or set(snapshots) != symbols:
                raise ValidationError("Computed metric result inputs do not match its definition")

            quantities: dict[str, MetricQuantity] = {}
            expected_hashes: dict[str, str] = {}
            for symbol, record_id in bindings.items():
                record = scientific.get(record_id)
                if record is None:
                    raise ValidationError("Computed metric result refers to a missing input record")
                archived_snapshot = snapshots[symbol]
                if not isinstance(archived_snapshot, dict):
                    raise ValidationError("Computed metric result input snapshot is invalid")
                expected = _snapshot(
                    record,
                    project_id=project_id,
                    calibration_current=archived_snapshot.get("calibration_current"),
                    environmental_snapshot_current=archived_snapshot.get(
                        "environmental_snapshot_current"
                    ),
                )
                if archived_snapshot != expected:
                    raise ValidationError("Computed metric result input snapshot mismatch")
                uncertainty = archived_snapshot.get("uncertainty")
                quantities[symbol] = MetricQuantity(
                    value=archived_snapshot["value"],
                    unit=archived_snapshot["unit"],
                    uncertainty=(uncertainty["value"] if uncertainty is not None else None),
                )
                expected_hashes[symbol] = record["content_sha256"]

            provenance = payload.get("provenance")
            if (
                not isinstance(provenance, dict)
                or provenance.get("input_content_sha256") != expected_hashes
            ):
                raise ValidationError("Computed metric input checksum provenance mismatch")
            if (
                provenance.get("formula_engine") != FORMULA_ENGINE_VERSION
                or provenance.get("definition_sha256") != definition["definition_sha256"]
            ):
                raise ValidationError("Computed metric formula engine provenance mismatch")
            first_snapshot = snapshots[next(iter(sorted(symbols)))]
            expected_subject = {
                key: value for key, value in first_snapshot["subject"].items() if value is not None
            }
            if payload.get("subject") != expected_subject:
                raise ValidationError("Computed metric result subject snapshot mismatch")
            evaluation = evaluate_expression(
                compiled_by_id[definition_id], quantities, output_unit=definition["output_unit"]
            )
            expected_values = {
                "value": evaluation.value,
                "normalized_value": evaluation.normalized_value,
                "uncertainty": evaluation.uncertainty,
                "normalized_uncertainty": evaluation.normalized_uncertainty,
            }
            if any(
                not _same_number(payload.get(key), value) for key, value in expected_values.items()
            ):
                raise ValidationError("Computed metric result is not reproducible from its inputs")
            for key, value in (
                ("unit", evaluation.unit),
                ("normalized_unit", evaluation.normalized_unit),
                ("dimension", evaluation.dimension),
            ):
                if payload.get(key) != value:
                    raise ValidationError("Computed metric result unit metadata mismatch")
            observed_at = _utc(row["observed_at"])
            if _utc(payload["observed_at"]) != observed_at or any(
                _utc(snapshot["observed_at"]) != observed_at for snapshot in snapshots.values()
            ):
                raise ValidationError("Computed metric observation timestamp mismatch")
    except ValidationError:
        raise
    except (KeyError, TypeError, ValueError, SchemaError, MetricExpressionError) as exc:
        raise ValidationError("Invalid computed metric exchange inventory") from exc


def remap_computed_sections(
    sections: dict[str, list[dict[str, Any]]],
    id_map: dict[str, str],
    remapped_science: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Remap declared computed links and rebuild snapshots from remapped science."""

    result = {name: deepcopy(sections.get(name, [])) for name in COMPUTED_SECTIONS}
    remapped_records = {
        source["id"]: mapped
        for source, mapped in zip(
            sections.get("scientific_records", []),
            remapped_science.get("scientific_records", []),
            strict=True,
        )
    }
    for row in result["computed_metric_results"]:
        payload = row["payload_json"]
        source_snapshots = payload["input_snapshot"]
        mapped_bindings: dict[str, str] = {}
        mapped_snapshots: dict[str, dict[str, Any]] = {}
        mapped_hashes: dict[str, str] = {}
        for symbol, old_record_id in payload["input_record_ids"].items():
            mapped_record = remapped_records[old_record_id]
            new_record_id = id_map[old_record_id]
            mapped_bindings[symbol] = new_record_id
            mapped_snapshots[symbol] = _snapshot(
                {**mapped_record, "id": new_record_id},
                project_id=id_map[row["project_id"]],
                calibration_current=source_snapshots[symbol].get("calibration_current"),
                environmental_snapshot_current=source_snapshots[symbol].get(
                    "environmental_snapshot_current"
                ),
            )
            mapped_hashes[symbol] = mapped_record["content_sha256"]
        payload["definition_id"] = id_map[payload["definition_id"]]
        payload["input_record_ids"] = mapped_bindings
        payload["input_snapshot"] = mapped_snapshots
        subject = next(iter(mapped_snapshots.values()))["subject"]
        payload["subject"] = {key: value for key, value in subject.items() if value is not None}
        payload["provenance"]["input_content_sha256"] = mapped_hashes
        row["content_sha256"] = content_hash(payload)
    return result

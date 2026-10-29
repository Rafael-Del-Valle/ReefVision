"""Project-scoped, immutable computed metric persistence and validation."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import Project, ScientificRecord
from reefvision.db.models.computed_metric import ComputedMetricDefinition, ComputedMetricResult
from reefvision.domain.computed_metrics import (
    FORMULA_ENGINE_VERSION,
    CompiledMetricExpression,
    MetricExpressionError,
    MetricQuantity,
    compile_expression,
    evaluate_expression,
    validate_expression_dimensions,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.domain.scientific_units import UNITS
from reefvision.schemas.computed_metrics import (
    ComputedMetricDefinitionCreate,
    ComputedMetricDefinitionPage,
    ComputedMetricDefinitionResponse,
    ComputedMetricInputSpec,
    ComputedMetricResultPage,
    ComputedMetricResultResponse,
)
from reefvision.schemas.scientific_data import ScientificRecordResponse
from reefvision.services.scientific_data import ScientificDataService, content_hash

_REPRESENTATIVE_UNITS = {
    "dimensionless": "1",
    "length": "m",
    "area": "m2",
    "time": "s",
    "speed": "m/s",
    "temperature": "degC",
    "practical_salinity": "PSU",
    "mass_salinity": "g/kg",
    "count": "count",
    "count_density": "count/m2",
    "count_rate": "count/s",
    "angle": "degree",
    "pixel_length": "px",
    "pixel_area": "px2",
}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _csv_text(value: str) -> str:
    """Keep user-authored names and expressions inert in spreadsheet programs."""
    return (
        "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value
    )


def _definition_payload(
    *,
    name: str,
    expression: str,
    inputs: list[dict[str, str]],
    output_unit: str,
    formula_version: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "expression": expression,
        "formula_version": formula_version,
        "inputs": inputs,
        "output_unit": output_unit,
    }


class ComputedMetricService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def require_project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    @staticmethod
    def _compile_definition(
        payload: ComputedMetricDefinitionCreate,
    ) -> CompiledMetricExpression:
        try:
            compiled = compile_expression(
                payload.expression, {item.symbol for item in payload.inputs}
            )
            validate_expression_dimensions(
                compiled,
                {item.symbol: _REPRESENTATIVE_UNITS[item.dimension] for item in payload.inputs},
                output_unit=payload.output_unit,
            )
            return compiled
        except MetricExpressionError as exc:
            raise ValidationError(str(exc)) from exc

    def create_definition(
        self, project_id: str, payload: ComputedMetricDefinitionCreate
    ) -> ComputedMetricDefinition:
        self.require_project(project_id)
        self._compile_definition(payload)
        inputs = [item.model_dump(mode="json") for item in payload.inputs]
        definition_payload = _definition_payload(
            name=payload.name,
            expression=payload.expression,
            inputs=inputs,
            output_unit=payload.output_unit,
            formula_version=FORMULA_ENGINE_VERSION,
        )
        row = ComputedMetricDefinition(
            id=str(uuid4()),
            project_id=project_id,
            name=payload.name,
            expression=payload.expression,
            formula_version=FORMULA_ENGINE_VERSION,
            input_spec_json=inputs,
            output_unit=payload.output_unit,
            definition_sha256=content_hash(definition_payload),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def definition_response(
        self, row: ComputedMetricDefinition
    ) -> ComputedMetricDefinitionResponse:
        expected = content_hash(
            _definition_payload(
                name=row.name,
                expression=row.expression,
                inputs=row.input_spec_json,
                output_unit=row.output_unit,
                formula_version=row.formula_version,
            )
        )
        if expected != row.definition_sha256:
            raise ConflictError("Computed metric definition checksum mismatch")
        return ComputedMetricDefinitionResponse.model_validate(
            {
                "id": row.id,
                "project_id": row.project_id,
                "name": row.name,
                "expression": row.expression,
                "formula_version": row.formula_version,
                "inputs": row.input_spec_json,
                "output_unit": row.output_unit,
                "definition_sha256": row.definition_sha256,
                "created_at": _utc(row.created_at),
            }
        )

    def get_definition(self, project_id: str, definition_id: str) -> ComputedMetricDefinition:
        row = self.session.get(ComputedMetricDefinition, definition_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("Computed metric definition not found")
        self.definition_response(row)
        return row

    def list_definitions(
        self, project_id: str, *, limit: int, offset: int
    ) -> ComputedMetricDefinitionPage:
        self.require_project(project_id)
        query = select(ComputedMetricDefinition).where(
            ComputedMetricDefinition.project_id == project_id
        )
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(ComputedMetricDefinition.created_at, ComputedMetricDefinition.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return ComputedMetricDefinitionPage(
            items=[self.definition_response(row) for row in rows], total=total
        )

    @staticmethod
    def _source_category(subject: dict[str, Any]) -> str:
        if subject.get("prediction_id"):
            return "model_prediction"
        if subject.get("annotation_id") or subject.get("mask_id"):
            return "verified_annotation"
        return "scientific_observation"

    def calculate(
        self,
        project_id: str,
        definition_id: str,
        bindings: dict[str, str],
        *,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> ComputedMetricResult:
        definition = self.get_definition(project_id, definition_id)
        if definition.formula_version != FORMULA_ENGINE_VERSION:
            raise ValidationError(f"Unsupported formula version: {definition.formula_version}")
        specs = [
            ComputedMetricInputSpec.model_validate(item) for item in definition.input_spec_json
        ]
        symbols = {item.symbol for item in specs}
        if set(bindings) != symbols:
            raise ValidationError("Calculation bindings must exactly match definition inputs")
        if len(set(bindings.values())) != len(bindings):
            raise ValidationError(
                "Each input must bind a distinct scientific record; "
                "correlated bindings are unsupported"
            )
        if workflow_node_run_id is not None:
            existing = self.session.scalar(
                select(ComputedMetricResult).where(
                    ComputedMetricResult.workflow_node_run_id == workflow_node_run_id
                )
            )
            if existing is not None:
                replay_response = self.result_response(existing)
                if (
                    existing.definition_id != definition_id
                    or {key: str(value) for key, value in replay_response.input_record_ids.items()}
                    != bindings
                ):
                    raise ConflictError(
                        "Workflow metric replay conflicts with its persisted result"
                    )
                return existing

        scientific = ScientificDataService(self.session)
        records: dict[str, ScientificRecordResponse] = {}
        snapshots: dict[str, dict[str, Any]] = {}
        for spec in specs:
            scientific_row = self.session.get(ScientificRecord, bindings[spec.symbol])
            if scientific_row is None or scientific_row.project_id != project_id:
                raise ValidationError("All scientific inputs must belong to this project")
            scientific_response = scientific.response(scientific_row)
            if scientific_response.qc in ("suspect", "rejected"):
                raise ValidationError(
                    "Computed metrics cannot use suspect or rejected scientific observations"
                )
            if scientific_response.environmental_snapshot_current is False:
                raise ValidationError(
                    "Computed metrics cannot use superseded environmental observations"
                )
            if scientific_response.calibration_current is False:
                raise ValidationError(
                    "Computed metrics cannot use observations with stale image calibration"
                )
            if UNITS[scientific_response.unit][0] != spec.dimension:
                raise ValidationError(
                    f"Input {spec.symbol} requires {spec.dimension} units, "
                    f"got {scientific_response.unit}"
                )
            if (
                spec.dimension in {"length", "area"}
                and scientific_response.subject.image_id is not None
                and (
                    scientific_response.calibration_snapshot is None
                    or scientific_response.calibration_current is not True
                )
            ):
                raise ValidationError(
                    "Physical image length or area requires a current calibration snapshot"
                )
            records[spec.symbol] = scientific_response
            snapshots[spec.symbol] = scientific_response.model_dump(mode="json")

        subjects = [
            item.subject.model_dump(mode="json", exclude_none=True) for item in records.values()
        ]
        categories = {self._source_category(subject) for subject in subjects}
        if {"verified_annotation", "model_prediction"} <= categories:
            raise ValidationError(
                "Verified annotation metrics and model prediction metrics must remain separate"
            )
        if any(subject != subjects[0] for subject in subjects[1:]):
            raise ValidationError(
                "Metric inputs must have identical image/frame/object/run identity"
            )
        observed_times = [item.observed_at for item in records.values()]
        if any(value != observed_times[0] for value in observed_times[1:]):
            raise ValidationError("Metric inputs must share the exact observation time")
        if len(records) > 1:
            contexts = [
                (
                    item.location,
                    item.pixel,
                    item.depth_m,
                    item.depth_reference,
                    item.provenance.source,
                    item.provenance.dataset_id,
                    item.provenance.source_metadata,
                    item.provenance.source_url,
                )
                for item in records.values()
            ]
            if any(context != contexts[0] for context in contexts[1:]) or (
                not subjects[0]
                and (contexts[0][0] is None or contexts[0][2] is None or not contexts[0][5])
            ):
                raise ValidationError(
                    "Metric inputs require explicit shared contextual identity: matching location, "
                    "pixel, depth/reference, source/URL, dataset and station/source metadata; "
                    "inputs without a subject require known location, depth and dataset"
                )
        uncertainty_kinds = {
            record.uncertainty.kind for record in records.values() if record.uncertainty is not None
        }
        if "bound" in uncertainty_kinds or len(uncertainty_kinds) > 1:
            raise ValidationError(
                "Unsupported uncertainty kind combination: use one common standard_deviation "
                "or standard_error kind; bound propagation is not supported"
            )
        try:
            compiled = compile_expression(definition.expression, symbols)
            evaluation = evaluate_expression(
                compiled,
                {
                    symbol: MetricQuantity(
                        value=record.value,
                        unit=record.unit,
                        uncertainty=(record.uncertainty.value if record.uncertainty else None),
                    )
                    for symbol, record in records.items()
                },
                output_unit=definition.output_unit,
            )
        except MetricExpressionError as exc:
            raise ValidationError(str(exc)) from exc
        result_payload: dict[str, Any] = {
            "schema_version": "1.1.0",
            "definition_id": definition.id,
            "definition_name": definition.name,
            "expression": definition.expression,
            "formula_version": definition.formula_version,
            "definition_sha256": definition.definition_sha256,
            "value": evaluation.value,
            "unit": evaluation.unit,
            "normalized_value": evaluation.normalized_value,
            "normalized_unit": evaluation.normalized_unit,
            "uncertainty": evaluation.uncertainty,
            "normalized_uncertainty": evaluation.normalized_uncertainty,
            "dimension": evaluation.dimension,
            "observed_at": observed_times[0].isoformat(),
            "subject": subjects[0],
            "input_record_ids": bindings,
            "input_snapshot": snapshots,
            "provenance": {
                "formula_engine": FORMULA_ENGINE_VERSION,
                "definition_sha256": definition.definition_sha256,
                "input_content_sha256": {
                    symbol: record.content_sha256 for symbol, record in records.items()
                },
                "source_categories": sorted(categories),
                "uncertainty_kind": (
                    next(iter(uncertainty_kinds)) if evaluation.uncertainty is not None else None
                ),
                "uncertainty_method": (
                    "independent_first_order_root_sum_square"
                    if evaluation.uncertainty is not None
                    else "unavailable_missing_input_uncertainty"
                ),
            },
        }
        result_row = ComputedMetricResult(
            id=str(uuid4()),
            project_id=project_id,
            definition_id=definition.id,
            observed_at=observed_times[0],
            payload_json=result_payload,
            content_sha256=content_hash(result_payload),
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
        )
        self.session.add(result_row)
        self.session.flush()
        return result_row

    def result_response(self, row: ComputedMetricResult) -> ComputedMetricResultResponse:
        if content_hash(row.payload_json) != row.content_sha256:
            raise ConflictError("Computed metric result checksum mismatch")
        return ComputedMetricResultResponse.model_validate(
            {
                **row.payload_json,
                "id": row.id,
                "project_id": row.project_id,
                "content_sha256": row.content_sha256,
                "workflow_run_id": row.workflow_run_id,
                "workflow_node_run_id": row.workflow_node_run_id,
                "created_at": _utc(row.created_at),
            }
        )

    def list_results(self, project_id: str, *, limit: int, offset: int) -> ComputedMetricResultPage:
        self.require_project(project_id)
        query = select(ComputedMetricResult).where(ComputedMetricResult.project_id == project_id)
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(ComputedMetricResult.created_at, ComputedMetricResult.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return ComputedMetricResultPage(
            items=[self.result_response(row) for row in rows], total=total
        )

    def export_csv(self, project_id: str) -> str:
        self.require_project(project_id)
        rows = self.session.scalars(
            select(ComputedMetricResult)
            .where(ComputedMetricResult.project_id == project_id)
            .order_by(ComputedMetricResult.created_at, ComputedMetricResult.id)
            .execution_options(yield_per=500)
        )
        output = io.StringIO(newline="")
        fieldnames = [
            "result_id",
            "definition_id",
            "definition_name",
            "expression",
            "formula_version",
            "definition_sha256",
            "value",
            "unit",
            "uncertainty",
            "normalized_value",
            "normalized_unit",
            "normalized_uncertainty",
            "workflow_run_id",
            "workflow_node_run_id",
            "observed_at_utc",
            "subject_json",
            "input_record_ids_json",
            "input_snapshot_json",
            "provenance_json",
            "content_sha256",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            item = self.result_response(row)
            writer.writerow(
                {
                    "result_id": str(item.id),
                    "definition_id": str(item.definition_id),
                    "definition_name": _csv_text(item.definition_name),
                    "expression": _csv_text(item.expression),
                    "formula_version": item.formula_version,
                    "definition_sha256": item.definition_sha256,
                    "value": item.value,
                    "unit": item.unit,
                    "uncertainty": item.uncertainty,
                    "normalized_value": item.normalized_value,
                    "normalized_unit": item.normalized_unit,
                    "normalized_uncertainty": item.normalized_uncertainty,
                    "workflow_run_id": str(item.workflow_run_id) if item.workflow_run_id else "",
                    "workflow_node_run_id": str(item.workflow_node_run_id)
                    if item.workflow_node_run_id
                    else "",
                    "observed_at_utc": item.observed_at.isoformat(),
                    "subject_json": json.dumps(item.subject, sort_keys=True),
                    "input_record_ids_json": json.dumps(
                        {key: str(value) for key, value in item.input_record_ids.items()},
                        sort_keys=True,
                    ),
                    "input_snapshot_json": json.dumps(item.input_snapshot, sort_keys=True),
                    "provenance_json": json.dumps(item.provenance, sort_keys=True),
                    "content_sha256": item.content_sha256,
                }
            )
        return output.getvalue()

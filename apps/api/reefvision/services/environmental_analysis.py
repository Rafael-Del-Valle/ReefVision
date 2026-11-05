"""Project-scoped immutable persistence for composite environmental analyses."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models.environmental_analysis import (
    EnvironmentalAnalysisDefinition,
    EnvironmentalAnalysisResult,
)
from reefvision.db.models.scientific_record import ScientificRecord
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.environmental_analysis import (
    EnvironmentalAnalysisDefinitionPage,
    EnvironmentalAnalysisDefinitionResponse,
    EnvironmentalAnalysisKind,
    EnvironmentalAnalysisResultPage,
    EnvironmentalAnalysisResultResponse,
    LunarAnalysisBatchRequest,
    LunarAnalysisBatchResponse,
)
from reefvision.schemas.lunar_context import LunarContextRequest
from reefvision.services.lunar_context import ALGORITHM, calculate_lunar_context
from reefvision.services.scientific_data import ScientificDataService, content_hash


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class EnvironmentalAnalysisService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.science = ScientificDataService(session)

    @staticmethod
    def _definition_content(
        *, analysis_kind: str, name: str, configuration: dict[str, Any], calculation_version: str
    ) -> dict[str, Any]:
        return {
            "analysis_kind": analysis_kind,
            "name": name,
            "configuration": configuration,
            "calculation_version": calculation_version,
        }

    def create_definition(
        self,
        project_id: str,
        *,
        analysis_kind: EnvironmentalAnalysisKind,
        name: str,
        configuration: dict[str, Any],
        calculation_version: str,
    ) -> EnvironmentalAnalysisDefinition:
        self.science.require_project(project_id)
        content = self._definition_content(
            analysis_kind=analysis_kind,
            name=name,
            configuration=configuration,
            calculation_version=calculation_version,
        )
        row = EnvironmentalAnalysisDefinition(
            project_id=project_id,
            analysis_kind=analysis_kind,
            name=name,
            configuration_json=configuration,
            calculation_version=calculation_version,
            definition_sha256=content_hash(content),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def _definition_hash(self, row: EnvironmentalAnalysisDefinition) -> str:
        return content_hash(
            self._definition_content(
                analysis_kind=row.analysis_kind,
                name=row.name,
                configuration=row.configuration_json,
                calculation_version=row.calculation_version,
            )
        )

    def get_definition(
        self, project_id: str, definition_id: str
    ) -> EnvironmentalAnalysisDefinition:
        self.science.require_project(project_id)
        row = self.session.get(EnvironmentalAnalysisDefinition, definition_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("Environmental analysis definition not found")
        if self._definition_hash(row) != row.definition_sha256:
            raise ConflictError("Environmental analysis definition checksum mismatch")
        return row

    def definition_response(
        self, row: EnvironmentalAnalysisDefinition
    ) -> EnvironmentalAnalysisDefinitionResponse:
        if self._definition_hash(row) != row.definition_sha256:
            raise ConflictError("Environmental analysis definition checksum mismatch")
        return EnvironmentalAnalysisDefinitionResponse(
            id=row.id,
            project_id=row.project_id,
            analysis_kind=row.analysis_kind,
            name=row.name,
            configuration=row.configuration_json,
            calculation_version=row.calculation_version,
            definition_sha256=row.definition_sha256,
            created_at=_utc(row.created_at),
        )

    def list_definitions(
        self,
        project_id: str,
        *,
        analysis_kind: EnvironmentalAnalysisKind | None,
        limit: int,
        offset: int,
    ) -> EnvironmentalAnalysisDefinitionPage:
        self.science.require_project(project_id)
        filters = [EnvironmentalAnalysisDefinition.project_id == project_id]
        if analysis_kind is not None:
            filters.append(EnvironmentalAnalysisDefinition.analysis_kind == analysis_kind)
        total = self.session.scalar(
            select(func.count()).select_from(EnvironmentalAnalysisDefinition).where(*filters)
        )
        rows = self.session.scalars(
            select(EnvironmentalAnalysisDefinition)
            .where(*filters)
            .order_by(
                EnvironmentalAnalysisDefinition.created_at, EnvironmentalAnalysisDefinition.id
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return EnvironmentalAnalysisDefinitionPage(
            items=[self.definition_response(row) for row in rows], total=int(total or 0)
        )

    @staticmethod
    def _result_content(
        *,
        project_id: str,
        definition_id: str,
        definition_sha256: str,
        analysis_kind: str,
        observed_at: datetime,
        payload: dict[str, Any],
        input_snapshot: dict[str, Any],
        source_record_ids: list[str],
        source_analysis_result_ids: list[str],
        quality_control: dict[str, Any],
        uncertainty: dict[str, Any] | None,
        workflow_run_id: str | None,
        workflow_node_run_id: str | None,
    ) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "definition_id": definition_id,
            "definition_sha256": definition_sha256,
            "analysis_kind": analysis_kind,
            "observed_at": _utc(observed_at).isoformat(),
            "payload": payload,
            "input_snapshot": input_snapshot,
            "source_record_ids": source_record_ids,
            "source_analysis_result_ids": source_analysis_result_ids,
            "quality_control": quality_control,
            "uncertainty": uncertainty,
            "workflow_run_id": workflow_run_id,
            "workflow_node_run_id": workflow_node_run_id,
        }

    def create_result(
        self,
        definition: EnvironmentalAnalysisDefinition,
        *,
        observed_at: datetime,
        payload: dict[str, Any],
        input_snapshot: dict[str, Any],
        source_record_ids: list[str] | None = None,
        source_analysis_result_ids: list[str] | None = None,
        quality_control: dict[str, Any],
        uncertainty: dict[str, Any] | None,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> EnvironmentalAnalysisResult:
        source_record_ids = source_record_ids or []
        source_analysis_result_ids = source_analysis_result_ids or []
        if len(set(source_record_ids)) != len(source_record_ids):
            raise ValidationError("Source scientific record identifiers must be unique")
        if len(set(source_analysis_result_ids)) != len(source_analysis_result_ids):
            raise ValidationError("Source analysis result identifiers must be unique")
        for record_id in source_record_ids:
            record = self.session.get(ScientificRecord, record_id)
            if record is None or record.project_id != definition.project_id:
                raise ValidationError("Source scientific records must belong to this project")
        for result_id in source_analysis_result_ids:
            result = self.session.get(EnvironmentalAnalysisResult, result_id)
            if result is None or result.project_id != definition.project_id:
                raise ValidationError("Source analysis results must belong to this project")
        content = self._result_content(
            project_id=definition.project_id,
            definition_id=definition.id,
            definition_sha256=definition.definition_sha256,
            analysis_kind=definition.analysis_kind,
            observed_at=observed_at,
            payload=payload,
            input_snapshot=input_snapshot,
            source_record_ids=source_record_ids,
            source_analysis_result_ids=source_analysis_result_ids,
            quality_control=quality_control,
            uncertainty=uncertainty,
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
        )
        row = EnvironmentalAnalysisResult(
            project_id=definition.project_id,
            definition_id=definition.id,
            analysis_kind=definition.analysis_kind,
            observed_at=_utc(observed_at),
            payload_json=payload,
            input_snapshot_json=input_snapshot,
            source_record_ids_json=source_record_ids,
            source_analysis_result_ids_json=source_analysis_result_ids,
            quality_control_json=quality_control,
            uncertainty_json=uncertainty,
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
            content_sha256=content_hash(content),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def _result_hash(self, row: EnvironmentalAnalysisResult) -> str:
        definition = self.get_definition(row.project_id, row.definition_id)
        return content_hash(
            self._result_content(
                project_id=row.project_id,
                definition_id=row.definition_id,
                definition_sha256=definition.definition_sha256,
                analysis_kind=row.analysis_kind,
                observed_at=row.observed_at,
                payload=row.payload_json,
                input_snapshot=row.input_snapshot_json,
                source_record_ids=row.source_record_ids_json,
                source_analysis_result_ids=row.source_analysis_result_ids_json,
                quality_control=row.quality_control_json,
                uncertainty=row.uncertainty_json,
                workflow_run_id=row.workflow_run_id,
                workflow_node_run_id=row.workflow_node_run_id,
            )
        )

    def get_result(self, project_id: str, result_id: str) -> EnvironmentalAnalysisResult:
        self.science.require_project(project_id)
        row = self.session.get(EnvironmentalAnalysisResult, result_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("Environmental analysis result not found")
        if self._result_hash(row) != row.content_sha256:
            raise ConflictError("Environmental analysis result checksum mismatch")
        return row

    def result_response(
        self, row: EnvironmentalAnalysisResult
    ) -> EnvironmentalAnalysisResultResponse:
        if self._result_hash(row) != row.content_sha256:
            raise ConflictError("Environmental analysis result checksum mismatch")
        return EnvironmentalAnalysisResultResponse(
            id=row.id,
            project_id=row.project_id,
            definition_id=row.definition_id,
            analysis_kind=row.analysis_kind,
            observed_at=_utc(row.observed_at),
            payload=row.payload_json,
            input_snapshot=row.input_snapshot_json,
            source_record_ids=row.source_record_ids_json,
            source_analysis_result_ids=row.source_analysis_result_ids_json,
            quality_control=row.quality_control_json,
            uncertainty=row.uncertainty_json,
            content_sha256=row.content_sha256,
            workflow_run_id=row.workflow_run_id,
            workflow_node_run_id=row.workflow_node_run_id,
            created_at=_utc(row.created_at),
        )

    def list_results(
        self,
        project_id: str,
        *,
        analysis_kind: EnvironmentalAnalysisKind | None,
        limit: int,
        offset: int,
    ) -> EnvironmentalAnalysisResultPage:
        self.science.require_project(project_id)
        filters = [EnvironmentalAnalysisResult.project_id == project_id]
        if analysis_kind is not None:
            filters.append(EnvironmentalAnalysisResult.analysis_kind == analysis_kind)
        total = self.session.scalar(
            select(func.count()).select_from(EnvironmentalAnalysisResult).where(*filters)
        )
        rows = self.session.scalars(
            select(EnvironmentalAnalysisResult)
            .where(*filters)
            .order_by(EnvironmentalAnalysisResult.created_at, EnvironmentalAnalysisResult.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return EnvironmentalAnalysisResultPage(
            items=[self.result_response(row) for row in rows], total=int(total or 0)
        )

    def create_lunar_batch(
        self, project_id: str, request: LunarAnalysisBatchRequest
    ) -> LunarAnalysisBatchResponse:
        definition = self.create_definition(
            project_id,
            analysis_kind="lunar_context",
            name=request.name,
            configuration={
                "algorithm": ALGORITHM,
                "reference_frame": "geocentric_approximate",
                "computation": "offline_deterministic",
            },
            calculation_version=ALGORITHM,
        )
        rows = []
        for observed_at in request.observed_at:
            lunar = calculate_lunar_context(
                self.session, project_id, LunarContextRequest(observed_at=observed_at)
            )
            payload = lunar.model_dump(mode="json")
            rows.append(
                self.create_result(
                    definition,
                    observed_at=observed_at,
                    payload=payload,
                    input_snapshot={"observed_at": observed_at.isoformat()},
                    quality_control={
                        "status": "accepted",
                        "method": "deterministic_offline_calculation",
                        "flags": ["low_precision_geocentric_approximation"],
                    },
                    uncertainty={
                        "type": "methodological",
                        "statement": (
                            "Truncated geocentric longitude series; not a high-precision ephemeris"
                        ),
                    },
                )
            )
        self.session.commit()
        return LunarAnalysisBatchResponse(
            definition=self.definition_response(definition),
            results=[self.result_response(row) for row in rows],
        )

    def result_csv(self, project_id: str, result_id: str) -> str:
        response = self.result_response(self.get_result(project_id, result_id))
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(
            [
                "result_id",
                "definition_id",
                "analysis_kind",
                "observed_at_utc",
                "content_sha256",
                "payload_json",
                "input_snapshot_json",
                "quality_control_json",
                "uncertainty_json",
                "source_record_ids",
                "source_analysis_result_ids",
            ]
        )
        writer.writerow(
            [
                str(response.id),
                str(response.definition_id),
                response.analysis_kind,
                response.observed_at.isoformat(),
                response.content_sha256,
                json.dumps(response.payload, sort_keys=True, separators=(",", ":")),
                json.dumps(response.input_snapshot, sort_keys=True, separators=(",", ":")),
                json.dumps(response.quality_control, sort_keys=True, separators=(",", ":")),
                json.dumps(response.uncertainty, sort_keys=True, separators=(",", ":")),
                ";".join(str(value) for value in response.source_record_ids),
                ";".join(str(value) for value in response.source_analysis_result_ids),
            ]
        )
        return output.getvalue()

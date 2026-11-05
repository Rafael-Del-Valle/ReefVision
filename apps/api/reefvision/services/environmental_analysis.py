"""Project-scoped immutable persistence for composite environmental analyses."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models.environmental_analysis import (
    EnvironmentalAnalysisDefinition,
    EnvironmentalAnalysisResult,
)
from reefvision.db.models.scientific_record import ScientificRecord
from reefvision.db.models.workflow_execution import WorkflowNodeRun, WorkflowRun
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.environmental_analysis import (
    EnvironmentalAnalysisDefinitionPage,
    EnvironmentalAnalysisDefinitionResponse,
    EnvironmentalAnalysisKind,
    EnvironmentalAnalysisResultPage,
    EnvironmentalAnalysisResultResponse,
    EnvironmentalAnalysisSingleResponse,
    EnvironmentalAnalysisValidationResponse,
    EventWindowAnalysisRequest,
    LaggedComparisonAnalysisRequest,
    LunarAnalysisBatchRequest,
    LunarAnalysisBatchResponse,
    ObservationEnvironmentJoinRequest,
    TidalContextAnalysisRequest,
)
from reefvision.schemas.lunar_context import LunarContextRequest
from reefvision.services.environmental_context import EnvironmentalContextService
from reefvision.services.geographic_movement_analytics import geographic_distance_m
from reefvision.services.lunar_context import ALGORITHM, calculate_lunar_context
from reefvision.services.scientific_data import ScientificDataService, content_hash


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


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

    def _currentness_reasons(
        self, row: EnvironmentalAnalysisResult, visited: set[str]
    ) -> list[str]:
        if row.id in visited:
            return [f"source_analysis_cycle:{row.id}"]
        visited.add(row.id)
        reasons: list[str] = []
        try:
            if self._result_hash(row) != row.content_sha256:
                reasons.append(f"result_checksum_mismatch:{row.id}")
        except (ConflictError, NotFoundError, ValidationError):
            reasons.append(f"result_invalid:{row.id}")

        for record_id in row.source_record_ids_json:
            record = self.session.get(ScientificRecord, record_id)
            if record is None or record.project_id != row.project_id:
                reasons.append(f"source_record_missing:{record_id}")
                continue
            try:
                response = self.science.response(record)
            except (ConflictError, ValidationError):
                reasons.append(f"source_record_invalid:{record_id}")
                continue
            if response.environmental_snapshot_current is False:
                reasons.append(f"source_record_snapshot_stale:{record_id}")
            if response.calibration_current is False:
                reasons.append(f"source_record_calibration_stale:{record_id}")

        for source_result_id in row.source_analysis_result_ids_json:
            source = self.session.get(EnvironmentalAnalysisResult, source_result_id)
            if source is None or source.project_id != row.project_id:
                reasons.append(f"source_analysis_missing:{source_result_id}")
                continue
            nested = self._currentness_reasons(source, visited)
            reasons.extend(f"source_analysis:{source_result_id}:{reason}" for reason in nested)

        try:
            definition = self.get_definition(row.project_id, row.definition_id)
        except (ConflictError, NotFoundError):
            reasons.append(f"definition_invalid:{row.definition_id}")
        else:
            event_definition_id = definition.configuration_json.get("event_definition_id")
            if isinstance(event_definition_id, str):
                try:
                    EnvironmentalContextService(self.session).get_event_definition(
                        row.project_id, event_definition_id
                    )
                except (ConflictError, NotFoundError, ValidationError):
                    reasons.append(f"event_definition_invalid:{event_definition_id}")

        if row.workflow_run_id is not None:
            run = self.session.get(WorkflowRun, row.workflow_run_id)
            if run is None or run.project_id != row.project_id:
                reasons.append(f"workflow_run_invalid:{row.workflow_run_id}")
        if row.workflow_node_run_id is not None:
            node = self.session.get(WorkflowNodeRun, row.workflow_node_run_id)
            if node is None or node.workflow_run_id != row.workflow_run_id:
                reasons.append(f"workflow_node_run_invalid:{row.workflow_node_run_id}")

        visited.remove(row.id)
        return reasons

    def validate_result(
        self, project_id: str, result_id: str
    ) -> EnvironmentalAnalysisValidationResponse:
        self.science.require_project(project_id)
        row = self.session.get(EnvironmentalAnalysisResult, result_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("Environmental analysis result not found")
        reasons = sorted(set(self._currentness_reasons(row, set())))
        return EnvironmentalAnalysisValidationResponse(
            result_id=row.id,
            current=not reasons,
            result_sha256=row.content_sha256,
            reasons=reasons,
        )

    def create_lunar_batch(
        self,
        project_id: str,
        request: LunarAnalysisBatchRequest,
        *,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> LunarAnalysisBatchResponse:
        if workflow_node_run_id is not None and len(request.observed_at) != 1:
            raise ValidationError("Workflow lunar analysis requires exactly one timestamp")
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
                    workflow_run_id=workflow_run_id,
                    workflow_node_run_id=workflow_node_run_id,
                )
            )
        self.session.commit()
        return LunarAnalysisBatchResponse(
            definition=self.definition_response(definition),
            results=[self.result_response(row) for row in rows],
        )

    @staticmethod
    def _tidal_record_snapshot(record: Any, *, evidence_kind: str) -> dict[str, Any]:
        return {
            "record_id": str(record.id),
            "evidence_kind": evidence_kind,
            "observed_at": record.observed_at.isoformat(),
            "value_m": record.normalized_value,
            "unit": record.normalized_unit,
            "qc": record.qc,
            "qc_flags": record.qc_flags,
            "uncertainty": record.uncertainty.model_dump(mode="json")
            if record.uncertainty
            else None,
        }

    def create_tidal_context(
        self,
        project_id: str,
        request: TidalContextAnalysisRequest,
        *,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> EnvironmentalAnalysisSingleResponse:
        self.science.require_project(project_id)
        window = timedelta(seconds=request.max_time_delta_s)
        rows = self.session.scalars(
            select(ScientificRecord).where(
                ScientificRecord.project_id == project_id,
                ScientificRecord.variable.in_(["predicted_water_level", "observed_water_level"]),
                ScientificRecord.observed_at >= request.observed_at - window,
                ScientificRecord.observed_at <= request.observed_at + window,
            )
        ).all()
        candidates: dict[str, list[tuple[Any, float, float]]] = {
            "predicted_water_level": [],
            "observed_water_level": [],
        }
        for row in rows:
            record = self.science.response(row)
            metadata = record.provenance.source_metadata
            station = metadata.get("station")
            if not isinstance(station, dict) or str(station.get("id")) != request.station_id:
                continue
            if metadata.get("datum") != request.datum:
                continue
            if record.location is None or record.qc in ("suspect", "rejected"):
                continue
            if record.environmental_snapshot_current is False:
                continue
            distance = geographic_distance_m(
                request.location.latitude,
                request.location.longitude,
                record.location.latitude,
                record.location.longitude,
            )
            if distance > request.max_distance_m:
                continue
            delta = (record.observed_at - request.observed_at).total_seconds()
            candidates[row.variable].append((record, delta, distance))
        for values in candidates.values():
            values.sort(key=lambda item: (abs(item[1]), item[2], str(item[0].id)))
        predicted = candidates["predicted_water_level"]
        observed = candidates["observed_water_level"]
        if not predicted and not observed:
            raise ValidationError(
                "No current NOAA tidal records satisfy the station, datum, time and distance bounds"
            )

        nearest_predicted = predicted[0] if predicted else None
        nearest_observed = observed[0] if observed else None
        stage = "unknown"
        stage_reason = "At least one prediction on each side of the observation time is required"
        stage_records: list[Any] = []
        chronological = sorted(predicted, key=lambda item: item[0].observed_at)
        before = [item for item in chronological if item[0].observed_at < request.observed_at]
        after = [item for item in chronological if item[0].observed_at > request.observed_at]
        if before and after:
            previous = before[-1][0]
            following = after[0][0]
            difference = following.normalized_value - previous.normalized_value
            if difference > 0:
                stage = "rising_predicted"
            elif difference < 0:
                stage = "falling_predicted"
            else:
                stage = "stationary_predicted"
            stage_reason = "Derived from the bracketing NOAA prediction-series slope"
            stage_records = [previous, following]

        used: list[Any] = []
        for record in [
            nearest_predicted[0] if nearest_predicted else None,
            nearest_observed[0] if nearest_observed else None,
            *stage_records,
        ]:
            if record is not None and all(existing.id != record.id for existing in used):
                used.append(record)
        definition = self.create_definition(
            project_id,
            analysis_kind="tidal_context",
            name=request.name,
            configuration={
                "station_id": request.station_id,
                "datum": request.datum,
                "max_time_delta_s": request.max_time_delta_s,
                "max_distance_m": request.max_distance_m,
                "stage_policy": "bracketing_prediction_slope_only",
            },
            calculation_version="reefvision-tidal-context-1",
        )
        station_source = nearest_predicted or nearest_observed
        assert station_source is not None
        station_record = station_source[0]
        station_metadata = station_record.provenance.source_metadata["station"]
        station_distance = station_source[2]
        payload = {
            "schema_version": "1.1.0",
            "observed_at": request.observed_at.isoformat(),
            "station": {
                "id": request.station_id,
                "name": station_metadata.get("name"),
                "latitude": station_record.location.latitude,
                "longitude": station_record.location.longitude,
                "distance_m": station_distance,
                "datum": request.datum,
            },
            "observed": self._tidal_record_snapshot(nearest_observed[0], evidence_kind="observed")
            if nearest_observed
            else None,
            "predicted": self._tidal_record_snapshot(
                nearest_predicted[0], evidence_kind="predicted"
            )
            if nearest_predicted
            else None,
            "predicted_stage": stage,
            "predicted_stage_reason": stage_reason,
            "methodological_notes": [
                "Contextual descriptive evidence; no biological effect is inferred.",
                "Observed and predicted water levels are retained as separate evidence.",
                "Rising/falling labels use prediction-series slope, never observed height alone.",
            ],
        }
        result = self.create_result(
            definition,
            observed_at=request.observed_at,
            payload=payload,
            input_snapshot=request.model_dump(mode="json"),
            source_record_ids=[str(record.id) for record in used],
            quality_control={
                "status": "accepted" if used else "unavailable",
                "flags": sorted({flag for record in used for flag in record.qc_flags}),
            },
            uncertainty={
                "type": "source_and_matching",
                "statement": "See source-record uncertainty and signed time/distance offsets",
                "time_offsets_s": {
                    "predicted": nearest_predicted[1] if nearest_predicted else None,
                    "observed": nearest_observed[1] if nearest_observed else None,
                },
            },
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
        )
        self.session.commit()
        return EnvironmentalAnalysisSingleResponse(
            definition=self.definition_response(definition),
            result=self.result_response(result),
        )

    def create_event_window(
        self,
        project_id: str,
        request: EventWindowAnalysisRequest,
        *,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> EnvironmentalAnalysisSingleResponse:
        context = EnvironmentalContextService(self.session)
        legacy = context.get_event_definition(project_id, str(request.event_definition_id))
        legacy_response = context.event_definition_response(legacy)
        evaluation = context.evaluate_event_definition(project_id, str(request.event_definition_id))
        events = sorted(evaluation.result.matches, key=lambda match: match.record.observed_at)
        raw_windows = [
            {
                "start": event.record.observed_at - timedelta(seconds=request.before_s),
                "end": event.record.observed_at + timedelta(seconds=request.after_s),
                "event_record_ids": [str(event.record.id)],
            }
            for event in events
        ]
        merged: list[dict[str, Any]] = []
        for window in raw_windows:
            touches = bool(merged) and (
                window["start"] <= merged[-1]["end"]
                if request.boundary_policy == "inclusive"
                else window["start"] < merged[-1]["end"]
            )
            if touches:
                merged[-1]["end"] = max(merged[-1]["end"], window["end"])
                merged[-1]["event_record_ids"].extend(window["event_record_ids"])
            else:
                merged.append(dict(window))
        windows = [
            {
                "start_at": _iso(window["start"]),
                "end_at": _iso(window["end"]),
                "start_inclusive": request.boundary_policy == "inclusive",
                "end_inclusive": request.boundary_policy == "inclusive",
                "event_record_ids": window["event_record_ids"],
            }
            for window in merged
        ]
        definition = self.create_definition(
            project_id,
            analysis_kind="event_window",
            name=request.name,
            configuration={
                **request.model_dump(mode="json"),
                "event_definition_sha256": legacy_response.definition_sha256,
                "threshold_query": legacy_response.query.model_dump(mode="json"),
            },
            calculation_version="reefvision-event-window-1",
        )
        observed_at = cast(
            datetime,
            raw_windows[0]["start"] if raw_windows else legacy_response.query.observed_at,
        )
        source_ids = [str(event.record.id) for event in events]
        result = self.create_result(
            definition,
            observed_at=observed_at,
            payload={
                "schema_version": "1.1.0",
                "event_definition_id": str(legacy_response.id),
                "event_definition_sha256": legacy_response.definition_sha256,
                "event_sample_count": len(events),
                "windows": windows,
                "boundary_policy": request.boundary_policy,
                "method": "sample_threshold_windows_no_interpolation",
                "interpretation": "descriptive_context_only",
            },
            input_snapshot={
                **request.model_dump(mode="json"),
                "threshold_definition": legacy_response.model_dump(mode="json"),
            },
            source_record_ids=source_ids,
            quality_control={
                "status": "accepted" if events else "unavailable",
                "flags": [] if events else ["no_threshold_samples"],
            },
            uncertainty={
                "type": "boundary_policy",
                "statement": "Windows surround qualifying samples; duration is not interpolated",
            },
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
        )
        self.session.commit()
        return EnvironmentalAnalysisSingleResponse(
            definition=self.definition_response(definition),
            result=self.result_response(result),
        )

    @staticmethod
    def _independent_unit(record: Any) -> str:
        subject = record.subject
        if subject.image_id:
            return f"image:{subject.image_id}"
        if subject.video_id:
            frame = f":frame:{subject.frame_index}" if subject.frame_index is not None else ""
            return f"video:{subject.video_id}{frame}"
        return f"record:{record.id}"

    def _bounded_pairs(
        self,
        project_id: str,
        request: ObservationEnvironmentJoinRequest,
        *,
        lag_s: int = 0,
    ) -> tuple[list[dict[str, Any]], list[str], datetime]:
        observations = []
        for identifier in request.observation_record_ids:
            row = self.session.get(ScientificRecord, str(identifier))
            if row is None or row.project_id != project_id:
                raise ValidationError("Observation scientific records must belong to this project")
            record = self.science.response(row)
            if record.location is None:
                raise ValidationError("Observation records require an explicit EPSG:4326 location")
            if record.qc in ("suspect", "rejected"):
                raise ValidationError(
                    "Observation records with suspect or rejected QC cannot be joined"
                )
            if request.require_depth_match and (
                record.depth_m is None or record.depth_reference is None
            ):
                raise ValidationError("Depth-matched joins require observation depth and reference")
            observations.append(record)
        pairs = []
        sources = [str(record.id) for record in observations]
        for observation in observations:
            observation_location = observation.location
            if observation_location is None:
                raise ValidationError("Observation location became unavailable during matching")
            target_at = observation.observed_at + timedelta(seconds=lag_s)
            window = timedelta(seconds=request.max_time_delta_s)
            candidate_rows = self.session.scalars(
                select(ScientificRecord).where(
                    ScientificRecord.project_id == project_id,
                    ScientificRecord.variable == request.environmental_variable,
                    ScientificRecord.observed_at >= target_at - window,
                    ScientificRecord.observed_at <= target_at + window,
                )
            ).all()
            candidates = []
            for row in candidate_rows:
                if row.id == str(observation.id):
                    continue
                environmental = self.science.response(row)
                if (
                    environmental.location is None
                    or environmental.qc in ("suspect", "rejected")
                    or environmental.environmental_snapshot_current is False
                ):
                    continue
                distance = geographic_distance_m(
                    observation_location.latitude,
                    observation_location.longitude,
                    environmental.location.latitude,
                    environmental.location.longitude,
                )
                if distance > request.max_distance_m:
                    continue
                depth_delta = None
                if request.require_depth_match:
                    observation_depth = observation.depth_m
                    if (
                        observation_depth is None
                        or environmental.depth_m is None
                        or environmental.depth_reference != observation.depth_reference
                    ):
                        continue
                    depth_delta = round(environmental.depth_m - observation_depth, 9)
                    if abs(depth_delta) > request.max_depth_delta_m:
                        continue
                time_delta = (environmental.observed_at - target_at).total_seconds()
                candidates.append((environmental, time_delta, distance, depth_delta))
            candidates.sort(
                key=lambda item: (
                    abs(item[1]),
                    item[2],
                    abs(item[3]) if item[3] is not None else 0,
                    str(item[0].id),
                )
            )
            if not candidates:
                raise ValidationError(
                    f"No bounded environmental match for observation record {observation.id}"
                )
            environmental, time_delta, distance, depth_delta = candidates[0]
            sources.append(str(environmental.id))
            pairs.append(
                {
                    "observation_record_id": str(observation.id),
                    "observation_variable": observation.variable,
                    "observation_value": observation.normalized_value,
                    "observation_unit": observation.normalized_unit,
                    "observation_at": _iso(observation.observed_at),
                    "independent_unit_id": self._independent_unit(observation),
                    "environmental_record_id": str(environmental.id),
                    "environmental_variable": environmental.variable,
                    "environmental_value": environmental.normalized_value,
                    "environmental_unit": environmental.normalized_unit,
                    "environmental_at": _iso(environmental.observed_at),
                    "lag_s": lag_s,
                    "target_at": _iso(target_at),
                    "time_delta_s": time_delta,
                    "distance_m": distance,
                    "depth_delta_m": depth_delta,
                    "selection_rule": "minimum_absolute_time_then_distance_depth_and_id",
                }
            )
        return (
            pairs,
            list(dict.fromkeys(sources)),
            min(record.observed_at for record in observations),
        )

    def create_observation_environment_join(
        self,
        project_id: str,
        request: ObservationEnvironmentJoinRequest,
        *,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> EnvironmentalAnalysisSingleResponse:
        self.science.require_project(project_id)
        pairs, source_ids, observed_at = self._bounded_pairs(project_id, request)
        definition = self.create_definition(
            project_id,
            analysis_kind="observation_environment_join",
            name=request.name,
            configuration=request.model_dump(mode="json"),
            calculation_version="reefvision-bounded-environment-join-1",
        )
        environmental_counts = Counter(pair["environmental_record_id"] for pair in pairs)
        result = self.create_result(
            definition,
            observed_at=observed_at,
            payload={
                "schema_version": "1.1.0",
                "pairs": pairs,
                "matching_policy": {
                    "observation_time_source": "scientific_record.observed_at",
                    "max_time_delta_s": request.max_time_delta_s,
                    "max_distance_m": request.max_distance_m,
                    "require_depth_match": request.require_depth_match,
                    "max_depth_delta_m": request.max_depth_delta_m,
                },
                "reuse_diagnostics": {
                    "environmental_record_reuse_counts": dict(environmental_counts),
                    "pseudoreplication_warning": any(
                        count > 1 for count in environmental_counts.values()
                    ),
                },
                "interpretation": "descriptive_context_only",
                "inferential_statistics": None,
            },
            input_snapshot=request.model_dump(mode="json"),
            source_record_ids=source_ids,
            quality_control={"status": "accepted", "flags": []},
            uncertainty={
                "type": "matching_tolerance",
                "statement": "Each pair reports its actual time, distance and depth offsets",
            },
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
        )
        self.session.commit()
        return EnvironmentalAnalysisSingleResponse(
            definition=self.definition_response(definition),
            result=self.result_response(result),
        )

    def create_lagged_comparison(
        self,
        project_id: str,
        request: LaggedComparisonAnalysisRequest,
        *,
        workflow_run_id: str | None = None,
        workflow_node_run_id: str | None = None,
    ) -> EnvironmentalAnalysisSingleResponse:
        source_result = self.get_result(project_id, str(request.join_result_id))
        if source_result.analysis_kind != "observation_environment_join":
            raise ValidationError("Lagged comparisons require an observation-environment join")
        join_request = ObservationEnvironmentJoinRequest.model_validate(
            source_result.input_snapshot_json
        )
        all_pairs: list[dict[str, Any]] = []
        source_ids: list[str] = []
        observed_times = []
        for lag_s in request.lags_s:
            pairs, sources, observed_at = self._bounded_pairs(project_id, join_request, lag_s=lag_s)
            all_pairs.extend(pairs)
            source_ids.extend(sources)
            observed_times.append(observed_at)
        environmental_counts = Counter(pair["environmental_record_id"] for pair in all_pairs)
        unit_counts = Counter(pair["independent_unit_id"] for pair in all_pairs)
        warning = any(count > 1 for count in environmental_counts.values()) or any(
            count > 1 for count in unit_counts.values()
        )
        definition = self.create_definition(
            project_id,
            analysis_kind="lagged_comparison",
            name=request.name,
            configuration=request.model_dump(mode="json"),
            calculation_version="reefvision-lagged-descriptive-comparison-1",
        )
        result = self.create_result(
            definition,
            observed_at=min(observed_times),
            payload={
                "schema_version": "1.1.0",
                "join_result_id": str(source_result.id),
                "lags_s": request.lags_s,
                "pairs": all_pairs,
                "reuse_diagnostics": {
                    "environmental_record_reuse_counts": dict(environmental_counts),
                    "independent_unit_reuse_counts": dict(unit_counts),
                    "pseudoreplication_warning": warning,
                },
                "interpretation": "descriptive_context_only",
                "inferential_statistics": None,
                "methodological_notes": [
                    "Repeated samples and biological units are counted explicitly.",
                    "No independence, significance, effect, or causal claim is calculated.",
                ],
            },
            input_snapshot={
                **request.model_dump(mode="json"),
                "join_result_sha256": source_result.content_sha256,
                "join_configuration": join_request.model_dump(mode="json"),
            },
            source_record_ids=list(dict.fromkeys(source_ids)),
            source_analysis_result_ids=[source_result.id],
            quality_control={
                "status": "accepted",
                "flags": ["repeated_units_present"] if warning else [],
            },
            uncertainty={
                "type": "matching_tolerance",
                "statement": "Lagged pairs retain actual matching offsets and reuse counts",
            },
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
        )
        self.session.commit()
        return EnvironmentalAnalysisSingleResponse(
            definition=self.definition_response(definition),
            result=self.result_response(result),
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

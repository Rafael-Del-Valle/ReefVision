"""Anatomical measurement and biological event REST API."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.pose_biological_measurement import (
    BiologicalEventResponse,
    EventCorrectionRequest,
    EventDetectionCreateRequest,
    EventDetectionRunResponse,
    ManualEventCreateRequest,
    MeasurementRunResponse,
    MeasurementSampleResponse,
    MeasurementSeriesResponse,
    PoseMeasurementRunCreateRequest,
)
from reefvision.services.pose_biological_measurement import PoseBiologicalMeasurementService

router = APIRouter(tags=["pose-biological-measurement"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/pose-measurement-runs",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_measurement_run(
    project_id: str, payload: PoseMeasurementRunCreateRequest, session: DbSession
) -> JobResponse:
    return PoseBiologicalMeasurementService(session).submit_measurements(project_id, payload)


@router.get(
    "/projects/{project_id}/pose-measurement-runs", response_model=list[MeasurementRunResponse]
)
def list_measurement_runs(project_id: str, session: DbSession) -> list[MeasurementRunResponse]:
    return [
        MeasurementRunResponse.model_validate(r)
        for r in PoseBiologicalMeasurementService(session).measurement_runs(project_id)
    ]


@router.get("/pose-measurement-runs/{run_id}", response_model=MeasurementRunResponse)
def get_measurement_run(run_id: str, session: DbSession) -> MeasurementRunResponse:
    return MeasurementRunResponse.model_validate(
        PoseBiologicalMeasurementService(session)._measurement_run(run_id)
    )


@router.get(
    "/pose-measurement-runs/{run_id}/series", response_model=list[MeasurementSeriesResponse]
)
def list_series(run_id: str, session: DbSession) -> list[MeasurementSeriesResponse]:
    return [
        MeasurementSeriesResponse.model_validate(s)
        for s in PoseBiologicalMeasurementService(session).series(run_id)
    ]


@router.get(
    "/pose-measurement-series/{series_id}/samples", response_model=list[MeasurementSampleResponse]
)
def list_samples(series_id: str, session: DbSession) -> list[MeasurementSampleResponse]:
    return [
        MeasurementSampleResponse.model_validate(s)
        for s in PoseBiologicalMeasurementService(session).samples(series_id)
    ]


@router.post(
    "/projects/{project_id}/pose-event-runs",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_event_run(
    project_id: str, payload: EventDetectionCreateRequest, session: DbSession
) -> JobResponse:
    return PoseBiologicalMeasurementService(session).submit_events(project_id, payload)


@router.get("/pose-event-runs/{run_id}", response_model=EventDetectionRunResponse)
def get_event_run(run_id: str, session: DbSession) -> EventDetectionRunResponse:
    return EventDetectionRunResponse.model_validate(
        PoseBiologicalMeasurementService(session)._event_run(run_id)
    )


@router.get(
    "/projects/{project_id}/pose-event-runs",
    response_model=list[EventDetectionRunResponse],
)
def list_event_runs(project_id: str, session: DbSession) -> list[EventDetectionRunResponse]:
    return [
        EventDetectionRunResponse.model_validate(run)
        for run in PoseBiologicalMeasurementService(session).event_runs(project_id)
    ]


@router.get("/pose-event-runs/{run_id}/events", response_model=list[BiologicalEventResponse])
def list_events(
    run_id: str, session: DbSession, include_history: Annotated[bool, Query()] = False
) -> list[BiologicalEventResponse]:
    return [
        BiologicalEventResponse.model_validate(e)
        for e in PoseBiologicalMeasurementService(session).events(run_id, include_history)
    ]


@router.post(
    "/pose-biological-events/{event_id}/corrections",
    response_model=BiologicalEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def correct_event(
    event_id: str, payload: EventCorrectionRequest, session: DbSession
) -> BiologicalEventResponse:
    return BiologicalEventResponse.model_validate(
        PoseBiologicalMeasurementService(session).correct_event(event_id, payload)
    )


@router.post(
    "/pose-event-runs/{run_id}/events",
    response_model=BiologicalEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_manual_event(
    run_id: str, payload: ManualEventCreateRequest, session: DbSession
) -> BiologicalEventResponse:
    return BiologicalEventResponse.model_validate(
        PoseBiologicalMeasurementService(session).add_manual_event(run_id, payload)
    )


@router.get("/pose-event-runs/{run_id}/export")
def export_events(
    run_id: str,
    session: DbSession,
    reviewed_only: Annotated[bool, Query()] = True,
    format: Literal["json", "csv"] = "json",
) -> Response:
    service = PoseBiologicalMeasurementService(session)
    if format == "csv":
        return Response(
            service.export_csv(run_id, reviewed_only=reviewed_only),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="reefpose-events-{run_id}.csv"'},
        )
    return JSONResponse(service.export_json(run_id, reviewed_only=reviewed_only))

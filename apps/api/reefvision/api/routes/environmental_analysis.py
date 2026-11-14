"""Immutable composite environmental analysis API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.current_field import CurrentFieldAnalysisRequest
from reefvision.schemas.environmental_analysis import (
    EnvironmentalAnalysisDefinitionPage,
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
from reefvision.services.environmental_analysis import EnvironmentalAnalysisService

router = APIRouter(tags=["environmental-analysis"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/environment/analyses/current-streamline",
    response_model=EnvironmentalAnalysisSingleResponse,
    status_code=201,
)
def create_current_streamline_analysis(
    project_id: UUID, payload: CurrentFieldAnalysisRequest, session: DbSession
) -> EnvironmentalAnalysisSingleResponse:
    return EnvironmentalAnalysisService(session).create_current_streamline(str(project_id), payload)


@router.post(
    "/projects/{project_id}/environment/analyses/lunar-context",
    response_model=LunarAnalysisBatchResponse,
    status_code=201,
)
def create_lunar_analysis(
    project_id: UUID, payload: LunarAnalysisBatchRequest, session: DbSession
) -> LunarAnalysisBatchResponse:
    return EnvironmentalAnalysisService(session).create_lunar_batch(str(project_id), payload)


@router.post(
    "/projects/{project_id}/environment/analyses/tidal-context",
    response_model=EnvironmentalAnalysisSingleResponse,
    status_code=201,
)
def create_tidal_context_analysis(
    project_id: UUID, payload: TidalContextAnalysisRequest, session: DbSession
) -> EnvironmentalAnalysisSingleResponse:
    return EnvironmentalAnalysisService(session).create_tidal_context(str(project_id), payload)


@router.post(
    "/projects/{project_id}/environment/analyses/event-window",
    response_model=EnvironmentalAnalysisSingleResponse,
    status_code=201,
)
def create_event_window_analysis(
    project_id: UUID, payload: EventWindowAnalysisRequest, session: DbSession
) -> EnvironmentalAnalysisSingleResponse:
    return EnvironmentalAnalysisService(session).create_event_window(str(project_id), payload)


@router.post(
    "/projects/{project_id}/environment/analyses/observation-environment-join",
    response_model=EnvironmentalAnalysisSingleResponse,
    status_code=201,
)
def create_observation_environment_join(
    project_id: UUID, payload: ObservationEnvironmentJoinRequest, session: DbSession
) -> EnvironmentalAnalysisSingleResponse:
    return EnvironmentalAnalysisService(session).create_observation_environment_join(
        str(project_id), payload
    )


@router.post(
    "/projects/{project_id}/environment/analyses/lagged-comparison",
    response_model=EnvironmentalAnalysisSingleResponse,
    status_code=201,
)
def create_lagged_comparison(
    project_id: UUID, payload: LaggedComparisonAnalysisRequest, session: DbSession
) -> EnvironmentalAnalysisSingleResponse:
    return EnvironmentalAnalysisService(session).create_lagged_comparison(str(project_id), payload)


@router.get(
    "/projects/{project_id}/environment/analyses/definitions",
    response_model=EnvironmentalAnalysisDefinitionPage,
)
def list_analysis_definitions(
    project_id: UUID,
    session: DbSession,
    analysis_kind: EnvironmentalAnalysisKind | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EnvironmentalAnalysisDefinitionPage:
    return EnvironmentalAnalysisService(session).list_definitions(
        str(project_id), analysis_kind=analysis_kind, limit=limit, offset=offset
    )


@router.get(
    "/projects/{project_id}/environment/analyses/results",
    response_model=EnvironmentalAnalysisResultPage,
)
def list_analysis_results(
    project_id: UUID,
    session: DbSession,
    analysis_kind: EnvironmentalAnalysisKind | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EnvironmentalAnalysisResultPage:
    return EnvironmentalAnalysisService(session).list_results(
        str(project_id), analysis_kind=analysis_kind, limit=limit, offset=offset
    )


@router.get("/projects/{project_id}/environment/analyses/results/{result_id}.csv")
def export_analysis_result_csv(project_id: UUID, result_id: UUID, session: DbSession) -> Response:
    body = EnvironmentalAnalysisService(session).result_csv(str(project_id), str(result_id))
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="environmental-analysis-{result_id}.csv"'
        },
    )


@router.get(
    "/projects/{project_id}/environment/analyses/results/{result_id}/validation",
    response_model=EnvironmentalAnalysisValidationResponse,
)
def validate_analysis_result(
    project_id: UUID, result_id: UUID, session: DbSession
) -> EnvironmentalAnalysisValidationResponse:
    return EnvironmentalAnalysisService(session).validate_result(str(project_id), str(result_id))


@router.get(
    "/projects/{project_id}/environment/analyses/results/{result_id}",
    response_model=EnvironmentalAnalysisResultResponse,
)
def get_analysis_result(
    project_id: UUID, result_id: UUID, session: DbSession
) -> EnvironmentalAnalysisResultResponse:
    service = EnvironmentalAnalysisService(session)
    return service.result_response(service.get_result(str(project_id), str(result_id)))

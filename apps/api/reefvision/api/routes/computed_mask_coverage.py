"""Standalone API for immutable verified-mask area and coverage metrics."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.computed_mask_coverage import (
    ComputedMaskCoverageDefinitionCreate,
    ComputedMaskCoverageDefinitionPage,
    ComputedMaskCoverageDefinitionResponse,
    ComputedMaskCoveragePreview,
    ComputedMaskCoverageResultPage,
    ComputedMaskCoverageResultResponse,
    ComputedMaskCoverageSelection,
    ComputedMaskCoverageValidationResponse,
)
from reefvision.services.computed_mask_coverage import ComputedMaskCoverageService

router = APIRouter(tags=["computed-mask-coverage"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ComputedMaskCoverageService:
    settings: Settings = request.app.state.settings
    return ComputedMaskCoverageService(session, settings)


@router.post(
    "/projects/{project_id}/computed-mask-coverage-definitions",
    response_model=ComputedMaskCoverageDefinitionResponse,
    status_code=201,
)
def create_definition(
    project_id: UUID,
    payload: ComputedMaskCoverageDefinitionCreate,
    request: Request,
    session: DbSession,
) -> ComputedMaskCoverageDefinitionResponse:
    coverage = service(request, session)
    row = coverage.create_definition(str(project_id), payload)
    response = coverage.definition_response(row)
    session.commit()
    return response


@router.get(
    "/projects/{project_id}/computed-mask-coverage-definitions",
    response_model=ComputedMaskCoverageDefinitionPage,
)
def list_definitions(
    project_id: UUID,
    request: Request,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ComputedMaskCoverageDefinitionPage:
    return service(request, session).list_definitions(str(project_id), limit=limit, offset=offset)


@router.post(
    "/projects/{project_id}/computed-mask-coverage-definitions/{definition_id}/preview",
    response_model=ComputedMaskCoveragePreview,
)
def preview(
    project_id: UUID,
    definition_id: UUID,
    payload: ComputedMaskCoverageSelection,
    request: Request,
    session: DbSession,
) -> ComputedMaskCoveragePreview:
    return service(request, session).preview(
        str(project_id), str(definition_id), [str(value) for value in payload.image_ids]
    )


@router.post(
    "/projects/{project_id}/computed-mask-coverage-definitions/{definition_id}/calculate",
    response_model=ComputedMaskCoverageResultResponse,
    status_code=201,
)
def calculate(
    project_id: UUID,
    definition_id: UUID,
    payload: ComputedMaskCoverageSelection,
    request: Request,
    session: DbSession,
) -> ComputedMaskCoverageResultResponse:
    coverage = service(request, session)
    row = coverage.calculate(
        str(project_id), str(definition_id), [str(value) for value in payload.image_ids]
    )
    response = coverage.result_response(row)
    session.commit()
    return response


@router.get(
    "/projects/{project_id}/computed-mask-coverage-results",
    response_model=ComputedMaskCoverageResultPage,
)
def list_results(
    project_id: UUID,
    request: Request,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ComputedMaskCoverageResultPage:
    return service(request, session).list_results(str(project_id), limit=limit, offset=offset)


@router.get(
    "/projects/{project_id}/computed-mask-coverage-results/{result_id}/validation",
    response_model=ComputedMaskCoverageValidationResponse,
)
def validate_result(
    project_id: UUID,
    result_id: UUID,
    request: Request,
    session: DbSession,
) -> ComputedMaskCoverageValidationResponse:
    return service(request, session).validate_result(str(project_id), str(result_id))


@router.get("/projects/{project_id}/computed-mask-coverage-results.csv")
def export_results(project_id: UUID, request: Request, session: DbSession) -> Response:
    return Response(
        content=service(request, session).export_csv(str(project_id)),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="computed-mask-coverage.csv"'},
    )

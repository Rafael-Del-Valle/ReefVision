"""Typed annotation-source comparison preview API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.annotation_comparison import (
    AnnotationComparisonCalculateRequest,
    AnnotationComparisonPreviewRequest,
    AnnotationComparisonPreviewResponse,
    AnnotationComparisonSavedResponse,
    AnnotationComparisonValidationResponse,
)
from reefvision.services.annotation_comparison import AnnotationComparisonService

router = APIRouter(tags=["annotation-comparison"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/annotation-comparisons/preview",
    response_model=AnnotationComparisonPreviewResponse,
)
def preview_annotation_comparison(
    project_id: UUID,
    request: AnnotationComparisonPreviewRequest,
    http_request: Request,
    session: DbSession,
) -> AnnotationComparisonPreviewResponse:
    return AnnotationComparisonService(session, http_request.app.state.settings).preview(
        str(project_id), request
    )


@router.post(
    "/projects/{project_id}/annotation-comparisons/calculate",
    response_model=AnnotationComparisonSavedResponse,
    status_code=201,
)
def calculate_annotation_comparison(
    project_id: UUID,
    request: AnnotationComparisonCalculateRequest,
    http_request: Request,
    session: DbSession,
) -> AnnotationComparisonSavedResponse:
    return AnnotationComparisonService(session, http_request.app.state.settings).calculate(
        str(project_id), request
    )


@router.get(
    "/projects/{project_id}/annotation-comparisons/{result_id}",
    response_model=AnnotationComparisonSavedResponse,
)
def get_annotation_comparison(
    project_id: UUID,
    result_id: UUID,
    request: Request,
    session: DbSession,
) -> AnnotationComparisonSavedResponse:
    return AnnotationComparisonService(session, request.app.state.settings).get_result(
        str(project_id), str(result_id)
    )


@router.get(
    "/projects/{project_id}/annotation-comparisons/{result_id}/validation",
    response_model=AnnotationComparisonValidationResponse,
)
def validate_annotation_comparison(
    project_id: UUID,
    result_id: UUID,
    request: Request,
    session: DbSession,
) -> AnnotationComparisonValidationResponse:
    return AnnotationComparisonService(session, request.app.state.settings).validate_result(
        str(project_id), str(result_id)
    )


@router.get("/projects/{project_id}/annotation-comparisons/{result_id}/export.csv")
def export_annotation_comparison_csv(
    project_id: UUID,
    result_id: UUID,
    request: Request,
    session: DbSession,
) -> Response:
    payload = AnnotationComparisonService(session, request.app.state.settings).result_csv(
        str(project_id), str(result_id)
    )
    return Response(
        payload,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="annotation-comparison-{result_id}.csv"'
        },
    )

"""Typed annotation-source comparison preview API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.annotation_comparison import (
    AnnotationComparisonCalculateRequest,
    AnnotationComparisonPreviewRequest,
    AnnotationComparisonPreviewResponse,
    AnnotationComparisonSavedResponse,
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
    session: DbSession,
) -> AnnotationComparisonPreviewResponse:
    return AnnotationComparisonService(session).preview(str(project_id), request)


@router.post(
    "/projects/{project_id}/annotation-comparisons/calculate",
    response_model=AnnotationComparisonSavedResponse,
    status_code=201,
)
def calculate_annotation_comparison(
    project_id: UUID,
    request: AnnotationComparisonCalculateRequest,
    session: DbSession,
) -> AnnotationComparisonSavedResponse:
    return AnnotationComparisonService(session).calculate(str(project_id), request)

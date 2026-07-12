"""Annotation editor endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.annotations import (
    AnnotationBatchSaveRequest,
    AnnotationBatchSaveResponse,
    AnnotationSessionResponse,
)
from reefvision.services.annotations import AnnotationService

router = APIRouter(tags=["annotations"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> AnnotationService:
    settings: Settings = request.app.state.settings
    return AnnotationService(session, settings)


@router.get("/images/{image_id}/annotations", response_model=AnnotationSessionResponse)
def get_annotation_session(
    image_id: str, request: Request, session: DbSession
) -> AnnotationSessionResponse:
    return service(request, session).get_annotation_session(image_id)


@router.put("/images/{image_id}/annotations", response_model=AnnotationBatchSaveResponse)
def save_annotations(
    image_id: str,
    payload: AnnotationBatchSaveRequest,
    request: Request,
    session: DbSession,
) -> AnnotationBatchSaveResponse:
    return service(request, session).save_annotations(image_id, payload)

"""Classification crop QA and augmentation validation endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.classification_qa import (
    ClassificationAugmentationValidationRequest,
    ClassificationAugmentationValidationResponse,
    ClassificationCropQARequest,
    ClassificationCropQAResponse,
)
from reefvision.services.classification_qa import ClassificationQAService

router = APIRouter(tags=["classification-qa"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ClassificationQAService:
    settings: Settings = request.app.state.settings
    return ClassificationQAService(session, settings)


@router.post(
    "/projects/{project_id}/classification-crops/qa",
    response_model=ClassificationCropQAResponse,
)
def run_classification_crop_qa(
    project_id: str,
    payload: ClassificationCropQARequest,
    request: Request,
    session: DbSession,
) -> ClassificationCropQAResponse:
    return service(request, session).run_crop_qa(project_id, payload)


@router.post(
    "/projects/{project_id}/classification-augmentation/validate",
    response_model=ClassificationAugmentationValidationResponse,
)
def validate_classification_augmentation(
    project_id: str,
    payload: ClassificationAugmentationValidationRequest,
    request: Request,
    session: DbSession,
) -> ClassificationAugmentationValidationResponse:
    return service(request, session).validate_augmentation(project_id, payload)

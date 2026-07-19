"""Frozen scientific measurement acceptance endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.scientific_validation import (
    ScientificValidationRequest,
    ScientificValidationResponse,
)
from reefvision.services.scientific_validation import ScientificValidationService

router = APIRouter(tags=["scientific-validation"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/scientific-validation",
    response_model=ScientificValidationResponse,
)
def run_scientific_validation(
    project_id: str,
    payload: ScientificValidationRequest,
    request: Request,
    session: DbSession,
) -> ScientificValidationResponse:
    return ScientificValidationService(
        session,
        request.app.state.settings,
    ).run(project_id, payload)

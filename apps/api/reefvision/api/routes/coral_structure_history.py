"""Persisted coral structure analysis history endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.skeletonization import SkeletonAnalysisRevisionResponse
from reefvision.services.skeletonization import SkeletonizationService

router = APIRouter(tags=["coral_structure"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> SkeletonizationService:
    settings: Settings = request.app.state.settings
    return SkeletonizationService(session, settings)


@router.get(
    "/structure-analyses/{analysis_id}",
    response_model=SkeletonAnalysisRevisionResponse,
)
def get_structure_analysis_revision(
    analysis_id: str,
    request: Request,
    session: DbSession,
) -> SkeletonAnalysisRevisionResponse:
    return service(request, session).get_persisted_analysis(analysis_id)

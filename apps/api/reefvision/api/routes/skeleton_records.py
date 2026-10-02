"""Persisted skeleton analysis endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.skeletonization import (
    SkeletonAnalysisCreateRequest,
    SkeletonAnalysisRevisionResponse,
)
from reefvision.services.skeletonization import SkeletonizationService

router = APIRouter(tags=["skeletonization"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> SkeletonizationService:
    settings: Settings = request.app.state.settings
    return SkeletonizationService(session, settings)


@router.get(
    "/skeleton-analyses/{analysis_id}",
    response_model=SkeletonAnalysisRevisionResponse,
)
def get_skeleton_analysis(
    analysis_id: str,
    request: Request,
    session: DbSession,
) -> SkeletonAnalysisRevisionResponse:
    return service(request, session).get_persisted_analysis(analysis_id)



@router.post(
    "/mask-annotations/{mask_annotation_id}/skeleton-analyses",
    response_model=SkeletonAnalysisRevisionResponse,
)
def create_skeleton_analysis(
    mask_annotation_id: str,
    payload: SkeletonAnalysisCreateRequest,
    request: Request,
    session: DbSession,
) -> SkeletonAnalysisRevisionResponse:
    return service(request, session).persist_analysis(
        mask_annotation_id,
        payload,
    )

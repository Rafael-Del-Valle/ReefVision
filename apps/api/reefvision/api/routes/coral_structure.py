"""Coral structure-analysis readiness endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.skeletonization import SkeletonizationReadinessResponse
from reefvision.services.skeletonization import SkeletonizationService

router = APIRouter(tags=["coral_structure"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> SkeletonizationService:
    settings: Settings = request.app.state.settings
    return SkeletonizationService(session, settings)


@router.get(
    "/mask-annotations/{mask_annotation_id}/structure-readiness",
    response_model=SkeletonizationReadinessResponse,
)
def get_structure_readiness(
    mask_annotation_id: str,
    request: Request,
    session: DbSession,
) -> SkeletonizationReadinessResponse:
    return service(request, session).readiness(mask_annotation_id)

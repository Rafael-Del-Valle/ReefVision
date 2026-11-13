"""Independent scientific validation API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.reefpose_validation import (
    FreezeReferenceRequest,
    ReferenceDetail,
    ReferenceSummary,
)
from reefvision.services.reefpose_validation import ReferenceService

router = APIRouter(tags=["reefpose-validation"], prefix="/projects/{project_id}")
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("/reefpose-references", response_model=ReferenceDetail, status_code=201)
def freeze_reference(
    project_id: str, payload: FreezeReferenceRequest, session: DbSession
) -> ReferenceDetail:
    return ReferenceDetail.model_validate(ReferenceService(session).freeze(project_id, payload))


@router.get("/reefpose-references", response_model=list[ReferenceSummary])
def list_references(
    project_id: str,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReferenceSummary]:
    return [
        ReferenceSummary.model_validate(row)
        for row in ReferenceService(session).list(project_id, limit, offset)
    ]


@router.get("/reefpose-references/{reference_id}", response_model=ReferenceDetail)
def get_reference(project_id: str, reference_id: str, session: DbSession) -> ReferenceDetail:
    return ReferenceDetail.model_validate(ReferenceService(session).get(project_id, reference_id))

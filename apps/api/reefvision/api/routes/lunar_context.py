"""Project-scoped offline lunar context; never infer observation time."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.lunar_context import LunarContextRequest, LunarContextResponse
from reefvision.services.lunar_context import calculate_lunar_context

router = APIRouter(tags=["lunar-context"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/environment/lunar-context",
    response_model=LunarContextResponse,
)
def lunar_context(
    project_id: UUID, payload: LunarContextRequest, session: DbSession
) -> LunarContextResponse:
    return calculate_lunar_context(session, str(project_id), payload)

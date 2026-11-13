"""Scientific-record-backed current streamline preview API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.current_field import (
    CurrentFieldStreamlineRequest,
    CurrentFieldStreamlineResponse,
)
from reefvision.services.current_field import CurrentFieldService

router = APIRouter(tags=["current-field"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/current-field/streamlines/preview",
    response_model=CurrentFieldStreamlineResponse,
)
def preview_current_streamlines(
    project_id: UUID,
    request: CurrentFieldStreamlineRequest,
    session: DbSession,
) -> CurrentFieldStreamlineResponse:
    return CurrentFieldService(session).preview(str(project_id), request)

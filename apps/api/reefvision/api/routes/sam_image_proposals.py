"""Whole-image automatic SAM proposal jobs."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.sam_image_proposals import SamImageProposalsRequest
from reefvision.services.sam_image_proposals import SamImageProposalsService

router = APIRouter(tags=["predictions"])


@router.post(
    "/projects/{project_id}/sam-image-proposals", response_model=JobResponse, status_code=202
)
def create_sam_image_proposals(
    project_id: UUID,
    payload: SamImageProposalsRequest,
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> JobResponse:
    job = SamImageProposalsService(session, request.app.state.settings).create(
        str(project_id), payload
    )
    return JobResponse.model_validate(job)

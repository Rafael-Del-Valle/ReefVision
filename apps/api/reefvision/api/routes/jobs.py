"""Background-job status and retry endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.jobs import JobResponse
from reefvision.services.jobs import JobService

router = APIRouter(tags=["jobs"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, session: DbSession) -> JobResponse:
    return JobResponse.model_validate(JobService(session).get(job_id))


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: str, session: DbSession) -> JobResponse:
    return JobResponse.model_validate(JobService(session).retry(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: str, session: DbSession) -> JobResponse:
    return JobResponse.model_validate(JobService(session).cancel(job_id))

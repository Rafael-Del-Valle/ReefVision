"""Project-scoped local schedule and occurrence history routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.workflow_schedules import (
    WorkflowScheduleCreate,
    WorkflowScheduleOccurrencePage,
    WorkflowScheduleOccurrenceRead,
    WorkflowSchedulePage,
    WorkflowScheduleRead,
    WorkflowScheduleUpdate,
)
from reefvision.services.workflow_schedules import WorkflowScheduleService

router = APIRouter(prefix="/projects/{project_id}/workflow-schedules", tags=["workflow-schedules"])
DbSession = Annotated[Session, Depends(get_db_session)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0)]


def service(request: Request, session: DbSession) -> WorkflowScheduleService:
    return WorkflowScheduleService(session, request.app.state.settings)


ScheduleService = Annotated[WorkflowScheduleService, Depends(service)]


@router.get("", response_model=WorkflowSchedulePage)
def list_schedules(
    project_id: UUID, schedules: ScheduleService, limit: PageLimit = 20, offset: PageOffset = 0
) -> WorkflowSchedulePage:
    return schedules.list(str(project_id), limit=limit, offset=offset)


@router.post("", response_model=WorkflowScheduleRead, status_code=status.HTTP_201_CREATED)
def create_schedule(
    project_id: UUID, payload: WorkflowScheduleCreate, schedules: ScheduleService
) -> WorkflowScheduleRead:
    return schedules.create(str(project_id), payload)


@router.patch("/{schedule_id}", response_model=WorkflowScheduleRead)
def update_schedule(
    project_id: UUID, schedule_id: UUID, payload: WorkflowScheduleUpdate, schedules: ScheduleService
) -> WorkflowScheduleRead:
    return schedules.edit(str(project_id), str(schedule_id), payload)


@router.get("/{schedule_id}/occurrences", response_model=WorkflowScheduleOccurrencePage)
def list_schedule_occurrences(
    project_id: UUID,
    schedule_id: UUID,
    schedules: ScheduleService,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> WorkflowScheduleOccurrencePage:
    return schedules.list_occurrences(str(project_id), str(schedule_id), limit=limit, offset=offset)


@router.post(
    "/{schedule_id}/occurrences/{occurrence_id}/cancel",
    response_model=WorkflowScheduleOccurrenceRead,
)
def cancel_schedule_occurrence(
    project_id: UUID, schedule_id: UUID, occurrence_id: UUID, schedules: ScheduleService
) -> WorkflowScheduleOccurrenceRead:
    return schedules.cancel(str(project_id), str(schedule_id), str(occurrence_id))

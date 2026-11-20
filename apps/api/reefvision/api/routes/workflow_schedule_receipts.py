from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.services.workflow_schedule_receipt import VerifiedSlotReceipt, schedule_receipt

router = APIRouter(tags=["workflow-schedules"])


@router.get("/projects/{project_id}/workflow-schedule-occurrences/{occurrence_id}/receipt")
def get_schedule_receipt(
    project_id: UUID, occurrence_id: UUID, session: Annotated[Session, Depends(get_db_session)]
) -> VerifiedSlotReceipt:
    return schedule_receipt(session, str(project_id), str(occurrence_id))

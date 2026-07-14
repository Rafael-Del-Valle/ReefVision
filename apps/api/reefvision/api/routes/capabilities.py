"""Task and provider capability endpoints."""

from fastapi import APIRouter

from reefvision.ml.task_registry import capability_payload
from reefvision.schemas.capabilities import TaskCapabilityResponse

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities/tasks", response_model=list[TaskCapabilityResponse])
def list_task_capabilities() -> list[TaskCapabilityResponse]:
    return [TaskCapabilityResponse.model_validate(item) for item in capability_payload()]

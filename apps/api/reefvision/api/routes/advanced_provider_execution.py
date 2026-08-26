"""Executable advanced provider endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.advanced_provider_execution import (
    AdvancedProviderExecutionRequest,
    AdvancedProviderExecutionResponse,
)
from reefvision.services.advanced_provider_execution import AdvancedProviderExecutionService

router = APIRouter(tags=["advanced-providers"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/advanced-providers/{provider_id}/execute",
    response_model=AdvancedProviderExecutionResponse,
)
def execute_advanced_provider(
    project_id: str,
    provider_id: str,
    payload: AdvancedProviderExecutionRequest,
    request: Request,
    session: DbSession,
) -> AdvancedProviderExecutionResponse:
    return AdvancedProviderExecutionService(session, request.app.state.settings).execute(
        project_id, provider_id, payload
    )

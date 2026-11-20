"""Project Model Hub review and explicit local runtime selection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.model_runtime import (
    RuntimeConfirmation,
    RuntimeDraft,
    RuntimePreview,
    RuntimeSelectionResponse,
)
from reefvision.services.model_runtime import ModelRuntimeService

router = APIRouter(prefix="/projects/{project_id}/model-runtime-selections", tags=["models"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get("")
def list_selections(
    project_id: UUID, request: Request, session: DbSession
) -> list[RuntimeSelectionResponse]:
    return ModelRuntimeService(session, request.app.state.settings).list(str(project_id))


@router.get("/{selection_id}")
def get_selection(
    project_id: UUID, selection_id: UUID, request: Request, session: DbSession
) -> RuntimeSelectionResponse:
    return ModelRuntimeService(session, request.app.state.settings).get(
        str(project_id), str(selection_id)
    )


@router.post("/preview")
def preview(
    project_id: UUID, draft: RuntimeDraft, request: Request, session: DbSession
) -> RuntimePreview:
    return ModelRuntimeService(session, request.app.state.settings).preview(str(project_id), draft)


@router.post("", status_code=201)
def confirm(
    project_id: UUID, payload: RuntimeConfirmation, request: Request, session: DbSession
) -> RuntimeSelectionResponse:
    return ModelRuntimeService(session, request.app.state.settings).confirm(
        str(project_id), payload
    )

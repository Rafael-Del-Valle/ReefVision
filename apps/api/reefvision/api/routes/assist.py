"""Interactive annotation-assist endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.ml.assist_runtime import AssistRuntime
from reefvision.schemas.assist import (
    AssistAcceptRequest,
    AssistAcceptResponse,
    AssistBoxRequest,
    AssistBrushRequest,
    AssistSessionCreateRequest,
    AssistSessionResponse,
)
from reefvision.services.assist import AssistService

router = APIRouter(tags=["assist"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> AssistService:
    settings: Settings = request.app.state.settings
    runtime: AssistRuntime = request.app.state.assist_runtime
    return AssistService(session, settings, runtime)


@router.post("/images/{image_id}/assist-sessions", response_model=AssistSessionResponse)
def create_assist_session(
    image_id: str,
    payload: AssistSessionCreateRequest,
    request: Request,
    session: DbSession,
) -> AssistSessionResponse:
    return service(request, session).create_session(image_id, payload)


@router.post("/assist-sessions/{session_id}/brush", response_model=AssistSessionResponse)
def brush_assist_session(
    session_id: str,
    payload: AssistBrushRequest,
    request: Request,
    session: DbSession,
) -> AssistSessionResponse:
    return service(request, session).brush(session_id, payload)


@router.post("/assist-sessions/{session_id}/box", response_model=AssistSessionResponse)
def box_assist_session(
    session_id: str,
    payload: AssistBoxRequest,
    request: Request,
    session: DbSession,
) -> AssistSessionResponse:
    return service(request, session).box(session_id, payload)


@router.post("/assist-sessions/{session_id}/reset", response_model=AssistSessionResponse)
def reset_assist_session(
    session_id: str, request: Request, session: DbSession
) -> AssistSessionResponse:
    return service(request, session).reset(session_id)


@router.post("/assist-sessions/{session_id}/accept", response_model=AssistAcceptResponse)
def accept_assist_session(
    session_id: str,
    payload: AssistAcceptRequest,
    request: Request,
    session: DbSession,
) -> AssistAcceptResponse:
    return service(request, session).accept(session_id, payload)


@router.delete("/assist-sessions/{session_id}", status_code=204)
def delete_assist_session(session_id: str, request: Request, session: DbSession) -> None:
    service(request, session).cancel(session_id)

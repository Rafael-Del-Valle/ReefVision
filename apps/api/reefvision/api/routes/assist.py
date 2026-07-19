"""Interactive annotation-assist endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.db.models import ImageAsset
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.assist_runtime import AssistRuntime
from reefvision.ml.providers import PixelBox, PixelPoint
from reefvision.schemas.assist import (
    AssistAcceptRequest,
    AssistAcceptResponse,
    AssistBoxRequest,
    AssistBrushRequest,
    AssistPointPromptRequest,
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


def _with_point_counts(
    request: Request,
    response: AssistSessionResponse,
) -> AssistSessionResponse:
    runtime: AssistRuntime = request.app.state.assist_runtime
    state = runtime._session(response.session_id)
    return response.model_copy(
        update={
            "positive_point_count": len(state.positive_points),
            "negative_point_count": len(state.negative_points),
        }
    )


@router.post("/images/{image_id}/assist-sessions", response_model=AssistSessionResponse)
def create_assist_session(
    image_id: str,
    payload: AssistSessionCreateRequest,
    request: Request,
    session: DbSession,
) -> AssistSessionResponse:
    response = service(request, session).create_session(image_id, payload)
    return _with_point_counts(request, response)


@router.post("/assist-sessions/{session_id}/brush", response_model=AssistSessionResponse)
def brush_assist_session(
    session_id: str,
    payload: AssistBrushRequest,
    request: Request,
    session: DbSession,
) -> AssistSessionResponse:
    response = service(request, session).brush(session_id, payload)
    return _with_point_counts(request, response)


@router.post("/assist-sessions/{session_id}/points", response_model=AssistSessionResponse)
def point_prompt_assist_session(
    session_id: str,
    payload: AssistPointPromptRequest,
    request: Request,
    session: DbSession,
) -> AssistSessionResponse:
    runtime: AssistRuntime = request.app.state.assist_runtime
    state = runtime._session(session_id)
    image = session.get(ImageAsset, state.image_id)
    if image is None:
        raise NotFoundError("Image not found")
    context_box = None
    if payload.context_box is not None:
        box = payload.context_box
        if box.x_max <= box.x_min or box.y_max <= box.y_min:
            raise ValidationError("Bounding boxes must have positive width and height")
        if (
            box.x_min < 0
            or box.y_min < 0
            or box.x_max > image.width_px
            or box.y_max > image.height_px
        ):
            raise ValidationError("Point prompt context boxes must remain inside the image")
        context_box = PixelBox(
            x_min=float(box.x_min),
            y_min=float(box.y_min),
            x_max=float(box.x_max),
            y_max=float(box.y_max),
        )
    updated = runtime.apply_point_prompts(
        session_id=session_id,
        positive_points=[
            PixelPoint(x=float(point.x), y=float(point.y)) for point in payload.positive_points
        ],
        negative_points=[
            PixelPoint(x=float(point.x), y=float(point.y)) for point in payload.negative_points
        ],
        context_box=context_box,
        image_width=image.width_px,
        image_height=image.height_px,
    )
    response = service(request, session)._response(updated)
    return _with_point_counts(request, response)


@router.post("/assist-sessions/{session_id}/box", response_model=AssistSessionResponse)
def box_assist_session(
    session_id: str,
    payload: AssistBoxRequest,
    request: Request,
    session: DbSession,
) -> AssistSessionResponse:
    response = service(request, session).box(session_id, payload)
    return _with_point_counts(request, response)


@router.post("/assist-sessions/{session_id}/reset", response_model=AssistSessionResponse)
def reset_assist_session(
    session_id: str,
    request: Request,
    session: DbSession,
) -> AssistSessionResponse:
    response = service(request, session).reset(session_id)
    return _with_point_counts(request, response)


@router.post("/assist-sessions/{session_id}/accept", response_model=AssistAcceptResponse)
def accept_assist_session(
    session_id: str,
    payload: AssistAcceptRequest,
    request: Request,
    session: DbSession,
) -> AssistAcceptResponse:
    return service(request, session).accept(session_id, payload)


@router.delete("/assist-sessions/{session_id}", status_code=204)
def delete_assist_session(
    session_id: str,
    request: Request,
    session: DbSession,
) -> None:
    service(request, session).cancel(session_id)

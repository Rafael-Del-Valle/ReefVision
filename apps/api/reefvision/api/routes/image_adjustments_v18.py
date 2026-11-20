"""Preview, save, reopen and export an immutable still image adjustment."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.image_adjustments_v18 import (
    ImageAdjustmentDraft,
    ImageAdjustmentPage,
    ImageAdjustmentRecord,
)
from reefvision.services.image_adjustments_v18 import ImageAdjustmentService

router = APIRouter(prefix="/images/{image_id}/adjustments", tags=["image adjustments"])
DbSession = Annotated[Session, Depends(get_db_session)]
NO_CACHE = {"Cache-Control": "no-store"}


def _service(request: Request, session: Session) -> ImageAdjustmentService:
    return ImageAdjustmentService(session, request.app.state.settings)


@router.get("")
def list_adjustments(
    image_id: UUID,
    request: Request,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> ImageAdjustmentPage:
    return _service(request, session).list(str(image_id), page, page_size)


@router.post("/preview", response_class=Response)
def preview(
    image_id: UUID, draft: ImageAdjustmentDraft, request: Request, session: DbSession
) -> Response:
    rendered = _service(request, session).preview(str(image_id), draft)
    return Response(rendered.png, media_type="image/png", headers=NO_CACHE)


@router.post("", status_code=201)
def save(
    image_id: UUID, draft: ImageAdjustmentDraft, request: Request, session: DbSession
) -> ImageAdjustmentRecord:
    return _service(request, session).save(str(image_id), draft)


@router.get("/{recipe_id}")
def get_recipe(
    image_id: UUID, recipe_id: UUID, request: Request, session: DbSession
) -> ImageAdjustmentRecord:
    return _service(request, session).get(str(image_id), str(recipe_id))


@router.get("/{recipe_id}/rendition", response_class=FileResponse)
def rendition(
    image_id: UUID, recipe_id: UUID, request: Request, session: DbSession
) -> FileResponse:
    path = _service(request, session).rendition(str(image_id), str(recipe_id))
    return FileResponse(path, media_type="image/png", headers=NO_CACHE)


@router.get("/{recipe_id}/download", response_class=FileResponse)
def download(image_id: UUID, recipe_id: UUID, request: Request, session: DbSession) -> FileResponse:
    path = _service(request, session).rendition(str(image_id), str(recipe_id))
    return FileResponse(
        path, media_type="image/png", filename=f"adjusted-{recipe_id}.png", headers=NO_CACHE
    )


@router.get("/{recipe_id}/export", response_class=Response)
def export_receipt(
    image_id: UUID, recipe_id: UUID, request: Request, session: DbSession
) -> Response:
    record = _service(request, session).get(str(image_id), str(recipe_id))
    return Response(
        record.model_dump_json(indent=2),
        media_type="application/json",
        headers={
            **NO_CACHE,
            "Content-Disposition": f'attachment; filename="adjustment-{recipe_id}.json"',
        },
    )

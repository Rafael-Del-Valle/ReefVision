"""Selected-mask refinement preview, review and undo/redo endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.mask_refinements import (
    MaskRefinementAcceptRequest,
    MaskRefinementGeometryRequest,
    MaskRefinementPreviewRequest,
    MaskRefinementResponse,
)
from reefvision.schemas.raster_edits import RasterMaskEditResponse
from reefvision.services.mask_refinements import MaskRefinementService

router = APIRouter(tags=["mask-refinements"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> MaskRefinementService:
    return MaskRefinementService(session, request.app.state.settings)


@router.post("/mask-annotations/{mask_id}/refinements", response_model=MaskRefinementResponse)
def preview(
    mask_id: UUID, payload: MaskRefinementPreviewRequest, request: Request, session: DbSession
) -> MaskRefinementResponse:
    return service(request, session).preview(str(mask_id), payload)


@router.get("/mask-refinements/{candidate_id}", response_model=MaskRefinementResponse)
def get(candidate_id: UUID, request: Request, session: DbSession) -> MaskRefinementResponse:
    return service(request, session).get(str(candidate_id))


@router.get("/mask-refinements/{candidate_id}/content", response_class=FileResponse)
def content(candidate_id: UUID, request: Request, session: DbSession) -> FileResponse:
    return FileResponse(
        service(request, session).content(str(candidate_id)),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.put("/mask-refinements/{candidate_id}/geometry", response_model=MaskRefinementResponse)
def edit(
    candidate_id: UUID, payload: MaskRefinementGeometryRequest, request: Request, session: DbSession
) -> MaskRefinementResponse:
    return service(request, session).edit(str(candidate_id), payload)


@router.post("/mask-refinements/{candidate_id}/accept", response_model=RasterMaskEditResponse)
def accept(
    candidate_id: UUID, payload: MaskRefinementAcceptRequest, request: Request, session: DbSession
) -> RasterMaskEditResponse:
    return service(request, session).accept(str(candidate_id), payload)


@router.post("/mask-refinements/{candidate_id}/discard", response_model=MaskRefinementResponse)
def discard(candidate_id: UUID, request: Request, session: DbSession) -> MaskRefinementResponse:
    return service(request, session).discard(str(candidate_id))


@router.post("/mask-refinements/{candidate_id}/undo", response_model=RasterMaskEditResponse)
def undo(
    candidate_id: UUID, payload: MaskRefinementAcceptRequest, request: Request, session: DbSession
) -> RasterMaskEditResponse:
    return service(request, session).history(str(candidate_id), payload, redo=False)


@router.post("/mask-refinements/{candidate_id}/redo", response_model=RasterMaskEditResponse)
def redo(
    candidate_id: UUID, payload: MaskRefinementAcceptRequest, request: Request, session: DbSession
) -> RasterMaskEditResponse:
    return service(request, session).history(str(candidate_id), payload, redo=True)

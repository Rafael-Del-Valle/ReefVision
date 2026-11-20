from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.multispectral import (
    AcquisitionInput,
    AcquisitionSnapshot,
    IndexInput,
    IndexSnapshot,
    SpectralPage,
    SpectralRecord,
)
from reefvision.services.multispectral import MultispectralService

router = APIRouter(prefix="/projects/{project_id}/multispectral", tags=["multispectral"])
SessionDep = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: SessionDep) -> MultispectralService:
    return MultispectralService(session, request.app.state.settings)


Research = Annotated[MultispectralService, Depends(service)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
Channel = Annotated[int, Query(ge=0, le=7)]


@router.post("/acquisitions", status_code=201)
def register(
    project_id: UUID, body: AcquisitionInput, research: Research
) -> SpectralRecord[AcquisitionSnapshot]:
    return research.save(str(project_id), body)


@router.get("/acquisitions")
def acquisitions(
    project_id: UUID, research: Research, limit: Limit = 50, offset: Offset = 0
) -> SpectralPage[AcquisitionSnapshot]:
    return research.acquisitions(str(project_id), limit, offset)


@router.get("/acquisitions/{acquisition_id}")
def acquisition(
    project_id: UUID, acquisition_id: UUID, research: Research
) -> SpectralRecord[AcquisitionSnapshot]:
    return research.acquisition(str(project_id), str(acquisition_id))


@router.get("/acquisitions/{acquisition_id}/composite", response_class=Response)
def composite(
    project_id: UUID,
    acquisition_id: UUID,
    research: Research,
    red: Channel = 1,
    green: Channel = 0,
    blue: Channel = 0,
) -> Response:
    image = research.display(str(project_id), str(acquisition_id), (red, green, blue))
    return Response(image, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/acquisitions/{acquisition_id}/indices", status_code=201)
def analyze(
    project_id: UUID, acquisition_id: UUID, body: IndexInput, research: Research
) -> SpectralRecord[IndexSnapshot]:
    return research.analyze(str(project_id), str(acquisition_id), body)


@router.get("/indices")
def indices(
    project_id: UUID, research: Research, limit: Limit = 50, offset: Offset = 0
) -> SpectralPage[IndexSnapshot]:
    return research.indices(str(project_id), limit, offset)


@router.get("/indices/{index_id}/export", response_model=SpectralRecord[IndexSnapshot])
def export(project_id: UUID, index_id: UUID, research: Research) -> JSONResponse:
    saved = research.index(str(project_id), str(index_id))
    return JSONResponse(
        saved.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="spectral-index-{index_id}.json"'},
    )


@router.get("/indices/{index_id}/raster", response_class=Response)
def raster(project_id: UUID, index_id: UUID, research: Research) -> Response:
    return Response(
        research.raster(str(project_id), str(index_id)),
        media_type="image/tiff",
        headers={"Content-Disposition": f'attachment; filename="spectral-index-{index_id}.tif"'},
    )

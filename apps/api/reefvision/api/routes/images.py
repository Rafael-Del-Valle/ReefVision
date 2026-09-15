"""Managed image import and gallery endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.images import (
    ImageImportResponse,
    ImagePageResponse,
    ImageResponse,
    ImageUpdate,
)
from reefvision.services.images import ImageService

router = APIRouter(tags=["images"])
DbSession = Annotated[Session, Depends(get_db_session)]
IMMUTABLE_MEDIA_CACHE_CONTROL = "public, max-age=31536000, immutable"


def service(request: Request, session: Session) -> ImageService:
    settings: Settings = request.app.state.settings
    return ImageService(session, settings)


@router.post("/projects/{project_id}/imports/images", response_model=ImageImportResponse)
def import_images(
    project_id: str,
    request: Request,
    session: DbSession,
    files: Annotated[list[UploadFile], File()],
    relative_paths: Annotated[list[str] | None, Form()] = None,
) -> ImageImportResponse:
    uploads = [(upload.filename, upload.file) for upload in files]
    return service(request, session).import_streams(project_id, uploads, relative_paths)


@router.get("/projects/{project_id}/images", response_model=ImagePageResponse)
def list_images(
    project_id: str,
    request: Request,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
    filename: Annotated[str | None, Query(max_length=500)] = None,
    annotation_status: Annotated[str | None, Query(max_length=30)] = None,
    group_key: Annotated[str | None, Query(max_length=300)] = None,
    sort_by: Annotated[
        Literal["newest", "oldest", "filename", "annotations"], Query()
    ] = "newest",
) -> ImagePageResponse:
    return service(request, session).list_images(
        project_id,
        page=page,
        page_size=page_size,
        filename=filename,
        annotation_status=annotation_status,
        group_key=group_key,
        sort_by=sort_by,
    )


@router.get("/images/{image_id}", response_model=ImageResponse)
def get_image(image_id: str, request: Request, session: DbSession) -> ImageResponse:
    return ImageResponse.model_validate(service(request, session).get_image(image_id))


@router.patch("/images/{image_id}", response_model=ImageResponse)
def update_image(
    image_id: str,
    payload: ImageUpdate,
    request: Request,
    session: DbSession,
) -> ImageResponse:
    return ImageResponse.model_validate(service(request, session).update_image(image_id, payload))


@router.get("/images/{image_id}/content", response_class=FileResponse)
def image_content(image_id: str, request: Request, session: DbSession) -> FileResponse:
    image_service = service(request, session)
    image = image_service.get_image_record(image_id)
    path = image_service.content_path_for_image(image)
    return FileResponse(
        path,
        media_type=image.media_type,
        filename=image.original_filename,
        content_disposition_type="inline",
        headers={"Cache-Control": IMMUTABLE_MEDIA_CACHE_CONTROL},
    )


@router.get("/images/{image_id}/display", response_class=FileResponse)
def image_display(image_id: str, request: Request, session: DbSession) -> FileResponse:
    image_service = service(request, session)
    image = image_service.get_image_record(image_id)
    path, media_type = image_service.display_path_for_image(image)
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": IMMUTABLE_MEDIA_CACHE_CONTROL},
    )


@router.get("/images/{image_id}/thumbnail", response_class=FileResponse)
def image_thumbnail(image_id: str, request: Request, session: DbSession) -> FileResponse:
    image_service = service(request, session)
    image = image_service.get_image_record(image_id)
    path = image_service.thumbnail_path_for_image(image)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": IMMUTABLE_MEDIA_CACHE_CONTROL},
    )

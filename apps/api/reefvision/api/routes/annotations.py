"""Annotation editor endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.db.models import MaskAnnotation
from reefvision.domain.errors import ValidationError
from reefvision.schemas.annotations import (
    AnnotationBatchSaveRequest,
    AnnotationBatchSaveResponse,
    AnnotationSessionResponse,
)
from reefvision.services.annotations import AnnotationService
from reefvision.storage.projects import resolve_managed_project_path

router = APIRouter(tags=["annotations"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> AnnotationService:
    settings: Settings = request.app.state.settings
    return AnnotationService(session, settings)


def _stable_validation_error(exc: ValidationError) -> ValidationError:
    """Preserve the established annotation API messages for existing clients."""

    detail = str(exc)
    aliases = {
        "Annotation boxes must have positive area": (
            "Annotation boxes must have positive width and height"
        ),
        "Annotation coordinates cannot be negative": (
            "Annotation coordinates cannot fall outside the image"
        ),
        "Annotation coordinates cannot exceed image bounds": (
            "Annotation coordinates cannot fall outside the image"
        ),
    }
    return ValidationError(aliases.get(detail, detail))


@router.get(
    "/images/{image_id}/annotations",
    response_model=AnnotationSessionResponse,
)
def get_annotation_session(
    image_id: str,
    request: Request,
    session: DbSession,
) -> AnnotationSessionResponse:
    return service(request, session).get_session(image_id)


@router.put(
    "/images/{image_id}/annotations",
    response_model=AnnotationBatchSaveResponse,
)
def save_annotations(
    image_id: str,
    payload: AnnotationBatchSaveRequest,
    request: Request,
    session: DbSession,
) -> AnnotationBatchSaveResponse:
    try:
        return service(request, session).save_annotations(image_id, payload)
    except ValidationError as exc:
        raise _stable_validation_error(exc) from exc


@router.get(
    "/mask-annotations/{mask_annotation_id}/content",
    response_class=FileResponse,
)
def mask_annotation_content(
    mask_annotation_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    annotation = session.get(MaskAnnotation, mask_annotation_id)
    if annotation is None or annotation.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mask annotation not found",
        )
    if annotation.mask_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This polygon mask has no raster content file",
        )
    settings: Settings = request.app.state.settings
    path = resolve_managed_project_path(settings, annotation.mask_path)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The mask content file is missing from managed storage",
        )
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )

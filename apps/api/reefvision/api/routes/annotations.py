"""Annotation editor endpoints."""

from collections import Counter
from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.db.models import Annotation, MaskAnnotation, Project
from reefvision.domain.errors import ValidationError
from reefvision.schemas.annotations import (
    AnnotationBatchSaveRequest,
    AnnotationBatchSaveResponse,
    AnnotationCountResponse,
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


def _validate_annotation_ownership(
    session: Session,
    image_id: str,
    payload: AnnotationBatchSaveRequest,
) -> None:
    """Reject annotation UUIDs that are already owned by another image.

    This preflight applies the same ownership rule to box edits, polygon edits,
    and explicit mask deletions. It prevents database-key failures and avoids
    silently ignoring a deletion request that targets another image.
    """

    box_ids = {draft.id for draft in payload.annotations}
    if box_ids:
        statement = select(Annotation.id, Annotation.image_id).where(Annotation.id.in_(box_ids))
        for _annotation_id, owner_image_id in session.execute(statement):
            if owner_image_id != image_id:
                raise ValidationError("Annotations may only be saved back to their source image")

    mask_ids = {draft.id for draft in payload.mask_annotations}
    mask_ids.update(payload.deleted_mask_annotation_ids)
    if mask_ids:
        statement = select(MaskAnnotation.id, MaskAnnotation.image_id).where(
            MaskAnnotation.id.in_(mask_ids)
        )
        for _mask_id, owner_image_id in session.execute(statement):
            if owner_image_id != image_id:
                raise ValidationError("Mask annotations may only be saved to their source image")


def _ordered_counts(
    label_classes: Iterable[Any],
    annotations: Iterable[Any],
) -> list[AnnotationCountResponse]:
    counts = Counter(
        annotation.label_class_id
        for annotation in annotations
        if annotation.label_class_id is not None
    )
    ordered_classes = sorted(
        label_classes,
        key=lambda item: (item.display_order, item.class_index, item.name.casefold()),
    )
    return [
        AnnotationCountResponse(
            label_class_id=label_class.id,
            count=counts.get(label_class.id, 0),
        )
        for label_class in ordered_classes
    ]


def _normalize_session_counts(
    response: AnnotationSessionResponse,
) -> AnnotationSessionResponse:
    response.counts_by_class = _ordered_counts(
        response.label_classes,
        response.annotations,
    )
    response.mask_counts_by_class = _ordered_counts(
        response.label_classes,
        response.mask_annotations,
    )
    return response


def _normalize_save_counts(
    response: AnnotationBatchSaveResponse,
    session: Session,
) -> AnnotationBatchSaveResponse:
    project = session.get(Project, response.image.project_id)
    if project is None:
        return response
    response.counts_by_class = _ordered_counts(
        project.label_classes,
        response.annotations,
    )
    response.mask_counts_by_class = _ordered_counts(
        project.label_classes,
        response.mask_annotations,
    )
    return response


@router.get(
    "/images/{image_id}/annotation-session",
    response_model=AnnotationSessionResponse,
    deprecated=True,
)
@router.get(
    "/images/{image_id}/annotations",
    response_model=AnnotationSessionResponse,
)
def get_annotation_session(
    image_id: str,
    request: Request,
    session: DbSession,
) -> AnnotationSessionResponse:
    return _normalize_session_counts(service(request, session).get_session(image_id))


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
        _validate_annotation_ownership(session, image_id, payload)
        response = service(request, session).save_annotations(image_id, payload)
    except ValidationError as exc:
        raise _stable_validation_error(exc) from exc
    return _normalize_save_counts(response, session)


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

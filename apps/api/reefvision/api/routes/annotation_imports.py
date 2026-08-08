"""Annotation interoperability import endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.annotation_imports import AnnotationImportResponse
from reefvision.services.annotation_imports import AnnotationImportService

router = APIRouter(tags=["annotation-imports"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> AnnotationImportService:
    settings: Settings = request.app.state.settings
    return AnnotationImportService(session, settings)


@router.post(
    "/projects/{project_id}/imports/annotations",
    response_model=AnnotationImportResponse,
)
def import_annotations(
    project_id: str,
    request: Request,
    session: DbSession,
    files: Annotated[list[UploadFile], File()],
) -> AnnotationImportResponse:
    """Import CoralNet-Toolbox annotation JSON plus optional mapping/YAML files."""

    uploads = [(upload.filename, upload.file) for upload in files]
    return service(request, session).import_streams(project_id, uploads)

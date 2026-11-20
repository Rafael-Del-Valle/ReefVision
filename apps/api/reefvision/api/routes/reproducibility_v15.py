"""Local research package export, inspection and import as a new project."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models.project import Project
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.reproducibility_v15 import (
    ReproducibilityCreate,
    ReproducibilityImport,
    ReproducibilityInspection,
    ReproducibilityPackage,
    ReproducibilityProof,
    ReproducibilityQueued,
)
from reefvision.services.reproducibility_lineage_v15 import project_proofs
from reefvision.services.reproducibility_v15 import ReproducibilityService, inspect_bundle

router = APIRouter(tags=["reproducibility package"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("/projects/{project_id}/reproducibility-packages", status_code=202)
def export_package(
    project_id: UUID,
    payload: ReproducibilityCreate,
    request: Request,
    session: DbSession,
) -> ReproducibilityQueued:
    return ReproducibilityService(session, request.app.state.settings).queue(
        str(project_id), payload
    )


@router.get("/projects/{project_id}/reproducibility-packages")
def list_packages(
    project_id: UUID,
    request: Request,
    session: DbSession,
) -> list[ReproducibilityPackage]:
    return ReproducibilityService(session, request.app.state.settings).list(str(project_id))


@router.get("/projects/{project_id}/reproducibility-proofs")
def get_proofs(project_id: UUID, session: DbSession) -> list[ReproducibilityProof]:
    if session.get(Project, str(project_id)) is None:
        raise NotFoundError("Project not found")
    return project_proofs(session, str(project_id))


@router.post("/reproducibility-packages/inspect")
def inspect_package(file: Annotated[UploadFile, File(...)]) -> ReproducibilityInspection:
    return inspect_bundle(file.file)


@router.post("/reproducibility-packages/import", status_code=201)
def import_package(
    request: Request,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
    project_name: Annotated[str | None, Form()] = None,
) -> ReproducibilityImport:
    return ReproducibilityService(session, request.app.state.settings).restore(
        file.file, project_name
    )


@router.get("/reproducibility-packages/{package_id}")
def get_package(package_id: UUID, request: Request, session: DbSession) -> ReproducibilityPackage:
    return ReproducibilityService(session, request.app.state.settings).get(str(package_id))


@router.get("/reproducibility-packages/{package_id}/download")
def download_package(package_id: UUID, request: Request, session: DbSession) -> FileResponse:
    path = ReproducibilityService(session, request.app.state.settings).download(str(package_id))
    return FileResponse(path, media_type="application/zip", filename=path.name)

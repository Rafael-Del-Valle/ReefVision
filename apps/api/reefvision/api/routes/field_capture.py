"""Normal offline field capture and portable local batch transfer."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError as SchemaValidationError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from reefvision.api.dependencies import get_db_session
from reefvision.domain.errors import ValidationError
from reefvision.schemas.field_capture import (
    FieldCaptureBatchCreate,
    FieldCaptureBatchPage,
    FieldCaptureBatchResponse,
    FieldCaptureImportResponse,
    FieldCaptureMetadata,
    FieldCaptureObservationResponse,
    FieldCaptureReconcileRequest,
    FieldCaptureReconciliation,
    FieldCaptureReviewCreate,
    FieldCaptureReviewResponse,
)
from reefvision.services.field_capture import FieldCaptureService
from reefvision.services.field_capture_reconciliation import FieldCaptureReconciliationService
from reefvision.storage.field_capture import FieldCaptureStorage

router = APIRouter(prefix="/projects/{project_id}/field-capture", tags=["field capture"])
DbSession = Annotated[Session, Depends(get_db_session)]


def _service(request: Request, session: Session) -> FieldCaptureService:
    return FieldCaptureService(session, request.app.state.settings)


@router.get("/batches", response_model=FieldCaptureBatchPage)
def list_batches(
    project_id: UUID,
    request: Request,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> FieldCaptureBatchPage:
    return _service(request, session).list_batches(str(project_id), page, page_size)


@router.post("/batches", response_model=FieldCaptureBatchResponse, status_code=201)
def create_batch(
    project_id: UUID,
    payload: FieldCaptureBatchCreate,
    request: Request,
    session: DbSession,
) -> FieldCaptureBatchResponse:
    return _service(request, session).create_batch(str(project_id), payload.label)


@router.get("/batches/{batch_id}", response_model=FieldCaptureBatchResponse)
def get_batch(
    project_id: UUID,
    batch_id: UUID,
    request: Request,
    session: DbSession,
) -> FieldCaptureBatchResponse:
    service = _service(request, session)
    return service.response(service.batch(str(project_id), str(batch_id)))


@router.post(
    "/batches/{batch_id}/observations",
    response_model=FieldCaptureObservationResponse,
    status_code=201,
)
def add_observation(
    project_id: UUID,
    batch_id: UUID,
    request: Request,
    session: DbSession,
    file: Annotated[UploadFile, File()],
    metadata: Annotated[str, Form(max_length=16000)],
) -> FieldCaptureObservationResponse:
    try:
        source = FieldCaptureMetadata.model_validate_json(metadata)
    except SchemaValidationError as exc:
        raise ValidationError("Invalid field observation: " + str(exc.errors()[0]["msg"])) from exc
    return _service(request, session).add_observation(
        str(project_id), str(batch_id), file.filename, file.file, source
    )


@router.get(
    "/batches/{batch_id}/observations/{observation_id}/content", response_class=FileResponse
)
def source_content(
    project_id: UUID,
    batch_id: UUID,
    observation_id: UUID,
    request: Request,
    session: DbSession,
) -> FileResponse:
    path, name = _service(request, session).source(
        str(project_id), str(batch_id), str(observation_id)
    )
    return FileResponse(path, filename=name)


@router.post("/batches/{batch_id}/seal", response_model=FieldCaptureBatchResponse)
def seal_batch(
    project_id: UUID,
    batch_id: UUID,
    request: Request,
    session: DbSession,
) -> FieldCaptureBatchResponse:
    return _service(request, session).seal(str(project_id), str(batch_id))


@router.get("/batches/{batch_id}/archive", response_class=FileResponse)
def export_archive(
    project_id: UUID,
    batch_id: UUID,
    request: Request,
    session: DbSession,
) -> FileResponse:
    path = _service(request, session).export_archive(str(project_id), str(batch_id))
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"field-batch-{batch_id}.reefvision-field.zip",
        background=BackgroundTask(FieldCaptureStorage.remove_archive, path),
    )


@router.post("/imports", response_model=FieldCaptureImportResponse)
def import_archive(
    project_id: UUID,
    request: Request,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> FieldCaptureImportResponse:
    return _service(request, session).import_archive(str(project_id), file.file)


@router.post("/batches/{batch_id}/reconcile", response_model=FieldCaptureReconciliation)
def reconcile(
    project_id: UUID,
    batch_id: UUID,
    payload: FieldCaptureReconcileRequest,
    request: Request,
    session: DbSession,
) -> FieldCaptureReconciliation:
    return FieldCaptureReconciliationService(session, request.app.state.settings).reconcile(
        str(project_id),
        str(batch_id),
        payload.manifest_sha256,
    )


@router.get("/batches/{batch_id}/reconciliation", response_model=FieldCaptureReconciliation)
def get_reconciliation(
    project_id: UUID,
    batch_id: UUID,
    request: Request,
    session: DbSession,
) -> FieldCaptureReconciliation:
    return FieldCaptureReconciliationService(session, request.app.state.settings).get_report(
        str(project_id),
        str(batch_id),
    )


@router.get("/batches/{batch_id}/reviews", response_model=list[FieldCaptureReviewResponse])
def list_reviews(
    project_id: UUID,
    batch_id: UUID,
    request: Request,
    session: DbSession,
) -> list[FieldCaptureReviewResponse]:
    return FieldCaptureReconciliationService(session, request.app.state.settings).list_reviews(
        str(project_id),
        str(batch_id),
    )


@router.post("/batches/{batch_id}/reviews", response_model=FieldCaptureReviewResponse)
def record_review(
    project_id: UUID,
    batch_id: UUID,
    payload: FieldCaptureReviewCreate,
    request: Request,
    session: DbSession,
) -> FieldCaptureReviewResponse:
    return FieldCaptureReconciliationService(session, request.app.state.settings).review(
        str(project_id),
        str(batch_id),
        payload,
    )

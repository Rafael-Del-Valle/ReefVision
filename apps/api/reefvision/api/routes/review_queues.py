"""Review-queue generation and queue-item endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.domain.errors import ConflictError
from reefvision.schemas.review_queues import (
    ReviewQueueBulkRequest,
    ReviewQueueBulkResponse,
    ReviewQueueCreateRequest,
    ReviewQueueItemActorRequest,
    ReviewQueueItemCompleteRequest,
    ReviewQueueItemPageResponse,
    ReviewQueueItemResponse,
    ReviewQueueItemSkipRequest,
    ReviewQueueResponse,
)
from reefvision.services.review_queue_bulk import (
    _is_sqlite_writer_contention,
    bulk_triage_review_queue,
)
from reefvision.services.review_queues import ReviewQueueService

router = APIRouter(tags=["review_queues"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ReviewQueueService:
    settings: Settings = request.app.state.settings
    return ReviewQueueService(session, settings)


def _reject_reserved_workflow_creator(payload: ReviewQueueCreateRequest) -> None:
    """Public queue creation cannot impersonate a saved Workflow Builder node."""
    creator = payload.created_by
    if creator is not None and creator.strip().lower().startswith("workflow:"):
        raise HTTPException(
            status_code=422,
            detail="The workflow: creator namespace is reserved for saved workflow execution",
        )


@router.get("/projects/{project_id}/review-queues", response_model=list[ReviewQueueResponse])
def list_project_review_queues(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[ReviewQueueResponse]:
    return service(request, session).list_queues(project_id)


@router.post(
    "/projects/{project_id}/review-queues",
    response_model=ReviewQueueResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_review_queue(
    project_id: str,
    payload: ReviewQueueCreateRequest,
    request: Request,
    session: DbSession,
) -> ReviewQueueResponse:
    _reject_reserved_workflow_creator(payload)
    return service(request, session).create_queue_for_project(project_id, payload)


@router.get(
    "/dataset-versions/{version_id}/review-queues",
    response_model=list[ReviewQueueResponse],
)
def list_dataset_version_review_queues(
    version_id: str,
    request: Request,
    session: DbSession,
) -> list[ReviewQueueResponse]:
    version = service(request, session).quality_control._version(version_id)
    return service(request, session).list_queues(version.project_id, dataset_version_id=version.id)


@router.post(
    "/dataset-versions/{version_id}/review-queues",
    response_model=ReviewQueueResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_version_review_queue(
    version_id: str,
    payload: ReviewQueueCreateRequest,
    request: Request,
    session: DbSession,
) -> ReviewQueueResponse:
    _reject_reserved_workflow_creator(payload)
    return service(request, session).create_queue_for_dataset_version(version_id, payload)


@router.get("/review-queues/{queue_id}", response_model=ReviewQueueResponse)
def get_review_queue(
    queue_id: str,
    request: Request,
    session: DbSession,
) -> ReviewQueueResponse:
    return service(request, session).get_queue(queue_id)


@router.get("/review-queues/{queue_id}/items", response_model=ReviewQueueItemPageResponse)
def list_review_queue_items(
    queue_id: str,
    request: Request,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    label_class_id: str | None = None,
    split: str | None = None,
    qc_severity: str | None = None,
    review_state: str | None = None,
    model_id: str | None = None,
) -> ReviewQueueItemPageResponse:
    return service(request, session).list_items(
        queue_id,
        page=page,
        page_size=page_size,
        label_class_id=label_class_id,
        split=split,
        qc_severity=qc_severity,
        review_state=review_state,
        model_id=model_id,
    )


@router.post(
    "/review-queues/{queue_id}/items/bulk",
    response_model=ReviewQueueBulkResponse,
)
def bulk_review_queue_items(
    queue_id: str,
    payload: ReviewQueueBulkRequest,
    session: DbSession,
) -> ReviewQueueBulkResponse:
    """Manual operator triage, never automatic scientific approval.

    SQLite can reject a read *before* the bulk service reaches its commit
    handler when another local process holds an exclusive database lock.
    Convert only genuine BUSY/LOCKED errors to retryable HTTP conflicts;
    preserve unrelated database failures for diagnosis.
    """
    try:
        return bulk_triage_review_queue(session, queue_id, payload)
    except OperationalError as exc:
        session.rollback()
        if session.get_bind().dialect.name != "sqlite" or not _is_sqlite_writer_contention(exc):
            raise
        raise ConflictError("SQLite review queue is busy; retry the same bulk request ID") from exc


@router.post("/review-queue-items/{item_id}/start", response_model=ReviewQueueItemResponse)
def start_review_queue_item(
    item_id: str,
    request: Request,
    session: DbSession,
    payload: ReviewQueueItemActorRequest | None = None,
) -> ReviewQueueItemResponse:
    return service(request, session).start_item(
        item_id, actor=payload.actor if payload else "local_user"
    )


@router.post("/review-queue-items/{item_id}/complete", response_model=ReviewQueueItemResponse)
def complete_review_queue_item(
    item_id: str,
    payload: ReviewQueueItemCompleteRequest,
    request: Request,
    session: DbSession,
) -> ReviewQueueItemResponse:
    # Schema rejects missing/false confirmation before any review state mutation.
    return service(request, session).complete_item(item_id, actor=payload.actor)


@router.post("/review-queue-items/{item_id}/skip", response_model=ReviewQueueItemResponse)
def skip_review_queue_item(
    item_id: str,
    payload: ReviewQueueItemSkipRequest,
    request: Request,
    session: DbSession,
) -> ReviewQueueItemResponse:
    return service(request, session).skip_item(item_id, payload)


@router.post("/review-queue-items/{item_id}/return", response_model=ReviewQueueItemResponse)
def return_review_queue_item(
    item_id: str,
    request: Request,
    session: DbSession,
    payload: ReviewQueueItemActorRequest | None = None,
) -> ReviewQueueItemResponse:
    return service(request, session).return_item(
        item_id, actor=payload.actor if payload else "local_user"
    )


@router.post("/review-queues/{queue_id}/regenerate", response_model=ReviewQueueResponse)
def regenerate_review_queue(
    queue_id: str,
    request: Request,
    session: DbSession,
) -> ReviewQueueResponse:
    return service(request, session).regenerate(queue_id)

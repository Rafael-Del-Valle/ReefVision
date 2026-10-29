"""Local researcher comments and assignment history on QC queue items."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from reefvision.domain.errors import ConflictError
from reefvision.services.review_queue_bulk import _is_sqlite_writer_contention

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.review_queue_events import (
    ReviewQueueEventCreate,
    ReviewQueueEventResponse,
    ReviewQueueEventsPage,
)
from reefvision.services.review_queue_events import (
    create_review_event,
    list_review_events,
)

router = APIRouter(tags=["review_queues"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/review-queues/{queue_id}/items/{item_id}/events",
    response_model=ReviewQueueEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_review_event(
    queue_id: str,
    item_id: str,
    payload: ReviewQueueEventCreate,
    session: DbSession,
) -> ReviewQueueEventResponse:
    """Append a self-labeled local comment or assignment; never approve data."""
    try:
        return create_review_event(session, queue_id, item_id, payload)
    except OperationalError as exc:
        # SQLite can reject the initial scope read or the eventual append.
        # A failed append must never be reported as a successful review event.
        session.rollback()
        if session.get_bind().dialect.name != "sqlite" or not _is_sqlite_writer_contention(exc):
            raise
        raise ConflictError("SQLite review queue is busy; retry the same event request ID") from exc


@router.get(
    "/review-queues/{queue_id}/items/{item_id}/events",
    response_model=ReviewQueueEventsPage,
)
def get_review_events(
    queue_id: str,
    item_id: str,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ReviewQueueEventsPage:
    return list_review_events(session, queue_id, item_id, page=page, page_size=page_size)

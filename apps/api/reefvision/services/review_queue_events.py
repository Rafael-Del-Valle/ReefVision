"""Append-only review-queue coordination; never changes scientific annotations."""

from __future__ import annotations

import sqlite3

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.db.models import ReviewQueue, ReviewQueueItem
from reefvision.db.models.review_queue_item_event import ReviewQueueItemEvent
from reefvision.domain.errors import ConflictError, NotFoundError
from reefvision.schemas.review_queue_events import (
    ReviewQueueEventCreate,
    ReviewQueueEventResponse,
    ReviewQueueEventsPage,
)


def _scope(session: Session, queue_id: str, item_id: str) -> ReviewQueueItem:
    queue = session.get(ReviewQueue, queue_id)
    if queue is None:
        raise NotFoundError("Review queue not found")
    item = session.get(ReviewQueueItem, item_id)
    if item is None:
        raise NotFoundError("Review queue item not found")
    if item.review_queue_id != queue_id or item.project_id != queue.project_id:
        raise ConflictError("Review item does not belong to this queue")
    if queue.status != "complete":
        raise ConflictError("Review queue is not ready for coordination")
    # Refuse new coordination writes as well as reads when prior reviewer
    # evidence has been moved across project/queue boundaries. Otherwise a
    # fresh request key could append to a scientifically inconsistent history.
    foreign_event_id = session.scalar(
        select(ReviewQueueItemEvent.id)
        .where(
            ReviewQueueItemEvent.review_queue_item_id == item_id,
            (
                (ReviewQueueItemEvent.review_queue_id != queue_id)
                | (ReviewQueueItemEvent.project_id != item.project_id)
            ),
        )
        .limit(1)
    )
    if foreign_event_id is not None:
        raise ConflictError("Review event provenance does not match its queue")
    return item


def _existing(session: Session, item_id: str, request_id: str) -> ReviewQueueItemEvent | None:
    return session.scalar(
        select(ReviewQueueItemEvent).where(
            ReviewQueueItemEvent.review_queue_item_id == item_id,
            ReviewQueueItemEvent.client_request_id == request_id,
        )
    )


def _same(
    event: ReviewQueueItemEvent,
    payload: ReviewQueueEventCreate,
    *,
    queue_id: str,
    item: ReviewQueueItem,
) -> bool:
    # A request key cannot validate an event whose persisted scientific scope
    # disagrees with the item. Never trust a matching actor/comment alone.
    return (
        event.review_queue_id == queue_id
        and event.review_queue_item_id == item.id
        and event.project_id == item.project_id
        and event.event_type == payload.event_type
        and event.actor == payload.actor
        and event.comment == payload.comment
        and event.assignee == payload.assignee
    )


def _is_sqlite_event_request_collision(exc: IntegrityError) -> bool:
    """Only the event's own idempotency key permits a concurrent replay.

    Unrelated UNIQUE/PRIMARY KEY, foreign-key and NOT NULL violations must
    propagate after rollback; they are not evidence of an identical request.
    """
    if not isinstance(exc.orig, sqlite3.IntegrityError):
        return False
    return (
        getattr(exc.orig, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE
        and str(exc.orig)
        == (
            "UNIQUE constraint failed: "
            "review_queue_item_events.review_queue_item_id, "
            "review_queue_item_events.client_request_id"
        )
    )


def create_review_event(
    session: Session, queue_id: str, item_id: str, payload: ReviewQueueEventCreate
) -> ReviewQueueEventResponse:
    item = _scope(session, queue_id, item_id)
    request_id = str(payload.client_request_id)
    prior = _existing(session, item.id, request_id)
    if prior is not None:
        if not _same(prior, payload, queue_id=queue_id, item=item):
            raise ConflictError("Request ID already used for a different review event")
        return ReviewQueueEventResponse.model_validate(prior)

    event = ReviewQueueItemEvent(
        review_queue_id=queue_id,
        review_queue_item_id=item.id,
        project_id=item.project_id,
        client_request_id=request_id,
        event_type=payload.event_type,
        actor=payload.actor,
        comment=payload.comment,
        assignee=payload.assignee,
    )
    session.add(event)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # Only a collision on this event's idempotency key can represent a
        # concurrent identical retry. Other integrity failures are defects.
        if not _is_sqlite_event_request_collision(exc):
            raise
        prior = _existing(session, item_id, request_id)
        if prior is None or not _same(prior, payload, queue_id=queue_id, item=item):
            raise ConflictError("Review event request ID conflict") from None
        return ReviewQueueEventResponse.model_validate(prior)
    session.refresh(event)
    return ReviewQueueEventResponse.model_validate(event)


def list_review_events(
    session: Session,
    queue_id: str,
    item_id: str,
    *,
    page: int,
    page_size: int,
) -> ReviewQueueEventsPage:
    _scope(session, queue_id, item_id)
    filters = [ReviewQueueItemEvent.review_queue_item_id == item_id]
    total = (
        session.scalar(select(func.count()).select_from(ReviewQueueItemEvent).where(*filters)) or 0
    )
    events = list(
        session.scalars(
            select(ReviewQueueItemEvent)
            .where(*filters)
            .order_by(
                ReviewQueueItemEvent.created_at,
                ReviewQueueItemEvent.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    assignment = session.scalar(
        select(ReviewQueueItemEvent)
        .where(
            *filters,
            ReviewQueueItemEvent.event_type.in_(("assign", "unassign")),
        )
        .order_by(
            ReviewQueueItemEvent.created_at.desc(),
            ReviewQueueItemEvent.id.desc(),
        )
        .limit(1)
    )
    return ReviewQueueEventsPage(
        items=[ReviewQueueEventResponse.model_validate(item) for item in events],
        total=total,
        page=page,
        page_size=page_size,
        current_assignee=(
            assignment.assignee
            if assignment is not None and assignment.event_type == "assign"
            else None
        ),
    )

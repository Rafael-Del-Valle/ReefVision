"""Atomic, retry-safe manual triage for existing QC review queues.

This API does not accept/verify scientific observations or model predictions.
All items are validated before any state is changed; one transaction commits the batch.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import ReviewQueue, ReviewQueueItem
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.review_queues import (
    ReviewQueueBulkRequest,
    ReviewQueueBulkResponse,
    ReviewQueueItemResponse,
)


def bulk_triage_review_queue(
    session: Session, queue_id: str, request: ReviewQueueBulkRequest
) -> ReviewQueueBulkResponse:
    queue = session.get(ReviewQueue, queue_id)
    if queue is None:
        raise NotFoundError("Review queue not found")
    if queue.status != "complete":
        raise ConflictError("Only generated review queues can be triaged")
    if len(set(request.item_ids)) != len(request.item_ids):
        raise ValidationError("Bulk review item IDs must be unique")

    reason = (request.reason or "").strip()
    if request.action == "skip" and not reason:
        raise ValidationError("A nonempty reason is required to skip items")
    if request.action != "skip" and request.reason is not None:
        raise ValidationError("Reason is only accepted when skipping items")

    items = list(
        session.scalars(select(ReviewQueueItem).where(ReviewQueueItem.id.in_(request.item_ids)))
    )
    by_id = {item.id: item for item in items}
    ordered: list[ReviewQueueItem] = []
    for item_id in request.item_ids:
        item = by_id.get(item_id)
        if item is None:
            raise NotFoundError("Review queue item not found")
        if item.review_queue_id != queue_id or item.project_id != queue.project_id:
            raise ConflictError("Review item belongs to another review queue")
        if request.action == "start" and item.review_state not in {
            "pending",
            "in_progress",
        }:
            raise ConflictError("Only pending review items can be started")
        if request.action == "skip" and (
            item.review_state not in {"pending", "in_progress", "skipped"}
            or (item.review_state == "skipped" and item.skip_reason != reason)
        ):
            raise ConflictError("Only active review items can be skipped with this reason")
        if request.action == "return" and (
            item.review_state != "skipped"
            and not (item.review_state == "pending" and item.returned_at is not None)
        ):
            raise ConflictError("Only previously skipped items can be returned")
        ordered.append(item)

    now = datetime.now(UTC)
    changed = 0
    for item in ordered:
        if request.action == "start" and item.review_state == "pending":
            item.review_state = "in_progress"
            item.started_at = now
            changed += 1
        elif request.action == "skip" and item.review_state != "skipped":
            item.review_state = "skipped"
            item.skip_reason = reason
            item.completed_at = None
            changed += 1
        elif request.action == "return" and item.review_state == "skipped":
            item.review_state = "pending"
            item.returned_at = now
            changed += 1

    if changed:
        session.commit()
        for item in ordered:
            session.refresh(item)
    return ReviewQueueBulkResponse(
        queue_id=queue_id,
        action=request.action,
        changed_count=changed,
        items=[ReviewQueueItemResponse.model_validate(item) for item in ordered],
    )

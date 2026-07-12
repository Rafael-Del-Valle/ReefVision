"""Persistence helpers for review queues and queue items."""

from __future__ import annotations

from math import ceil

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from reefvision.db.models import ReviewQueue, ReviewQueueItem


class ReviewQueueRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_queue(self, queue: ReviewQueue) -> None:
        self.session.add(queue)

    def add_items(self, items: list[ReviewQueueItem]) -> None:
        self.session.add_all(items)

    def get_queue(self, queue_id: str) -> ReviewQueue | None:
        return self.session.get(ReviewQueue, queue_id)

    def get_item(self, item_id: str) -> ReviewQueueItem | None:
        return self.session.get(ReviewQueueItem, item_id)

    def list_queues(
        self,
        project_id: str,
        *,
        dataset_version_id: str | None = None,
    ) -> list[ReviewQueue]:
        filters = [ReviewQueue.project_id == project_id]
        if dataset_version_id is None:
            filters.append(ReviewQueue.dataset_version_id.is_(None))
        else:
            filters.append(ReviewQueue.dataset_version_id == dataset_version_id)
        statement = (
            select(ReviewQueue)
            .where(*filters)
            .order_by(desc(ReviewQueue.created_at), desc(ReviewQueue.id))
        )
        return list(self.session.scalars(statement))

    def items_for_queue(self, queue_id: str) -> list[ReviewQueueItem]:
        statement = (
            select(ReviewQueueItem)
            .where(ReviewQueueItem.review_queue_id == queue_id)
            .order_by(ReviewQueueItem.rank_position, desc(ReviewQueueItem.score))
        )
        return list(self.session.scalars(statement))

    def paged_items(
        self,
        queue_id: str,
        *,
        page: int,
        page_size: int,
        label_class_id: str | None,
        split: str | None,
        qc_severity: str | None,
        review_state: str | None,
        model_id: str | None,
    ) -> tuple[list[ReviewQueueItem], int, int]:
        items = self.items_for_queue(queue_id)
        filtered = [
            item
            for item in items
            if (label_class_id is None or label_class_id in item.label_class_ids_json)
            and (split is None or item.split == split)
            and (qc_severity is None or item.highest_qc_severity == qc_severity)
            and (review_state is None or item.review_state == review_state)
            and (model_id is None or model_id in item.model_ids_json)
        ]
        total = len(filtered)
        pages = max(1, ceil(total / page_size)) if total else 1
        start = (page - 1) * page_size
        end = start + page_size
        return filtered[start:end], total, pages

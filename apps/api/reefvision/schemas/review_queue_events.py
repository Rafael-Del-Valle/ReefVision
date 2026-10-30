"""Typed local coordination events for QC review queues."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ReviewEventType = Literal[
    "comment",
    "assign",
    "unassign",
    "triage_start",
    "triage_skip",
    "triage_return",
    "triage_complete",
]


class ReviewQueueEventCreate(BaseModel):
    client_request_id: UUID
    # State-transition audit events are server-generated only. Clients may
    # submit comments and assignments but cannot forge triage history.
    event_type: Literal["comment", "assign", "unassign"]
    actor: str = Field(min_length=1, max_length=100)
    comment: str | None = Field(default=None, max_length=2000)
    assignee: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_action(self) -> ReviewQueueEventCreate:
        self.actor = self.actor.strip()
        if not self.actor:
            raise ValueError("Actor label cannot be blank")
        if self.event_type == "comment":
            self.comment = (self.comment or "").strip()
            if not self.comment or self.assignee is not None:
                raise ValueError("Comment requires text and no assignee")
        elif self.event_type == "assign":
            self.assignee = (self.assignee or "").strip()
            if not self.assignee or self.comment is not None:
                raise ValueError("Assignment requires an assignee and no comment")
        elif self.comment is not None or self.assignee is not None:
            raise ValueError("Unassign does not accept a comment or assignee")
        return self


class ReviewQueueEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    review_queue_id: str
    review_queue_item_id: str
    project_id: str
    client_request_id: str
    event_type: ReviewEventType
    actor: str
    comment: str | None
    assignee: str | None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def explicit_utc_timestamp(cls, value: datetime) -> datetime:
        """SQLite strips timezone offsets from UTC audit timestamps on read.

        Existing ReefVision audit events were created with utc_now(), so
        legacy naive SQLite values represent UTC, not local workstation time.
        Emit explicit UTC for both new events and persisted workflow replays.
        """
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ReviewQueueEventsPage(BaseModel):
    items: list[ReviewQueueEventResponse]
    total: int
    page: int
    page_size: int
    current_assignee: str | None
    requires_researcher_review: bool = True

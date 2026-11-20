"""Poll durable schedule cursors independently of long-running local workflow jobs."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models.workflow_schedule import WorkflowSchedule
from reefvision.services.workflow_schedules import WorkflowScheduleService

LOGGER = logging.getLogger("reefvision.workflow_schedules")


def dispatch_due_schedules(
    settings: Settings, factory: sessionmaker[Session], *, now: datetime | None = None
) -> int:
    """Admit all due schedule IDs independently; a failed transaction cannot leak a job."""
    if settings.safe_mode:
        return 0
    clock = datetime.now(UTC) if now is None else now.astimezone(UTC)
    with factory() as session:
        due = session.execute(
            select(WorkflowSchedule.id, WorkflowSchedule.revision, WorkflowSchedule.next_due_at)
            .where(WorkflowSchedule.enabled.is_(True), WorkflowSchedule.next_due_at <= clock)
            .order_by(WorkflowSchedule.next_due_at, WorkflowSchedule.id)
        ).all()
    count = 0
    for identifier, revision, cursor in due:
        try:
            with factory.begin() as session:
                dispatched = WorkflowScheduleService(session, settings).dispatch(identifier, clock)
            count += int(dispatched)
        except Exception:
            LOGGER.exception(
                "Scheduled workflow dispatch rolled back",
                extra={
                    "event_id": "workflow_schedule_dispatch_failure",
                    "component": "workflow_schedule",
                    "schedule_id": identifier,
                },
            )
            # A competing success/edit changes this condition and wins over stale diagnostics.
            with factory.begin() as session:
                session.execute(
                    update(WorkflowSchedule)
                    .where(
                        WorkflowSchedule.id == identifier,
                        WorkflowSchedule.revision == revision,
                        WorkflowSchedule.enabled.is_(True),
                        WorkflowSchedule.next_due_at == cursor,
                    )
                    .values(
                        last_status="dispatch_failed",
                        last_message="Dispatch could not be saved. The same occurrence will retry.",
                    )
                )
    return count


async def workflow_schedule_loop(
    settings: Settings, factory: sessionmaker[Session], stop_event: asyncio.Event
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(dispatch_due_schedules, settings, factory)
        except Exception:
            LOGGER.exception(
                "Workflow schedule poll failed",
                extra={
                    "event_id": "workflow_schedule_poll_failure",
                    "component": "workflow_schedule",
                },
            )
        with suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=settings.worker_poll_seconds)

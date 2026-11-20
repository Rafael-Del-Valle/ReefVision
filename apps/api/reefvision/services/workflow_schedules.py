"""Local persistence, once-only dispatch, and status of recurring saved workflows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job, Project, WorkflowGraphRecord, WorkflowRun
from reefvision.db.models.workflow_schedule import WorkflowSchedule, WorkflowScheduleOccurrence
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.workflow_graphs import WorkflowGraphPlanResponse
from reefvision.schemas.workflow_schedules import (
    WorkflowScheduleCreate,
    WorkflowScheduleOccurrencePage,
    WorkflowScheduleOccurrenceRead,
    WorkflowSchedulePage,
    WorkflowScheduleRead,
    WorkflowScheduleUpdate,
)
from reefvision.services.jobs import JobService
from reefvision.services.workflow_execution import WorkflowExecutionService
from reefvision.services.workflow_schedule_graphs import schedule_graph_inputs
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.workflow_schedules import available_storage_bytes

_ACTIVE_RUNS = ("queued", "running", "waiting_for_review", "cancel_requested")
_ARCHIVED_MESSAGE = "The project is archived. Restore it before dispatching scheduled work."


def _utc(value: datetime) -> datetime:
    # SQLite serializes aware columns as naive UTC. Other engines retain the offset.
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _next(due_at: datetime, cadence: timedelta) -> datetime:
    try:
        return due_at + cadence
    except OverflowError as exc:
        raise ValidationError("The chosen time and interval exceed the supported calendar") from exc


class WorkflowScheduleService:
    def __init__(self, session: Session, settings: Settings):
        self.session = session
        self.settings = settings
        self.workflows = WorkflowExecutionService(session, settings)

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _schedule(self, project_id: str, schedule_id: str) -> WorkflowSchedule:
        schedule = self.session.get(WorkflowSchedule, schedule_id)
        if schedule is None or schedule.project_id != project_id:
            raise NotFoundError("Workflow schedule not found in this project")
        return schedule

    def _admit(
        self, project_id: str, graph_record_id: str, purpose: str
    ) -> tuple[WorkflowGraphRecord, WorkflowGraphPlanResponse, dict[str, Any]]:
        record = self.session.get(WorkflowGraphRecord, graph_record_id)
        if record is None or record.project_id != project_id:
            raise ValidationError("Choose a saved workflow revision within this project")
        if canonical_json_sha256(record.graph_json) != record.graph_sha256:
            raise ValidationError("Saved workflow revision no longer matches its checksum")
        record, plan = self.workflows.prepare_run(project_id, graph_record_id)
        inputs = schedule_graph_inputs(self.session, project_id, purpose, plan)
        return record, plan, inputs

    def _schedule_read(self, schedule: WorkflowSchedule) -> WorkflowScheduleRead:
        state, message = schedule.last_status, schedule.last_message
        if state == "queued":
            latest = self.session.scalar(
                select(WorkflowScheduleOccurrence)
                .where(WorkflowScheduleOccurrence.schedule_id == schedule.id)
                .order_by(
                    WorkflowScheduleOccurrence.created_at.desc(),
                    WorkflowScheduleOccurrence.id.desc(),
                )
                .limit(1)
            )
            if latest is not None:
                occurrence = self._occurrence_read(latest)
                state, message = occurrence.status, occurrence.detail or message
        return WorkflowScheduleRead.model_validate(
            {
                "id": schedule.id,
                "project_id": schedule.project_id,
                "name": schedule.name,
                "purpose": schedule.purpose,
                "workflow_graph_record_id": schedule.workflow_graph_record_id,
                "graph_sha256": schedule.graph_sha256,
                "inputs": schedule.inputs_json,
                "inputs_sha256": schedule.inputs_sha256,
                "interval_seconds": schedule.interval_seconds,
                "next_due_at": _utc(schedule.next_due_at),
                "enabled": schedule.enabled,
                "revision": schedule.revision,
                "minimum_free_bytes": schedule.minimum_free_bytes,
                "last_status": state,
                "last_message": message,
                "created_at": _utc(schedule.created_at),
                "updated_at": _utc(schedule.updated_at),
            }
        )

    def _occurrence_read(
        self, occurrence: WorkflowScheduleOccurrence
    ) -> WorkflowScheduleOccurrenceRead:
        run = (
            self.session.get(WorkflowRun, occurrence.workflow_run_id, populate_existing=True)
            if occurrence.workflow_run_id
            else None
        )
        return WorkflowScheduleOccurrenceRead.model_validate(
            {
                "id": occurrence.id,
                "project_id": occurrence.project_id,
                "schedule_id": occurrence.schedule_id,
                "scheduled_at": _utc(occurrence.scheduled_at),
                "created_at": _utc(occurrence.created_at),
                "missed_intervals": occurrence.missed_intervals,
                "status": run.status if run else occurrence.status,
                "detail": (run.error_message if run else None) or occurrence.detail,
                "workflow_run_id": occurrence.workflow_run_id,
                "job_id": run.job_id if run else None,
                "graph_sha256": occurrence.graph_sha256,
                "inputs_sha256": occurrence.inputs_sha256,
            }
        )

    def list(self, project_id: str, *, limit: int, offset: int) -> WorkflowSchedulePage:
        self._project(project_id)
        scope = WorkflowSchedule.project_id == project_id
        rows = self.session.scalars(
            select(WorkflowSchedule)
            .where(scope)
            .order_by(WorkflowSchedule.created_at.desc(), WorkflowSchedule.id.desc())
            .offset(offset)
            .limit(limit)
        )
        total = self.session.scalar(select(func.count()).select_from(WorkflowSchedule).where(scope))
        return WorkflowSchedulePage(
            items=[self._schedule_read(row) for row in rows], total=int(total or 0)
        )

    def create(self, project_id: str, payload: WorkflowScheduleCreate) -> WorkflowScheduleRead:
        if self._project(project_id).archived_at is not None:
            raise ConflictError(_ARCHIVED_MESSAGE)
        if payload.inputs:
            raise ValidationError(
                "Schedule inputs must be pinned in the saved graph. Remove invocation overrides."
            )
        _next(payload.next_due_at, timedelta(seconds=payload.interval_seconds))
        record, _, inputs = self._admit(
            project_id, str(payload.workflow_graph_record_id), payload.purpose
        )
        schedule = WorkflowSchedule(
            project_id=project_id,
            name=payload.name,
            purpose=payload.purpose,
            workflow_graph_record_id=record.id,
            graph_sha256=record.graph_sha256,
            inputs_json=inputs,
            inputs_sha256=canonical_json_sha256(inputs),
            interval_seconds=payload.interval_seconds,
            next_due_at=payload.next_due_at,
            enabled=payload.enabled,
            minimum_free_bytes=payload.minimum_free_bytes,
            last_status="scheduled" if payload.enabled else "paused",
        )
        self.session.add(schedule)
        self.session.commit()
        return self._schedule_read(schedule)

    def edit(
        self, project_id: str, schedule_id: str, payload: WorkflowScheduleUpdate
    ) -> WorkflowScheduleRead:
        # Lock first, then read. This serializes edits with admission without overwriting a cursor
        # advanced by a worker while the client held its edit form open.
        claim = self.session.execute(
            update(WorkflowSchedule)
            .where(
                WorkflowSchedule.id == schedule_id,
                WorkflowSchedule.project_id == project_id,
                WorkflowSchedule.revision == payload.expected_revision,
            )
            .values(updated_at=WorkflowSchedule.updated_at)
        )
        if cast(CursorResult[Any], claim).rowcount != 1:
            self._schedule(project_id, schedule_id)
            raise ConflictError("Schedule changed. Reload it before saving.")
        schedule = self._schedule(project_id, schedule_id)
        changes = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
        due_at = changes.get("next_due_at", _utc(schedule.next_due_at))
        interval = changes.get("interval_seconds", schedule.interval_seconds)
        _next(due_at, timedelta(seconds=interval))
        if changes.get("enabled") and self._project(project_id).archived_at is not None:
            raise ConflictError(_ARCHIVED_MESSAGE)
        for name, value in changes.items():
            setattr(schedule, name, value)
        schedule.revision += 1
        schedule.last_status = "scheduled" if schedule.enabled else "paused"
        schedule.last_message = None
        self.session.commit()
        return self._schedule_read(schedule)

    def list_occurrences(
        self, project_id: str, schedule_id: str, *, limit: int, offset: int
    ) -> WorkflowScheduleOccurrencePage:
        self._schedule(project_id, schedule_id)
        scope = (
            WorkflowScheduleOccurrence.project_id == project_id,
            WorkflowScheduleOccurrence.schedule_id == schedule_id,
        )
        rows = self.session.scalars(
            select(WorkflowScheduleOccurrence)
            .where(*scope)
            .order_by(
                WorkflowScheduleOccurrence.scheduled_at.desc(), WorkflowScheduleOccurrence.id.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        total = self.session.scalar(
            select(func.count()).select_from(WorkflowScheduleOccurrence).where(*scope)
        )
        return WorkflowScheduleOccurrencePage(
            items=[self._occurrence_read(row) for row in rows], total=int(total or 0)
        )

    def cancel(
        self, project_id: str, schedule_id: str, occurrence_id: str
    ) -> WorkflowScheduleOccurrenceRead:
        self._schedule(project_id, schedule_id)
        occurrence = self.session.get(WorkflowScheduleOccurrence, occurrence_id)
        if occurrence is None or (occurrence.project_id, occurrence.schedule_id) != (
            project_id,
            schedule_id,
        ):
            raise NotFoundError("Schedule occurrence not found in this project")
        details = self._occurrence_read(occurrence)
        if details.job_id is None:
            raise ConflictError("This occurrence did not dispatch a workflow job")
        # Acquire the job row before JobService reads status so a worker's simultaneous
        # claim cannot turn a queued cancellation into an unobserved running cancellation.
        job_id = str(details.job_id)
        self.session.execute(
            update(Job)
            .where(Job.id == job_id, Job.project_id == project_id)
            .values(status=Job.status)
        )
        job_service = JobService(self.session)
        job = job_service.get(job_id)
        if job.status not in ("cancel_requested", "cancelled"):
            job_service.cancel(job_id)
        else:
            self.session.commit()
        return self._occurrence_read(occurrence)

    def dispatch(self, schedule_id: str, now: datetime) -> bool:
        """Consume one logical due slot and stage its normal workflow in the same commit."""
        claim = self.session.execute(
            update(WorkflowSchedule)
            .where(
                WorkflowSchedule.id == schedule_id,
                WorkflowSchedule.enabled.is_(True),
                WorkflowSchedule.next_due_at <= now,
            )
            .values(updated_at=WorkflowSchedule.updated_at)
        )
        if cast(CursorResult[Any], claim).rowcount != 1:
            return False
        schedule = self.session.get_one(WorkflowSchedule, schedule_id)
        project = self._project(schedule.project_id)
        if project.archived_at is not None:
            schedule.last_status = "failed"
            schedule.last_message = _ARCHIVED_MESSAGE
            return False
        active = self.session.scalar(
            select(WorkflowRun.id)
            .join(
                WorkflowScheduleOccurrence,
                WorkflowScheduleOccurrence.workflow_run_id == WorkflowRun.id,
            )
            .where(
                WorkflowScheduleOccurrence.schedule_id == schedule.id,
                WorkflowRun.status.in_(_ACTIVE_RUNS),
            )
            .limit(1)
        )
        if active:
            schedule.last_status = "waiting_previous_run"
            schedule.last_message = "Waiting for the previous occurrence to finish or be cancelled."
            return False
        if schedule.minimum_free_bytes:
            free_bytes = available_storage_bytes(self.settings.resolved_data_dir)
            if free_bytes is None or free_bytes < schedule.minimum_free_bytes:
                schedule.last_status = "blocked_storage"
                schedule.last_message = (
                    "Free storage on the managed profile volume could not be determined."
                    if free_bytes is None
                    else (
                        f"The profile has {free_bytes} free bytes. "
                        f"{schedule.minimum_free_bytes} bytes are required."
                    )
                )
                return False

        cadence = timedelta(seconds=schedule.interval_seconds)
        due_at = _utc(schedule.next_due_at)
        missed_intervals = (now - due_at) // cadence
        scheduled_at = due_at + missed_intervals * cadence
        next_due_at = _next(scheduled_at, cadence)
        existing = self.session.scalar(
            select(WorkflowScheduleOccurrence.id).where(
                WorkflowScheduleOccurrence.schedule_id == schedule.id,
                WorkflowScheduleOccurrence.scheduled_at == scheduled_at,
            )
        )
        if existing is not None:
            # Editing a cursor back onto a known slot can never create a second job.
            schedule.next_due_at = next_due_at
            schedule.last_status = "scheduled"
            schedule.last_message = "This occurrence was already dispatched."
            return False

        occurrence = WorkflowScheduleOccurrence(
            project_id=schedule.project_id,
            schedule_id=schedule.id,
            scheduled_at=scheduled_at,
            created_at=now,
            missed_intervals=missed_intervals,
            graph_sha256=schedule.graph_sha256,
            inputs_sha256=schedule.inputs_sha256,
            status="queued",
        )
        try:
            record, plan, inputs = self._admit(
                schedule.project_id, schedule.workflow_graph_record_id, schedule.purpose
            )
            if (
                record.graph_sha256 != schedule.graph_sha256
                or inputs != schedule.inputs_json
                or canonical_json_sha256(inputs) != schedule.inputs_sha256
            ):
                raise ValidationError(
                    "The saved graph or its pinned inputs changed; create a new schedule."
                )
        except ValidationError as exc:
            occurrence.status = "failed"
            occurrence.detail = str(exc)
        else:
            run = self.workflows.stage_run(record, plan, inputs)
            occurrence.workflow_run_id = run.id
        self.session.add(occurrence)
        schedule.next_due_at = next_due_at
        schedule.last_status = occurrence.status
        schedule.last_message = occurrence.detail
        return True

"""Preserve schedule history and separately arm an imported schedule on its new machine."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    WorkflowGraphRecord,
    WorkflowRun,
    WorkflowSchedule,
    WorkflowScheduleOccurrence,
)
from reefvision.domain.errors import ValidationError
from reefvision.services.project_exchange_monitoring_v17 import FORMAT as MONITORING_FORMAT
from reefvision.storage.datasets import canonical_json_sha256

FORMAT = "1.7"
SCHEDULES = "workflow_schedules"
OCCURRENCES = "workflow_schedule_occurrences"
SECTIONS = (SCHEDULES, OCCURRENCES)
Rows = dict[str, list[dict[str, Any]]]


def has_schedules(session: Session, project_id: str) -> bool:
    return (
        session.scalar(
            select(WorkflowSchedule.id).where(WorkflowSchedule.project_id == project_id).limit(1)
        )
        is not None
    )


def schedule_dataset_ids(rows: Rows) -> set[str]:
    return {
        ref["id"]
        for schedule in rows.get(SCHEDULES, ())
        for ref in schedule["inputs_json"].get("references", ())
        if ref["kind"] == "dataset_version_source"
    }


def _utc_slot(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)


def validate_schedule_exchange(version: str, project_id: str, rows: Rows) -> None:
    present = any(rows.get(name) for name in SECTIONS)
    if version not in {FORMAT, MONITORING_FORMAT}:
        if present:
            raise ValidationError("Scheduled workflow history requires Project Exchange 1.7")
        return
    if not all(name in rows for name in SECTIONS):
        raise ValidationError("Project Exchange 1.7 is missing its schedule inventory")
    graphs = {g["id"]: g for g in rows.get("workflow_graphs", ())}
    runs = {r["id"]: r for r in rows.get("workflow_runs", ())}
    schedules = {s["id"]: s for s in rows[SCHEDULES]}
    slots: set[tuple[str, datetime]] = set()
    used_runs: set[str] = set()
    try:
        for schedule in schedules.values():
            graph = graphs[schedule["workflow_graph_record_id"]]
            if (
                schedule["project_id"] != project_id
                or graph["project_id"] != project_id
                or schedule["graph_sha256"] != graph["graph_sha256"]
                or canonical_json_sha256(schedule["inputs_json"]) != schedule["inputs_sha256"]
                or schedule["interval_seconds"] < 1
                or schedule["minimum_free_bytes"] < 0
            ):
                raise ValidationError("The scheduled workflow has an invalid graph or input pin")
            _utc_slot(schedule["next_due_at"])
        for slot in rows[OCCURRENCES]:
            schedule = schedules[slot["schedule_id"]]
            due = (schedule["id"], _utc_slot(slot["scheduled_at"]))
            if (
                slot["project_id"] != project_id
                or due in slots
                or slot["missed_intervals"] < 0
                or slot["graph_sha256"] != schedule["graph_sha256"]
                or slot["inputs_sha256"] != schedule["inputs_sha256"]
            ):
                raise ValidationError(
                    "The schedule occurrence has an invalid due slot or input pin"
                )
            slots.add(due)
            run_id = slot["workflow_run_id"]
            if run_id is None:
                if slot["status"] != "failed":
                    raise ValidationError("The dispatched schedule occurrence is missing its run")
            else:
                run = runs[run_id]
                if (
                    run_id in used_runs
                    or run["project_id"] != project_id
                    or run["workflow_graph_record_id"] != schedule["workflow_graph_record_id"]
                    or run["graph_sha256"] != schedule["graph_sha256"]
                    or run["input_json"] != schedule["inputs_json"]
                ):
                    raise ValidationError("The schedule occurrence refers to a different execution")
                used_runs.add(run_id)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValidationError(
            "The scheduled workflow history contains an invalid reference"
        ) from exc


def restore_schedule_row(name: str, row: dict[str, Any], values: dict[str, Any]) -> None:
    if name == SCHEDULES:
        values.update(
            name=row["name"],
            enabled=False,
            last_status="paused",
            last_message="Review the imported schedule before resuming it on this computer.",
        )
    elif name == OCCURRENCES:
        values["detail"] = row.get("detail")


def restore_schedule_pins(
    session: Session, rows: Rows, id_map: dict[str, str], digests: dict[str, str]
) -> None:
    """Rebind only record identities and content digests after their graphs have been restored."""
    for source in rows.get(SCHEDULES, ()):
        schedule = session.get(WorkflowSchedule, id_map[source["id"]])
        if schedule is None:
            raise ValidationError("The imported schedule is missing")
        graph = session.get(WorkflowGraphRecord, schedule.workflow_graph_record_id)
        if graph is None or graph.project_id != schedule.project_id:
            raise ValidationError("The imported schedule lost its saved graph")
        refs = [
            {**r, "id": id_map[r["id"]], "sha256": digests.get(r["sha256"], r["sha256"])}
            for r in source["inputs_json"].get("references", ())
        ]
        schedule.inputs_json = {"references": refs} if refs else {}
        schedule.inputs_sha256 = canonical_json_sha256(schedule.inputs_json)
        schedule.graph_sha256 = graph.graph_sha256
    for source in rows.get(OCCURRENCES, ()):
        occurrence = session.get(WorkflowScheduleOccurrence, id_map[source["id"]])
        schedule = session.get(WorkflowSchedule, id_map[source["schedule_id"]])
        if occurrence is None or schedule is None:
            raise ValidationError("The imported occurrence lost its schedule")
        occurrence.graph_sha256 = schedule.graph_sha256
        occurrence.inputs_sha256 = schedule.inputs_sha256
        if occurrence.workflow_run_id is not None:
            run = session.get(WorkflowRun, occurrence.workflow_run_id)
            if run is None or run.workflow_graph_record_id != schedule.workflow_graph_record_id:
                raise ValidationError("The imported occurrence lost its execution")
            run.input_json = dict(schedule.inputs_json)

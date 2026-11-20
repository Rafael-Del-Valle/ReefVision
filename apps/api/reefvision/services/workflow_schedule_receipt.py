"""Verify the terminal outcome of one local schedule slot for inspection and saved replay."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel
from pydantic import ValidationError as SchemaError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowRun,
    WorkflowSchedule,
    WorkflowScheduleOccurrence,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.workflow_provenance import build_workflow_run_provenance
from reefvision.storage.datasets import canonical_json_sha256

NODE = "workflow_schedule_receipt"


class SlotPin(BaseModel):
    occurrence_id: UUID
    scheduled_at: AwareDatetime


class ScheduleArtifactReference(BaseModel):
    artifact_id: UUID
    producer_node_run_id: UUID
    producer_port_id: str
    data_type: str
    payload_sha256: str


class SlotReceipt(BaseModel):
    schema_version: str = "workflow-schedule-receipt-0001"
    project_id: UUID
    schedule_id: UUID
    occurrence_id: UUID
    purpose: str
    scheduled_at: AwareDatetime
    dispatched_at: AwareDatetime
    missed_intervals: int
    workflow_graph_record_id: UUID
    graph_sha256: str
    inputs: dict[str, Any]
    inputs_sha256: str
    status: str
    detail: str | None
    workflow_run_id: UUID | None
    job_id: UUID | None
    workflow_provenance_sha256: str | None
    artifacts: list[ScheduleArtifactReference]


class VerifiedSlotReceipt(BaseModel):
    receipt: SlotReceipt
    receipt_sha256: str


def _utc(stamp: datetime) -> datetime:
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)


def schedule_receipt(session: Session, project: str, occurrence_id: str) -> VerifiedSlotReceipt:
    occurrence = session.get(WorkflowScheduleOccurrence, occurrence_id)
    if occurrence is None or occurrence.project_id != project:
        raise NotFoundError("Schedule occurrence not found in this project")
    schedule = session.get(WorkflowSchedule, occurrence.schedule_id)
    if schedule is None or schedule.project_id != project:
        raise ConflictError("The occurrence lost its project schedule")
    graph = session.get(WorkflowGraphRecord, schedule.workflow_graph_record_id)
    if (
        graph is None
        or graph.project_id != project
        or canonical_json_sha256(graph.graph_json) != graph.graph_sha256
        or graph.graph_sha256 != schedule.graph_sha256
        or schedule.graph_sha256 != occurrence.graph_sha256
        or canonical_json_sha256(schedule.inputs_json) != schedule.inputs_sha256
        or schedule.inputs_sha256 != occurrence.inputs_sha256
    ):
        raise ConflictError("The schedule graph or frozen inputs no longer match this occurrence")
    status, detail = occurrence.status, occurrence.detail
    job_id = None
    provenance_sha = None
    artifacts: list[ScheduleArtifactReference] = []
    if occurrence.workflow_run_id is not None:
        run = session.get(WorkflowRun, occurrence.workflow_run_id)
        if (
            run is None
            or run.project_id != project
            or run.workflow_graph_record_id != graph.id
            or run.input_json != schedule.inputs_json
        ):
            raise ConflictError("The occurrence lost its linked workflow execution")
        status, detail, job_id = run.status, run.error_message, run.job_id
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ConflictError("The receipt becomes available when the workflow finishes")
        provenance = build_workflow_run_provenance(session, run_id=run.id)
        provenance_sha = canonical_json_sha256(provenance)
        artifacts = [ScheduleArtifactReference.model_validate(a) for a in provenance["artifacts"]]
    elif status != "failed":
        raise ConflictError("The occurrence has no completed dispatch outcome")
    receipt = SlotReceipt.model_validate(
        {
            "project_id": project,
            "schedule_id": schedule.id,
            "occurrence_id": occurrence.id,
            "purpose": schedule.purpose,
            "scheduled_at": _utc(occurrence.scheduled_at),
            "dispatched_at": _utc(occurrence.created_at),
            "missed_intervals": occurrence.missed_intervals,
            "workflow_graph_record_id": graph.id,
            "graph_sha256": graph.graph_sha256,
            "inputs": schedule.inputs_json,
            "inputs_sha256": schedule.inputs_sha256,
            "status": status,
            "detail": detail,
            "workflow_run_id": occurrence.workflow_run_id,
            "job_id": job_id,
            "workflow_provenance_sha256": provenance_sha,
            "artifacts": artifacts,
        }
    )
    return VerifiedSlotReceipt(
        receipt=receipt, receipt_sha256=canonical_json_sha256(receipt.model_dump(mode="json"))
    )


def schedule_receipt_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type=NODE,
        display_name="Read scheduled workflow result",
        category="Data and evidence",
        description="Verify one completed schedule occurrence and its recorded artifacts.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="receipt", display_name="Schedule receipt", accepted_types=[NODE]
            )
        ],
        required_parameters=["occurrence_id", "scheduled_at"],
        optional_parameters={},
        executable=True,
        execution_state="executable",
        implementation_notes=[
            "A saved replay reads the identified UTC slot and its original outcome."
        ],
    )


def execute_schedule_receipt(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Schedule receipt requires its owning project")
    try:
        pin = SlotPin.model_validate(parameters)
    except SchemaError as exc:
        raise ValidationError(
            "Choose a schedule occurrence and its offset-bearing due time"
        ) from exc
    result = schedule_receipt(session, project_id, str(pin.occurrence_id))
    if result.receipt.scheduled_at != pin.scheduled_at:
        raise ConflictError("The pinned UTC slot does not match this occurrence")
    return [{"port_id": "receipt", "data_type": NODE, "payload": result.model_dump(mode="json")}]

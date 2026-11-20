"""Collect one authorized occurrence or read an immutable prior capture."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError as SchemaValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.workflow_execution import WorkflowArtifact, WorkflowNodeRun, WorkflowRun
from reefvision.db.models.workflow_schedule import WorkflowSchedule, WorkflowScheduleOccurrence
from reefvision.domain.errors import ValidationError
from reefvision.schemas.acquisition_source import (
    AcquisitionCaptureReceipt,
    AcquisitionDispatch,
    AcquisitionReceiptPin,
    AcquisitionSourcePin,
)
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.acquisition_sources import AcquisitionSourceService

ACQUISITION_CAPTURE_NODE = "acquisition_source_capture"
ACQUISITION_REPLAY_NODE = "acquisition_capture_replay"
ACQUISITION_RECEIPT_TYPE = "acquisition_capture_receipt"
_RUNTIME = {"__workflow_run_id", "__workflow_node_run_id"}


def _definition(
    node_type: str, name: str, description: str, parameters: list[str], notes: list[str]
) -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type=node_type,
        display_name=name,
        category="Data and evidence",
        description=description,
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="receipt",
                display_name="Acquisition receipt",
                accepted_types=[ACQUISITION_RECEIPT_TYPE],
            )
        ],
        required_parameters=parameters,
        optional_parameters={},
        implementation_notes=notes,
        execution_state="executable",
        executable=True,
    )


def acquisition_source_node() -> WorkflowNodeDefinitionResponse:
    return _definition(
        ACQUISITION_CAPTURE_NODE,
        "Capture from an acquisition source",
        "Collect one observation from a pinned local source during a scheduled occurrence.",
        ["source_id", "source_sha256"],
        [
            "New observations require a matching project acquisition schedule.",
            "A local camera also requires current explicit approval.",
            "Use the receipt replay node to reopen earlier evidence.",
        ],
    )


def acquisition_replay_node() -> WorkflowNodeDefinitionResponse:
    return _definition(
        ACQUISITION_REPLAY_NODE,
        "Replay a saved acquisition receipt",
        "Verify the original bytes and receipt from an earlier acquisition.",
        ["capture_id", "content_sha256"],
        ["Reading a saved receipt does not open the device or advance the source cursor."],
    )


def _check_project(project_id: str, inputs: dict[str, list[WorkflowArtifact]]) -> None:
    projects = inputs.get("project", [])
    if (
        len(projects) != 1
        or projects[0].data_type != "project_reference"
        or projects[0].payload_json.get("project_id") != project_id
    ):
        raise ValidationError("Acquisition requires the current project reference")


def _dispatch(
    session: Session, project_id: str, pins: AcquisitionSourcePin, parameters: dict[str, Any]
) -> tuple[str, AcquisitionDispatch]:
    error = (
        "A new acquisition requires its matching scheduled occurrence. "
        "Use Capture once or replay a saved receipt."
    )
    run = session.get(WorkflowRun, parameters.get("__workflow_run_id"))
    node = session.get(WorkflowNodeRun, parameters.get("__workflow_node_run_id"))
    if (
        run is None
        or node is None
        or run.project_id != project_id
        or run.status != "running"
        or node.status != "running"
        or node.node_type != ACQUISITION_CAPTURE_NODE
        or node.workflow_run_id != run.id
        or node.parameters_json != pins.model_dump(mode="json")
    ):
        raise ValidationError(error)
    match = session.execute(
        select(WorkflowScheduleOccurrence, WorkflowSchedule)
        .join(WorkflowSchedule, WorkflowScheduleOccurrence.schedule_id == WorkflowSchedule.id)
        .where(WorkflowScheduleOccurrence.workflow_run_id == run.id)
    ).one_or_none()
    if match is None:
        raise ValidationError(error)
    occurrence, schedule = match
    if (
        occurrence.project_id != project_id
        or schedule.project_id != project_id
        or schedule.purpose != "acquisition"
        or run.workflow_graph_record_id != schedule.workflow_graph_record_id
        or run.graph_sha256 != occurrence.graph_sha256
        or run.graph_sha256 != schedule.graph_sha256
        or occurrence.inputs_sha256 != schedule.inputs_sha256
        or run.input_json != schedule.inputs_json
        or not any(
            ref.get("node_id") == node.node_id
            and ref.get("kind") == ACQUISITION_CAPTURE_NODE
            and ref.get("id") == str(pins.source_id)
            and ref.get("sha256") == pins.source_sha256
            for ref in schedule.inputs_json.get("references", [])
        )
    ):
        raise ValidationError(error)
    return f"schedule:{occurrence.id}:{node.node_id}", AcquisitionDispatch(
        kind="schedule",
        occurrence_id=UUID(occurrence.id),
        workflow_run_id=UUID(run.id),
        node_id=node.node_id,
    )


def _artifact(receipt: AcquisitionCaptureReceipt) -> list[dict[str, Any]]:
    return [
        {
            "port_id": "receipt",
            "data_type": ACQUISITION_RECEIPT_TYPE,
            "payload": receipt.model_dump(mode="json"),
        }
    ]


def execute_acquisition_source(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    _check_project(project_id, inputs)
    try:
        pins = AcquisitionSourcePin.model_validate(
            {key: value for key, value in parameters.items() if key not in _RUNTIME}
        )
    except SchemaValidationError as exc:
        raise ValidationError(
            "Pin an acquisition source UUID and checksum before scheduling"
        ) from exc
    key, dispatch = _dispatch(session, project_id, pins, parameters)
    return _artifact(
        AcquisitionSourceService(session, settings).capture(
            project_id, str(pins.source_id), pins.source_sha256, key, dispatch
        )
    )


def execute_acquisition_replay(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    _check_project(project_id, inputs)
    try:
        pins = AcquisitionReceiptPin.model_validate(
            {key: value for key, value in parameters.items() if key not in _RUNTIME}
        )
    except SchemaValidationError as exc:
        raise ValidationError(
            "Pin an acquisition receipt UUID and checksum before replaying"
        ) from exc
    return _artifact(
        AcquisitionSourceService(session, settings).get_capture(
            project_id, str(pins.capture_id), expected_sha256=pins.content_sha256
        )
    )

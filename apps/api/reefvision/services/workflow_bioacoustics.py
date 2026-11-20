"""Workflow Builder reads the same frozen bioacoustic evidence as the workspace."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError as InvalidPin
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.workflow_execution import WorkflowArtifact
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.bioacoustics import AudioSchema, AudioSHA
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.bioacoustics import BioacousticsService

NODE = "bioacoustic_report"


class AudioReportPin(AudioSchema):
    report_id: UUID
    report_sha256: AudioSHA


def audio_report_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type=NODE,
        display_name="Read reviewed bioacoustic report",
        category="Scientific analysis",
        description="Replay a frozen sample report with its local review and clock evidence.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="report", display_name="Bioacoustic report", accepted_types=[NODE]
            )
        ],
        required_parameters=["report_id", "report_sha256"],
        optional_parameters={},
        executable=True,
        execution_state="executable",
        implementation_notes=[
            "Proposed, uncertain, and conflicting intervals remain visible as withheld."
        ],
    )


def execute_audio_report(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("A bioacoustic report requires its owning project")
    try:
        pin = AudioReportPin.model_validate(
            {
                key: value
                for key, value in parameters.items()
                if key not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
    except InvalidPin as exc:
        raise ValidationError("Choose a saved bioacoustic report and its checksum") from exc
    result = BioacousticsService(session, settings).report(project_id, str(pin.report_id))
    if result.report_sha256 != pin.report_sha256:
        raise ConflictError("The pinned bioacoustic report checksum differs from the frozen report")
    return [{"port_id": "report", "data_type": NODE, "payload": result.model_dump(mode="json")}]

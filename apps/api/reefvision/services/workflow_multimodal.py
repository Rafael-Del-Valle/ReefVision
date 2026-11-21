"""Run the same reviewed survey calculation from a pinned Workflow Builder graph."""

from typing import Any

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services import workflow_runtime_adapters as runtime
from reefvision.services.multimodal import find_study, replay

NODE = "multimodal_study_replay"


def execute(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    if runtime._single_payload(inputs, "project").get("project_id") != project_id:
        raise ValidationError("Choose the current survey project")
    study = find_study(session, project_id, str(parameters.get("study_id") or ""))
    result = replay(session, settings, project_id, study, str(parameters.get("study_sha256") or ""))
    return [
        {
            "port_id": "report",
            "data_type": "multimodal_study_report",
            "payload": {"project_id": project_id, **result},
        }
    ]


def register() -> WorkflowNodeDefinitionResponse:
    runtime.RUNTIME_ADAPTER_NODE_TYPES.add(NODE)
    runtime._ADAPTERS[NODE] = execute
    return WorkflowNodeDefinitionResponse(
        node_type=NODE,
        display_name="Replay multimodal survey",
        category="Scientific analysis",
        description="Recompute a pinned acoustic and optical survey with its alignment checks.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="report",
                display_name="Survey comparison",
                accepted_types=["multimodal_study_report"],
            )
        ],
        required_parameters=["study_id", "study_sha256"],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "Research → Multimodal analysis saves a pinned graph for this survey."
        ],
    )

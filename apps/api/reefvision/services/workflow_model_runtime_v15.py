"""A saved model choice verifies the same receipt used by Model Hub inference."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services import workflow_runtime_adapters as adapters
from reefvision.services.model_runtime import ModelRuntimeService, pinned_job_settings

NODE_TYPE = "reviewed_model_runtime"


def extend_model_runtime_registry(
    base: Callable[[], dict[str, WorkflowNodeDefinitionResponse]],
) -> Callable[[], dict[str, WorkflowNodeDefinitionResponse]]:
    def registry() -> dict[str, WorkflowNodeDefinitionResponse]:
        nodes = dict(base())
        for name in (
            "detection_inference",
            "segmentation_inference",
            "pose_inference",
            "video_tracking",
        ):
            node = nodes[name].model_copy(deep=True)
            for port in node.input_ports:
                if port.port_id == "model":
                    port.accepted_types.append("reviewed_model_reference")
            nodes[name] = node
        nodes[NODE_TYPE] = WorkflowNodeDefinitionResponse(
            node_type=NODE_TYPE,
            display_name="Reviewed model runtime",
            category="sources",
            description="Load a reviewed Model Hub configuration and verify its local checkpoint.",
            input_ports=[
                WorkflowPortDefinition(
                    port_id="project", display_name="Project", accepted_types=["project_reference"]
                )
            ],
            output_ports=[
                WorkflowPortDefinition(
                    port_id="model",
                    display_name="Reviewed model",
                    accepted_types=["reviewed_model_reference"],
                    required=False,
                    multiple=True,
                )
            ],
            required_parameters=["selection_id", "selection_sha256"],
            optional_parameters={},
            execution_state="executable_source",
            executable=True,
            implementation_notes=[
                "The selected device, confidence and IoU apply to each connected inference step."
            ],
        )
        return nodes

    return registry


def execute_reviewed_model(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    project = adapters._single_payload(inputs, "project")
    if project.get("project_id") != project_id:
        raise ValidationError("Reviewed model requires the current project")
    service = ModelRuntimeService(session, settings)
    selection_id = str(parameters.get("selection_id") or "")
    saved = service.get(project_id, selection_id)
    pinned = service.verify(
        project_id,
        selection_id,
        model_id=str(saved.model_id),
        digest=str(parameters.get("selection_sha256") or ""),
    )
    return [
        {
            "port_id": "model",
            "data_type": "reviewed_model_reference",
            "payload": {
                "project_id": project_id,
                "model_id": str(pinned.model_id),
                "model_sha256": pinned.snapshot.checkpoint_sha256,
                "purpose": pinned.snapshot.purpose,
                "task": pinned.snapshot.task,
                "provider_name": pinned.snapshot.provider_id,
                "runtime_id": pinned.snapshot.runtime_id,
                **pinned_job_settings(pinned),
            },
        }
    ]


def register_model_runtime_adapter() -> None:
    adapters.RUNTIME_ADAPTER_NODE_TYPES.add(NODE_TYPE)
    adapters._ADAPTERS[NODE_TYPE] = execute_reviewed_model

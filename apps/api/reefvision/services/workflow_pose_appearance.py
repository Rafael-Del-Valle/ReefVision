"""Workflow Builder replay of an immutable appearance comparison."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact, WorkflowRun
from reefvision.domain.errors import ValidationError, WorkflowExecutionCancelled
from reefvision.jobs.pose_appearance import replay
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services import workflow_runtime_adapters as runtime
from reefvision.services.pose_appearance import study_row

NODE = "reefpose_appearance_replay"


def execute(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    project = runtime._single_payload(inputs, "project")
    if project.get("project_id") != project_id:
        raise ValidationError("Choose the current project for appearance replay")
    row = study_row(session, project_id, str(parameters.get("study_id") or ""))
    if row.content_sha256 != parameters.get("study_sha256"):
        raise ValidationError("The selected appearance study digest differs from the saved graph")
    run_id = parameters.get("__workflow_run_id")

    def check() -> None:
        if run_id and session.scalar(
            select(WorkflowRun.status).where(WorkflowRun.id == run_id)
        ) in {"cancel_requested", "cancelled"}:
            raise WorkflowExecutionCancelled("Saved appearance replay was cancelled")

    output = replay(session, settings, project_id, row, check)
    return [
        {
            "port_id": "report",
            "data_type": "pose_appearance_report",
            "payload": {
                "project_id": project_id,
                **output,
                "download_url": f"/projects/{project_id}/pose-appearance/studies/{row.id}/export",
            },
        }
    ]


def register_appearance_node() -> WorkflowNodeDefinitionResponse:
    runtime.RUNTIME_ADAPTER_NODE_TYPES.add(NODE)
    runtime._ADAPTERS[NODE] = execute
    return WorkflowNodeDefinitionResponse(
        node_type=NODE,
        display_name="Replay ReefPose appearance study",
        category="Pose",
        description="Recompute a frozen appearance study and its held-out scores.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="report",
                display_name="Verified appearance report",
                accepted_types=["pose_appearance_report"],
            )
        ],
        required_parameters=["study_id", "study_sha256"],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=["A researcher can save a pinned replay graph from Identity review."],
    )

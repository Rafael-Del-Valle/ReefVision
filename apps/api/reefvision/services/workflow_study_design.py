"""Executable node for an exact project study design revision."""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError as RequestValidationError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.workflow_execution import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.study_design import StudyDesignReplay
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.study_design import StudyDesignService


def reviewed_study_design_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type="reviewed_study_design",
        display_name="Reviewed study design",
        category="Scientific analysis",
        description="Replay a frozen two-visit design, reviewed roster and bound growth evidence.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="report",
                display_name="Study design report",
                accepted_types=["study_design_report"],
            )
        ],
        required_parameters=list(StudyDesignReplay.model_fields),
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "The revision UUID and digest are pinned in the saved workflow.",
            "Checks the current reviewed roster and calibrated sources against the frozen design.",
        ],
    )


def execute_reviewed_study_design(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: Mapping[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Study design requires the current project reference")
    try:
        request = StudyDesignReplay.model_validate(
            {
                key: value
                for key, value in parameters.items()
                if key not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
    except RequestValidationError as exc:
        raise ValidationError("Invalid study design reference: " + exc.errors()[0]["msg"]) from exc
    report = StudyDesignService(session).replay(
        project_id, str(request.design_revision_id), request.design_sha256
    )
    return [
        {
            "port_id": "report",
            "data_type": "study_design_report",
            "payload": report.model_dump(mode="json"),
        }
    ]

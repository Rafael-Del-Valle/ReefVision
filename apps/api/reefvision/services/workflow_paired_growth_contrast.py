"""Use the standalone frozen paired growth calculation from saved workflow graphs."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError as RequestValidationError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models.workflow_execution import WorkflowArtifact
from reefvision.domain.errors import ValidationError
from reefvision.schemas.paired_growth_contrast import PairedGrowthContrastRequest
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.paired_growth_contrast import paired_growth_contrast


def paired_growth_contrast_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type="paired_growth_contrast",
        display_name="Paired growth contrast",
        category="Scientific analysis",
        description="Compare two planned UTC visits in a frozen, reviewed growth analysis.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="contrast",
                display_name="Paired growth contrast",
                accepted_types=["paired_growth_contrast"],
            )
        ],
        required_parameters=["analysis_id", *PairedGrowthContrastRequest.model_fields],
        optional_parameters={},
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "The growth source digest and declared design are pinned in the graph revision.",
            "Only complete declared units enter the contrast, with equal weighting.",
        ],
    )


def execute_paired_growth_contrast(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: Mapping[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Paired growth requires the current project reference")
    analysis_id = parameters.get("analysis_id")
    try:
        analysis_id = str(UUID(analysis_id)) if isinstance(analysis_id, str) else None
    except ValueError:
        analysis_id = None
    if analysis_id is None:
        raise ValidationError("A saved reviewed growth analysis UUID is required")
    design = {
        key: value
        for key, value in parameters.items()
        if key not in {"analysis_id", "__workflow_run_id", "__workflow_node_run_id"}
    }
    try:
        request = PairedGrowthContrastRequest.model_validate(design)
    except RequestValidationError as exc:
        raise ValidationError("Invalid paired growth design: " + exc.errors()[0]["msg"]) from exc
    report = paired_growth_contrast(session, project_id, analysis_id, request)
    return [
        {
            "port_id": "contrast",
            "data_type": "paired_growth_contrast",
            "payload": report.model_dump(mode="json"),
        }
    ]

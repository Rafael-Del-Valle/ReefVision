"""Workflow Builder access to the persisted acquisition QC service."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.domain.errors import ValidationError, WorkflowExecutionCancelled
from reefvision.schemas.quality_control import (
    AcquisitionQualityThresholds,
    QualityControlRunCreateRequest,
    QualityControlThresholdConfig,
)
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.quality_control import QualityControlService


class AcquisitionWorkflowParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version_id: UUID | None = None
    thresholds: AcquisitionQualityThresholds = Field(default_factory=AcquisitionQualityThresholds)


def acquisition_quality_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type="image_acquisition_quality",
        display_name="Check Image Acquisition Quality",
        category="Scientific analysis",
        description="Record camera, calibration, and pixel diagnostics for scientist review.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project",
                display_name="Project",
                accepted_types=["project_reference"],
            ),
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="quality",
                display_name="Acquisition QC result",
                accepted_types=["acquisition_quality_result"],
                multiple=True,
            ),
        ],
        required_parameters=[],
        optional_parameters={
            "dataset_version_id": None,
            "thresholds": AcquisitionQualityThresholds().model_dump(mode="json"),
        },
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "Leave the dataset version empty to inspect the current project.",
            "Open the saved run in Quality Control to inspect source images and findings.",
            "Findings do not exclude evidence from any dataset or scientific analysis.",
        ],
    )


def execute_acquisition_quality(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Acquisition quality requires the current project")
    context = {
        key: parameters.get(f"__{key}") for key in ("workflow_run_id", "workflow_node_run_id")
    }
    if any(not isinstance(value, str) or not value for value in context.values()):
        raise ValidationError("Acquisition quality requires a persisted workflow run")
    try:
        request = AcquisitionWorkflowParameters.model_validate(
            {
                key: value
                for key, value in parameters.items()
                if key not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
    except ValueError as exc:
        raise ValidationError(f"Invalid acquisition QC parameters: {exc}") from exc
    service = QualityControlService(session, settings)
    run = service.create_workflow_acquisition_run(
        project_id,
        str(request.dataset_version_id) if request.dataset_version_id else None,
        QualityControlRunCreateRequest(
            rule_categories=["acquisition"],
            thresholds=QualityControlThresholdConfig(acquisition=request.thresholds),
        ),
        {key: str(value) for key, value in context.items()},
    )
    if run.status in {"queued", "running"}:
        run = service.execute_run(run.id)
    if run.status == "cancelled":
        raise WorkflowExecutionCancelled("Acquisition QC was cancelled")
    if run.status != "succeeded":
        raise ValidationError(run.error_message or "Acquisition QC did not complete")
    return [
        {
            "port_id": "quality",
            "data_type": "acquisition_quality_result",
            "payload": {
                "project_id": project_id,
                "dataset_version_id": run.dataset_version_id,
                "quality_control_run_id": run.id,
                "report": run.summary_json["acquisition"],
            },
        }
    ]

"""Use the same scoped plugin measurement from a typed saved graph."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError as SchemaError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, ScientificRecord, WorkflowArtifact
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.plugins import PluginMeasurementPin
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.plugin_measurements import PluginMeasurementService
from reefvision.services.scientific_data import ScientificDataService
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.plugins import PluginStorage

NODE = "plugin_image_measurement"
MEASUREMENT_REVIEW = "measurement_review_gate"


def measurement_review_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type=MEASUREMENT_REVIEW,
        display_name="Review derived measurements",
        category="human_review",
        description="Inspect saved measurements and acknowledge their use in this run.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="measurement",
                display_name="Measurements",
                accepted_types=["scientific_record_collection"],
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="reviewed",
                display_name="Acknowledged measurements",
                accepted_types=["scientific_record_collection"],
                required=False,
                multiple=True,
            )
        ],
        required_parameters=[],
        optional_parameters={},
        execution_state="pausable_review_gate",
        executable=True,
        implementation_notes=[
            "Records the review decision for this run and preserves the original scientific QC."
        ],
    )


def measurement_review_context(
    session: Session, project_id: str, artifacts: list[WorkflowArtifact]
) -> dict[str, Any]:
    if len(artifacts) != 1 or artifacts[0].data_type != "scientific_record_collection":
        raise ValidationError("Measurement review requires one collection of scientific records.")
    artifact = artifacts[0]
    payload = artifact.payload_json
    if (
        payload.get("project_id") != project_id
        or canonical_json_sha256(payload) != artifact.payload_sha256
    ):
        raise ConflictError(
            "The input measurement artifact differs from its saved project or checksum."
        )
    identifiers = payload.get("record_ids")
    digests = payload.get("content_sha256")
    if (
        not isinstance(identifiers, list)
        or not 1 <= len(identifiers) <= 500
        or not isinstance(digests, dict)
    ):
        raise ValidationError("Measurement review requires saved record IDs and content checksums.")
    science = ScientificDataService(session)
    for identifier in identifiers:
        if not isinstance(identifier, str):
            raise ValidationError("Measurement review found an invalid scientific record ID.")
        row = session.get(ScientificRecord, identifier)
        if (
            row is None
            or row.project_id != project_id
            or science.response(row).content_sha256 != digests.get(identifier)
        ):
            raise ConflictError("A scientific record differs from the reviewed collection.")
    return {"record_ids": identifiers, "content_sha256": digests}


def plugin_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type=NODE,
        display_name="Local plugin image measurement",
        category="Scientific analysis",
        description="Measure a pinned original with a selected, enabled local plugin version.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="measurement",
                display_name="Derived measurement",
                accepted_types=["scientific_record_collection"],
                required=False,
                multiple=True,
            )
        ],
        required_parameters=list(PluginMeasurementPin.model_fields),
        optional_parameters={},
        execution_state="executable_analysis",
        executable=True,
        implementation_notes=[
            "Saves an unassessed derived record with original image and package checksums."
        ],
    )


def parse_pin(parameters: dict[str, Any]) -> PluginMeasurementPin:
    try:
        return PluginMeasurementPin.model_validate(
            {
                k: v
                for k, v in parameters.items()
                if k not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
    except SchemaError as exc:
        raise ValidationError(
            "Choose a plugin version and an original image with valid SHA-256 pins."
        ) from exc


def plugin_plan_issue(
    session: Session, settings: Settings | None, project_id: str, parameters: dict[str, Any]
) -> str | None:
    if settings is None:
        return "Open this graph in the profile that contains the pinned plugin."
    try:
        pin = parse_pin(parameters)
        PluginStorage(settings).enabled_module(pin.plugin_record_id, pin.package_sha256)
        image = session.get(ImageAsset, str(pin.image_id))
        if image is None or image.project_id != project_id or image.sha256 != pin.image_sha256:
            return "Choose the pinned original image from this project."
    except (ConflictError, NotFoundError, ValidationError) as exc:
        return str(exc)
    return None


def execute_plugin_measurement(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    project = inputs.get("project", [])
    if (
        len(project) != 1
        or project[0].data_type != "project_reference"
        or project[0].payload_json.get("project_id") != project_id
    ):
        raise ValidationError("The plugin measurement requires the current project reference.")
    pin = parse_pin(parameters)
    result = PluginMeasurementService(session, settings).measure(UUID(project_id), pin)
    record_id = str(result.id)
    return [
        {
            "port_id": "measurement",
            "data_type": "scientific_record_collection",
            "payload": {
                "project_id": project_id,
                "record_ids": [record_id],
                "content_sha256": {record_id: result.content_sha256},
                "plugin": result.provenance.processing_parameters,
                "quantity": result.variable,
                "value": result.value,
                "unit": result.unit,
                "qc": result.qc,
            },
        }
    ]

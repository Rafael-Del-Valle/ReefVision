"""Workflow adapters for independent reference freezing and scoring."""

from typing import Any

from pydantic import ValidationError as ContractError
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, PoseIdentityAssociationRun, WorkflowArtifact
from reefvision.domain.errors import ValidationError, WorkflowExecutionCancelled
from reefvision.jobs.reefpose_validation import (
    completed_report,
    process_reefpose_validation_job,
    submit_validation,
)
from reefvision.schemas.reefpose_validation import FreezeReferenceRequest, ValidationRequest
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services import workflow_runtime_adapters as runtime
from reefvision.services.reefpose_validation import ReferenceService


def reference_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    del settings, inputs
    service = ReferenceService(session)
    try:
        if parameters.get("manifest"):
            if parameters.get("manifest_sha256"):
                raise ValidationError("Use a manifest hash only when loading a frozen reference")
            row = service.freeze(
                project_id, FreezeReferenceRequest.model_validate(parameters["manifest"])
            )
        else:
            row = service.get(project_id, str(parameters.get("reference_id") or ""))
    except ContractError as exc:
        raise ValidationError(f"Invalid scientific reference configuration: {exc}") from exc
    expected = parameters.get("manifest_sha256")
    if expected and expected != row.manifest_sha256:
        raise ValidationError("Workflow reference hash does not match")
    return [
        {
            "port_id": "reference",
            "data_type": "reefpose_reference",
            "payload": {
                "project_id": project_id,
                "reference_id": row.id,
                "manifest_sha256": row.manifest_sha256,
            },
        }
    ]


def validation_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    reference = runtime._single_payload(inputs, "reference")
    row = ReferenceService(session).get(project_id, str(reference.get("reference_id") or ""))
    if reference.get("manifest_sha256") != row.manifest_sha256:
        raise ValidationError("Workflow reference hash does not match")
    sources: dict[str, str] = {}
    zero_detection_jobs: dict[str, str] = {}
    for artifact in inputs.get("tracks", []):
        payload = artifact.payload_json
        run = session.get(PoseIdentityAssociationRun, str(payload.get("run_id") or ""))
        if (
            run is None
            or run.project_id != project_id
            or run.input_manifest_sha256 != payload.get("input_manifest_sha256")
            or run.video_id != payload.get("video_id")
            or run.video_id in sources
        ):
            raise ValidationError("Workflow identity artifact is stale, duplicated or incompatible")
        sources[run.video_id] = run.id
    for artifact in inputs.get("zero_detections", []):
        payload = artifact.payload_json
        video_id = str(payload.get("video_id") or "")
        job_id = str(payload.get("tracking_job_id") or "")
        if (
            not video_id
            or not job_id
            or video_id in sources
            or video_id in zero_detection_jobs
            or payload.get("project_id") != project_id
            or payload.get("count") != 0
        ):
            raise ValidationError("Workflow zero-detection artifact is invalid or duplicated")
        zero_detection_jobs[video_id] = job_id
    try:
        if parameters.get("split") == "test" and parameters.get("configurations") == [{}]:
            raise ValidationError("Clear the development configuration grid for held-out testing")
        request = ValidationRequest.model_validate(
            {
                key: value
                for key, value in {
                    **parameters,
                    "reference_id": row.id,
                    "source_runs": sources,
                    "zero_detection_jobs": zero_detection_jobs,
                }.items()
                if not key.startswith("__")
            }
        )
    except ContractError as exc:
        raise ValidationError(f"Invalid scientific scoring configuration: {exc}") from exc
    context = {
        "workflow_run_id": str(parameters.get("__workflow_run_id") or ""),
        "workflow_node_run_id": str(parameters.get("__workflow_node_run_id") or ""),
    }
    job = submit_validation(session, settings, project_id, request, workflow_context=context)
    job_id = job.id
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    process_reefpose_validation_job(settings, factory, job_id)
    session.expire_all()
    finished = session.get(Job, job_id)
    if finished is not None and finished.status == "cancelled":
        raise WorkflowExecutionCancelled("Scientific validation was cancelled")
    if finished is None or finished.status != "succeeded":
        raise ValidationError(
            f"Scientific validation failed: {finished.error_message if finished else 'missing job'}"
        )
    report = completed_report(session, project_id, job_id)
    return [
        {
            "port_id": "report",
            "data_type": "reefpose_validation_report",
            "payload": {
                "project_id": project_id,
                "job_id": job_id,
                "reference_id": row.id,
                "result_sha256": report["result_sha256"],
                "input_sha256": report["input_sha256"],
                "split": report["split"],
                "data_kind": report["data_kind"],
                "export_path": f"/projects/{project_id}/reefpose-validations/{job_id}/export",
            },
        }
    ]


def register_reefpose_validation_nodes() -> dict[str, WorkflowNodeDefinitionResponse]:
    adapters = {
        "reefpose_reference_source": reference_adapter,
        "reefpose_scientific_validation": validation_adapter,
    }
    runtime.RUNTIME_ADAPTER_NODE_TYPES.update(adapters)
    runtime._ADAPTERS.update(adapters)
    return {
        "reefpose_reference_source": WorkflowNodeDefinitionResponse(
            node_type="reefpose_reference_source",
            display_name="Independent ReefPose Reference",
            category="Scientific analysis",
            description="Freeze a manifest or load a frozen revision.",
            input_ports=[],
            output_ports=[
                WorkflowPortDefinition(
                    port_id="reference",
                    display_name="Frozen reference",
                    accepted_types=["reefpose_reference"],
                )
            ],
            required_parameters=[],
            optional_parameters={
                "reference_id": "",
                "manifest_sha256": "",
                "manifest": None,
            },
            execution_state="executable",
            executable=True,
            implementation_notes=[],
        ),
        "reefpose_scientific_validation": WorkflowNodeDefinitionResponse(
            node_type="reefpose_scientific_validation",
            display_name="Validate ReefPose Scientifically",
            category="Scientific analysis",
            description="Score original predictions against independent references.",
            input_ports=[
                WorkflowPortDefinition(
                    port_id="reference",
                    display_name="Frozen reference",
                    accepted_types=["reefpose_reference"],
                ),
                WorkflowPortDefinition(
                    port_id="tracks",
                    display_name="Original identity runs",
                    accepted_types=["pose_identity_tracks"],
                    multiple=True,
                    required=False,
                ),
                WorkflowPortDefinition(
                    port_id="zero_detections",
                    display_name="Zero-detection pose outputs",
                    accepted_types=["pose_tracks"],
                    multiple=True,
                    required=False,
                ),
            ],
            output_ports=[
                WorkflowPortDefinition(
                    port_id="report",
                    display_name="Validation report",
                    accepted_types=["reefpose_validation_report"],
                )
            ],
            required_parameters=["rater_id"],
            optional_parameters={
                "split": "development",
                "configurations": [{}],
                "development_job_id": None,
                "bootstrap_seed": 20261112,
            },
            execution_state="executable",
            executable=True,
            implementation_notes=[],
        ),
    }

"""Workflow nodes that share the standalone temporal ReefPose contracts."""

from __future__ import annotations

from functools import partial
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, TemporalReefPoseRun, WorkflowArtifact
from reefvision.domain.errors import ConflictError, ValidationError, WorkflowExecutionCancelled
from reefvision.jobs.temporal_reefpose import process_temporal_reefpose_job
from reefvision.schemas.temporal_reefpose import (
    TEMPORAL_RUN_ADAPTER,
    TemporalDatasetCreate,
    TemporalRunCreate,
)
from reefvision.schemas.workflow_graphs import (
    WorkflowDataType,
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.temporal_reefpose import TEMPORAL_JOB, TemporalReefPoseService
from reefvision.services.temporal_reefpose_sources import source_model

NodeKind = Literal["dataset", "training", "inference", "evaluation"]
OUTPUTS: dict[NodeKind, tuple[str, WorkflowDataType]] = {
    "dataset": ("dataset", "temporal_reefpose_dataset"),
    "training": ("model", "temporal_reefpose_model"),
    "inference": ("predictions", "temporal_reefpose_predictions"),
    "evaluation": ("report", "temporal_reefpose_evaluation"),
}


def _connected(
    project_id: str, inputs: dict[str, list[WorkflowArtifact]], port: str
) -> dict[str, Any] | None:
    artifacts = inputs.get(port, [])
    if not artifacts:
        return None
    if len(artifacts) != 1 or artifacts[0].payload_json.get("project_id") != project_id:
        raise ValidationError(f"Temporal workflow port {port} requires one project-scoped input")
    return artifacts[0].payload_json


def _add_connected(
    configuration: dict[str, Any], field: str, payload: dict[str, Any] | None
) -> None:
    if payload is None:
        return
    value = payload.get(field)
    if not value or configuration.get(field) not in (None, "", value):
        raise ValidationError(f"Configured {field} conflicts with the connected artifact")
    configuration[field] = value


def _calculate(
    session: Session,
    settings: Settings,
    service: TemporalReefPoseService,
    project_id: str,
    configuration: TemporalRunCreate,
    workflow_id: str,
    workflow_node_id: str,
) -> TemporalReefPoseRun:
    existing = session.scalar(
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.job_type == TEMPORAL_JOB,
            Job.request_json["workflow_node_run_id"].as_string() == workflow_node_id,
        )
        .order_by(Job.created_at.desc(), Job.id)
        .limit(1)
    )
    if existing is None:
        row = service.submit(
            project_id,
            configuration,
            workflow_run_id=workflow_id,
            workflow_node_run_id=workflow_node_id,
        )
        job_id = row.job_id
        run_id = row.id
    else:
        job_id = existing.id
        run_id = existing.request_json["temporal_run_id"]
        row = service.run(project_id, run_id)
        if row.configuration_json != configuration.model_dump(mode="json"):
            raise ConflictError("Recovered temporal workflow configuration changed")
        if existing.status in {"failed", "cancelled"}:
            existing.status = "queued"
            existing.completed_at = None
            existing.started_at = None
            existing.error_message = None
    if job_id is None:
        raise ValidationError("Temporal workflow child job is unavailable")
    session.commit()
    process_temporal_reefpose_job(
        settings, sessionmaker(bind=session.get_bind(), expire_on_commit=False), job_id
    )
    session.expire_all()
    job = session.get(Job, job_id)
    if job is not None and job.status in {"cancel_requested", "cancelled"}:
        raise WorkflowExecutionCancelled("Temporal ReefPose job was cancelled")
    if job is None or job.status != "succeeded":
        raise ValidationError(
            job.error_message
            if job and job.error_message
            else "Temporal child job did not complete"
        )
    return service.run(project_id, run_id)


def execute(
    kind: NodeKind,
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    _connected(project_id, inputs, "project")
    service = TemporalReefPoseService(session)
    workflow_id = str(parameters.get("__workflow_run_id") or "")
    workflow_node_id = str(parameters.get("__workflow_node_run_id") or "")
    configuration = {
        key: value
        for key, value in parameters.items()
        if key not in {"__workflow_run_id", "__workflow_node_run_id"}
    }
    result: dict[str, Any] = {"project_id": project_id}
    try:
        if kind == "dataset":
            saved = configuration.pop("saved_dataset_id", None)
            if saved:
                if configuration.get("sources"):
                    raise ValidationError("Choose a frozen dataset or a new source selection")
                dataset = service.dataset(project_id, str(saved))
            else:
                dataset = service.freeze(
                    project_id, TemporalDatasetCreate.model_validate(configuration)
                )
            result.update(
                dataset_id=dataset.id,
                manifest_sha256=dataset.manifest_sha256,
                schema_hash=dataset.manifest_json["schema"]["content_hash"],
            )
        else:
            saved_run_id = configuration.pop("saved_run_id", None)
            if saved_run_id:
                if inputs.get("dataset") or inputs.get("model") or inputs.get("poses"):
                    raise ValidationError("Saved temporal runs replay their frozen inputs")
                row = service.run(project_id, str(saved_run_id))
                if row.kind != kind or row.result_json is None:
                    raise ValidationError("Select a completed temporal run for this operation")
                if service.source_stale(row):
                    raise ConflictError("Saved pose input changed. Use a fresh refinement run.")
            else:
                dataset_input = _connected(project_id, inputs, "dataset")
                _add_connected(configuration, "dataset_id", dataset_input)
                if dataset_input is not None:
                    dataset = service.dataset(project_id, configuration["dataset_id"])
                    if dataset.manifest_sha256 != dataset_input.get("manifest_sha256"):
                        raise ConflictError("Connected temporal dataset checksum changed")
                model = _connected(project_id, inputs, "model")
                _add_connected(configuration, "temporal_model_id", model)
                if model is not None:
                    checkpoint = source_model(
                        session, project_id, configuration["temporal_model_id"]
                    )
                    if checkpoint.sha256 != model.get("checkpoint_sha256"):
                        raise ConflictError("Connected temporal checkpoint checksum changed")
                poses = _connected(project_id, inputs, "poses")
                if poses:
                    ids = poses.get("track_ids") or []
                    source = dict(configuration.get("source") or {})
                    selected = source.get("frame_track_id")
                    if (selected and selected not in ids) or (not selected and len(ids) != 1):
                        raise ValidationError(
                            "Choose one frame track from the connected video pose output"
                        )
                    source["frame_track_id"] = selected or ids[0]
                    configuration["source"] = source
                payload = TEMPORAL_RUN_ADAPTER.validate_python({**configuration, "kind": kind})
                if not workflow_id or not workflow_node_id:
                    raise ValidationError("Temporal execution requires a saved workflow run")
                row = _calculate(
                    session, settings, service, project_id, payload, workflow_id, workflow_node_id
                )
            result.update(
                run_id=row.id,
                job_id=row.job_id,
                dataset_id=row.dataset_id,
                input_manifest_sha256=row.input_manifest_sha256,
                identity_run_id=row.identity_run_id,
                review_revision=row.review_revision,
                **(row.result_json or {}),
            )
            if kind == "training":
                result["temporal_model_id"] = result["model_id"]
    except ValueError as exc:
        raise ValidationError(f"Invalid temporal workflow parameters: {exc}") from exc
    port, data_type = OUTPUTS[kind]
    return [{"port_id": port, "data_type": data_type, "payload": result}]


def register_temporal_reefpose_nodes() -> dict[str, WorkflowNodeDefinitionResponse]:
    from reefvision.services import workflow_runtime_adapters as runtime

    project = WorkflowPortDefinition(
        port_id="project",
        display_name="Project",
        accepted_types=["project_reference"],
        required=False,
    )
    dataset = WorkflowPortDefinition(
        port_id="dataset",
        display_name="Frozen sequence dataset",
        accepted_types=["temporal_reefpose_dataset"],
        required=False,
    )
    model = WorkflowPortDefinition(
        port_id="model",
        display_name="Temporal checkpoint",
        accepted_types=["temporal_reefpose_model"],
        required=False,
    )
    poses = WorkflowPortDefinition(
        port_id="poses",
        display_name="Native frame pose predictions",
        accepted_types=["pose_tracks"],
        required=False,
    )
    nodes: dict[str, WorkflowNodeDefinitionResponse] = {}
    options: dict[NodeKind, tuple[str, str, list[WorkflowPortDefinition], dict[str, Any]]] = {
        "dataset": (
            "Freeze Temporal Pose Dataset",
            "Freeze reviewed landmark targets and native frame predictions by recording group.",
            [project],
            {"saved_dataset_id": "", "name": "", "sources": []},
        ),
        "training": (
            "Train Temporal ReefPose",
            "Train a temporal checkpoint from a frozen sequence dataset.",
            [project, dataset],
            {
                "saved_run_id": "",
                "dataset_id": None,
                "name": "",
                "window_length": 9,
                "context_mode": "centered",
                "channels": 32,
                "max_gap_seconds": None,
                "epochs": 20,
                "batch_size": 32,
                "learning_rate": 0.001,
                "loss": "smooth_l1",
                "seed": 1337,
                "device": "auto",
            },
        ),
        "inference": (
            "Refine Video Pose",
            "Produce reviewable temporal predictions alongside the original frame observations.",
            [project, model, poses],
            {
                "saved_run_id": "",
                "temporal_model_id": None,
                "source": {},
                "chunk_size": 128,
                "device": "auto",
            },
        ),
        "evaluation": (
            "Evaluate Temporal ReefPose",
            "Compare frame-only and temporal output on the same frozen test recordings.",
            [project, dataset, model],
            {
                "saved_run_id": "",
                "dataset_id": None,
                "temporal_model_id": None,
                "chunk_size": 128,
                "device": "auto",
                "movement_threshold_px_per_second": 20,
                "bootstrap_samples": 1000,
                "anatomical_events": None,
            },
        ),
    }
    for kind, (label, description, inputs, defaults) in options.items():
        name = f"temporal_reefpose_{kind}"
        port, data_type = OUTPUTS[kind]
        runtime.RUNTIME_ADAPTER_NODE_TYPES.add(name)
        runtime._ADAPTERS[name] = partial(execute, kind)
        nodes[name] = WorkflowNodeDefinitionResponse(
            node_type=name,
            display_name=label,
            category="Pose",
            description=description,
            input_ports=inputs,
            output_ports=[
                WorkflowPortDefinition(
                    port_id=port, display_name=port.title(), accepted_types=[data_type]
                )
            ],
            required_parameters=[],
            optional_parameters=defaults,
            execution_state="executable",
            executable=True,
            implementation_notes=[
                "Choose a saved record or fill in the inputs for a new calculation."
            ],
        )
    return nodes

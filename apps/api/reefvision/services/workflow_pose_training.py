"""Workflow-native Ultralytics pose retraining."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    ExperimentRecord,
    Job,
    ModelRegistration,
    PoseLandmarkSchemaRevision,
    PoseModelSchemaBinding,
    PoseTrainingDataset,
    Project,
    TrainingRun,
    WorkflowArtifact,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs.pose_training import (
    process_pose_training_job,
)
from reefvision.ml.dependencies import provider_spec
from reefvision.ml.ultralytics_registry import (
    validate_ultralytics_training_configuration,
)
from reefvision.services import (
    workflow_runtime_adapters as runtime_adapters,
)
from reefvision.storage.datasets import (
    canonical_json_sha256,
)
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import (
    resolve_managed_project_path,
)

PoseTrainingProcessor = Callable[
    [
        Settings,
        sessionmaker[Session],
        str,
    ],
    bool,
]


POSE_TRAINING_WORKFLOW_NODE_TYPES = {
    "pose_model_training",
}


DEFAULT_POSE_TRAINING_CONFIG: dict[str, Any] = {
    "epochs": 50,
    "patience": 20,
    "batch": 8,
    "imgsz": 640,
    "optimizer": "auto",
    "workers": 2,
    "cache": False,
    "plots": True,
}


def _single_payload(
    inputs: dict[
        str,
        list[WorkflowArtifact],
    ],
    port_id: str,
) -> dict[str, Any]:
    artifacts = list(
        inputs.get(
            port_id,
            [],
        )
    )

    if len(artifacts) != 1:
        raise ValidationError(f"Pose Model Training requires exactly one '{port_id}' artifact")

    return dict(artifacts[0].payload_json or {})


def _optional_payload(
    inputs: dict[
        str,
        list[WorkflowArtifact],
    ],
    port_id: str,
) -> dict[str, Any] | None:
    artifacts = list(
        inputs.get(
            port_id,
            [],
        )
    )

    if not artifacts:
        return None

    if len(artifacts) != 1:
        raise ValidationError(f"Pose Model Training accepts at most one '{port_id}' artifact")

    return dict(artifacts[0].payload_json or {})


def _pose_dataset(
    session: Session,
    *,
    project_id: str,
    payload: dict[str, Any],
    role: str,
) -> PoseTrainingDataset:
    payload_project = payload.get("project_id")

    if payload_project is not None and str(payload_project) != project_id:
        raise ValidationError(f"Pose {role} dataset belongs to another project")

    dataset_id = str(payload.get("dataset_id") or "")

    if not dataset_id:
        raise ValidationError(f"Pose {role} dataset artifact is missing dataset_id")

    dataset = session.get(
        PoseTrainingDataset,
        dataset_id,
    )

    if dataset is None or dataset.project_id != project_id:
        raise ValidationError(f"Pose {role} dataset does not belong to this project")

    if dataset.status != "complete":
        raise ValidationError(f"Pose {role} dataset must be complete")

    advertised_manifest = str(payload.get("manifest_sha256") or "")

    if advertised_manifest and advertised_manifest != dataset.manifest_sha256:
        raise ValidationError(f"Pose {role} dataset manifest no longer matches persisted truth")

    return dataset


def _seed_pose_model(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    payload: dict[str, Any],
    dataset: PoseTrainingDataset,
) -> ModelRegistration:
    model_id = str(payload.get("model_id") or "")

    if not model_id:
        raise ValidationError("Pose retraining requires a registered seed model")

    model = session.get(
        ModelRegistration,
        model_id,
    )

    if model is None or model.project_id != project_id:
        raise ValidationError("Pose retraining seed does not belong to this project")

    if model.purpose != "detector" or model.task != "pose" or model.provider_name != "ultralytics":
        raise ValidationError("Pose retraining seed must be a registered Ultralytics pose model")

    binding = session.get(
        PoseModelSchemaBinding,
        model.id,
    )

    if binding is None:
        raise ValidationError("Pose retraining seed requires a bound ReefVision landmark schema")

    revision = session.scalar(
        select(PoseLandmarkSchemaRevision).where(
            PoseLandmarkSchemaRevision.schema_id == binding.schema_id,
            PoseLandmarkSchemaRevision.revision == binding.schema_revision,
        )
    )

    if revision is None:
        raise ValidationError("Pose retraining seed schema revision no longer exists")

    if revision.content_hash != dataset.pose_schema_content_hash:
        raise ValidationError(
            "Pose retraining seed landmark schema does not match the frozen training dataset"
        )

    checkpoint = resolve_managed_project_path(
        settings,
        model.managed_path,
    )

    if not checkpoint.is_file():
        raise ValidationError("Pose retraining seed checkpoint is missing")

    actual_sha, _ = hash_model_file(checkpoint)

    if actual_sha != model.sha256:
        raise ValidationError("Pose retraining seed checkpoint checksum changed")

    return model


def create_pose_workflow_training_result(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    dataset_payload: dict[str, Any],
    initial_model_payload: dict[str, Any],
    parameters: dict[str, Any],
    validation_dataset_payload: dict[str, Any] | None = None,
    workflow_run_id: str | None = None,
    workflow_node_run_id: str | None = None,
    processor: PoseTrainingProcessor = process_pose_training_job,
) -> dict[str, Any]:
    """Execute real Ultralytics pose retraining from immutable verified truth."""

    project = session.get(
        Project,
        project_id,
    )

    if project is None:
        raise ValidationError("Pose training project was not found")

    dataset = _pose_dataset(
        session,
        project_id=project_id,
        payload=dataset_payload,
        role="training",
    )

    validation_dataset = (
        _pose_dataset(
            session,
            project_id=project_id,
            payload=(validation_dataset_payload or {}),
            role="validation",
        )
        if validation_dataset_payload is not None
        else None
    )

    if validation_dataset is not None and validation_dataset.id == dataset.id:
        raise ValidationError("Pose validation dataset must be distinct from the training dataset")

    if (
        validation_dataset is not None
        and validation_dataset.pose_schema_content_hash != dataset.pose_schema_content_hash
    ):
        raise ValidationError(
            "Pose validation dataset must use the same landmark schema as training truth"
        )

    require_validation = bool(
        parameters.get(
            "require_validation_dataset",
            False,
        )
    )

    if require_validation and validation_dataset is None:
        raise ValidationError(
            "This pose retraining configuration requires a separate frozen validation dataset"
        )

    seed_model = _seed_pose_model(
        session,
        settings,
        project_id=project_id,
        payload=initial_model_payload,
        dataset=dataset,
    )

    precision = str(
        parameters.get(
            "precision",
            "fp32",
        )
    ).strip()

    if precision not in {
        "fp32",
        "amp",
    }:
        raise ValidationError("Pose training precision must be fp32 or amp")

    supplied_config = parameters.get(
        "training_config",
        {},
    )

    if supplied_config is None:
        supplied_config = {}

    if not isinstance(
        supplied_config,
        dict,
    ):
        raise ValidationError("Pose training_config must be an object")

    training_config = {
        **DEFAULT_POSE_TRAINING_CONFIG,
        **dict(supplied_config),
    }

    # ReefVision controls this from the explicit validation input.
    training_config["val"] = validation_dataset is not None

    validate_ultralytics_training_configuration(
        task="pose",
        mode="train",
        parameters=training_config,
        search_space=[],
        expected_ultralytics_version=(provider_spec("ultralytics").provider_version),
        settings=settings,
    )

    epochs = int(
        training_config.get(
            "epochs",
            50,
        )
    )

    if epochs < 1:
        raise ValidationError("Pose training epochs must be at least 1")

    split_manifest = {
        "schema_version": ("pose-training-split-0001"),
        "training_dataset_id": dataset.id,
        "training_dataset_manifest_sha256": (dataset.manifest_sha256),
        "validation_dataset_id": (
            validation_dataset.id if validation_dataset is not None else None
        ),
        "validation_dataset_manifest_sha256": (
            validation_dataset.manifest_sha256 if validation_dataset is not None else None
        ),
        "validation_mode": (
            "separate_frozen_pose_dataset" if validation_dataset is not None else "none"
        ),
        "pose_schema_id": (dataset.pose_schema_id),
        "pose_schema_revision": (dataset.pose_schema_revision),
        "pose_schema_content_hash": (dataset.pose_schema_content_hash),
    }

    split_manifest_sha256 = canonical_json_sha256(split_manifest)

    metadata = dict(seed_model.metadata_json or {})

    architecture = str(
        parameters.get("architecture")
        or metadata.get("source_architecture")
        or seed_model.source_filename
    ).strip()

    run_name = str(parameters.get("run_name") or "workflow-pose-retrain").strip()

    if not run_name:
        raise ValidationError("Pose training run_name cannot be blank")

    random_seed = (
        int(parameters["random_seed"]) if parameters.get("random_seed") is not None else None
    )

    warning_list: list[str] = []

    if validation_dataset is None:
        warning_list.append(
            "No separate frozen validation dataset was supplied. "
            "Validation is disabled and training metrics must not be "
            "reported as independent validation performance."
        )

    run = TrainingRun(
        project_id=project_id,
        draft_id=None,
        dataset_version_id=None,
        dataset_manifest_sha256=(dataset.manifest_sha256),
        split_manifest_sha256=(split_manifest_sha256),
        task="pose",
        catalog_model_id=None,
        provider_id="ultralytics",
        architecture=architecture,
        initial_checkpoint_source=("registered_model"),
        initial_checkpoint_model_id=(seed_model.id),
        resolved_model_asset_id=(f"registered_model:{seed_model.id}"),
        resolved_model_checksum=(seed_model.sha256),
        parameter_registry_version=(provider_spec("ultralytics").provider_version),
        selected_preset=None,
        installation_state="ready",
        device=str(
            parameters.get(
                "device",
                "auto",
            )
        ),
        precision=precision,
        run_name=run_name,
        notes=(str(parameters.get("notes")).strip() if parameters.get("notes") else None),
        random_seed=random_seed,
        tiling_config_json={"mode": "none"},
        training_config_json=(training_config),
        tuning_config_json={"mode": "disabled"},
        evaluation_config_json={"validation_mode": (split_manifest["validation_mode"])},
        resource_limits_json=dict(parameters.get("resource_limits") or {}),
        preflight_report_json={
            "status": "ready_with_warnings" if warning_list else "ready",
            "warnings": warning_list,
            "task": "pose",
            "provider_id": "ultralytics",
            "truth_policy": ("scientist_verified_only"),
            "validation_mode": (split_manifest["validation_mode"]),
        },
        draft_snapshot_json={
            "schema_version": ("pose-workflow-training-snapshot-0001"),
            "pose_training_dataset_id": (dataset.id),
            "pose_training_dataset_manifest_sha256": (dataset.manifest_sha256),
            "pose_validation_dataset_id": (
                validation_dataset.id if validation_dataset is not None else None
            ),
            "pose_validation_dataset_manifest_sha256": (
                validation_dataset.manifest_sha256 if validation_dataset is not None else None
            ),
            "pose_schema_id": (dataset.pose_schema_id),
            "pose_schema_revision": (dataset.pose_schema_revision),
            "pose_schema_content_hash": (dataset.pose_schema_content_hash),
            "split_manifest": (split_manifest),
            "seed_model_id": (seed_model.id),
            "seed_model_sha256": (seed_model.sha256),
            "workflow_run_id": (workflow_run_id),
            "workflow_node_run_id": (workflow_node_run_id),
        },
        status="queued",
        stage="queued",
        progress_epoch=0,
        progress_total_epochs=epochs,
        warnings_json=warning_list,
        artifact_manifest_json={
            "pose_training_dataset_id": (dataset.id),
            "pose_validation_dataset_id": (
                validation_dataset.id if validation_dataset is not None else None
            ),
            "pose_schema_id": (dataset.pose_schema_id),
            "pose_schema_revision": (dataset.pose_schema_revision),
            "pose_schema_content_hash": (dataset.pose_schema_content_hash),
            "pose_split_manifest": (split_manifest),
            "pose_split_manifest_sha256": (split_manifest_sha256),
        },
    )

    session.add(run)
    session.flush()

    job = Job(
        project_id=project_id,
        job_type="training",
        status="queued",
        progress_current=0,
        progress_total=epochs,
        request_json={
            "training_run_id": run.id,
            "pose_training_dataset_id": (dataset.id),
            "pose_validation_dataset_id": (
                validation_dataset.id if validation_dataset is not None else None
            ),
            "created_by_workflow": True,
            "workflow_run_id": (workflow_run_id),
            "workflow_node_run_id": (workflow_node_run_id),
        },
        result_json={
            "stage": "queued",
            "task": "pose",
        },
    )

    session.add(job)
    session.flush()

    run.job_id = job.id

    session.commit()

    child_factory = sessionmaker(
        bind=session.get_bind(),
        expire_on_commit=False,
    )

    processed = processor(
        settings,
        child_factory,
        job.id,
    )

    session.expire_all()

    refreshed_job = session.get(
        Job,
        job.id,
    )

    refreshed_run = session.get(
        TrainingRun,
        run.id,
    )

    if not processed or refreshed_job is None or refreshed_run is None:
        raise ValidationError("Pose training child job did not complete")

    job = refreshed_job
    run = refreshed_run

    if job.status != "succeeded" or run.status != "completed":
        detail = run.error_message or job.error_message or (f"job={job.status}, run={run.status}")

        raise ValidationError("Pose training child job failed: " + detail)

    if not run.result_checkpoint_path:
        raise ValidationError("Completed pose training did not produce a checkpoint")

    checkpoint = resolve_managed_project_path(
        settings,
        run.result_checkpoint_path,
    )

    if not checkpoint.is_file():
        raise ValidationError("Completed pose training checkpoint is missing")

    checkpoint_sha256, checkpoint_size = hash_model_file(checkpoint)

    experiment = session.scalar(
        select(ExperimentRecord).where(ExperimentRecord.training_run_id == run.id)
    )

    return {
        "schema_version": ("workflow-training-result-0001"),
        "project_id": project_id,
        "created_by_workflow": True,
        "workflow_run_id": (workflow_run_id),
        "workflow_node_run_id": (workflow_node_run_id),
        "training_run_id": run.id,
        "training_job_id": job.id,
        "training_draft_id": None,
        "experiment_id": (experiment.id if experiment is not None else None),
        "dataset_version_id": None,
        "dataset_manifest_sha256": (run.dataset_manifest_sha256),
        "split_manifest_sha256": (run.split_manifest_sha256),
        "pose_training_dataset_id": (dataset.id),
        "pose_validation_dataset_id": (
            validation_dataset.id if validation_dataset is not None else None
        ),
        "pose_schema_id": (dataset.pose_schema_id),
        "pose_schema_revision": (dataset.pose_schema_revision),
        "pose_schema_content_hash": (dataset.pose_schema_content_hash),
        "validation_mode": (split_manifest["validation_mode"]),
        "task": run.task,
        "provider_id": run.provider_id,
        "architecture": run.architecture,
        "initial_checkpoint_source": (run.initial_checkpoint_source),
        "initial_checkpoint_model_id": (run.initial_checkpoint_model_id),
        "resolved_model_asset_id": (run.resolved_model_asset_id),
        "resolved_model_checksum": (run.resolved_model_checksum),
        "parameter_registry_version": (run.parameter_registry_version),
        "device": run.device,
        "precision": run.precision,
        "run_name": run.run_name,
        "random_seed": run.random_seed,
        "metrics": dict(run.metrics_json or {}),
        "metrics_history": dict(run.metrics_history_json or {}),
        "warnings": list(run.warnings_json or []),
        "artifact_manifest": dict(run.artifact_manifest_json or {}),
        "logs_path": run.logs_path,
        "result_checkpoint_path": (run.result_checkpoint_path),
        "result_checkpoint_sha256": (checkpoint_sha256),
        "result_checkpoint_size_bytes": (checkpoint_size),
    }


def execute_pose_model_training_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[
        str,
        list[WorkflowArtifact],
    ],
) -> list[dict[str, Any]]:
    dataset = _single_payload(
        inputs,
        "dataset",
    )

    initial_model = _single_payload(
        inputs,
        "initial_model",
    )

    validation_dataset = _optional_payload(
        inputs,
        "validation_dataset",
    )

    result = create_pose_workflow_training_result(
        session,
        settings,
        project_id=project_id,
        dataset_payload=dataset,
        validation_dataset_payload=(validation_dataset),
        initial_model_payload=(initial_model),
        parameters=parameters,
        workflow_run_id=str(parameters.get("__workflow_run_id") or "") or None,
        workflow_node_run_id=str(parameters.get("__workflow_node_run_id") or "") or None,
    )

    return [
        {
            "port_id": "training",
            "data_type": "training_result",
            "payload": result,
        }
    ]


_POSE_TRAINING_ADAPTERS = {
    "pose_model_training": (execute_pose_model_training_adapter),
}


def register_pose_training_workflow_adapter() -> None:
    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.update(_POSE_TRAINING_ADAPTERS)

    runtime_adapters._ADAPTERS.update(_POSE_TRAINING_ADAPTERS)

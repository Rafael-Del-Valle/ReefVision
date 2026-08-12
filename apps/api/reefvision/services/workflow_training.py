"""Workflow-native training, retraining, and trained-model registration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    ExperimentRecord,
    Job,
    ModelRegistration,
    TrainingRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.jobs.training_dispatch import process_task_aware_training_job
from reefvision.ml.semantic_segmentation import (
    NNUNET_CONFIGURATION,
    NNUNET_PROVIDER_ID,
    SEMANTIC_SEGMENTATION_TASK,
)
from reefvision.schemas.models import RegisterModelFromRunRequest
from reefvision.schemas.training import TrainingDraftWriteRequest, TrainingRunCreateRequest
from reefvision.services.semantic_models import SemanticModelService
from reefvision.services.semantic_training import SemanticTrainingService
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path

SUPPORTED_WORKFLOW_TRAINING_TASKS = {"detect", "segment", SEMANTIC_SEGMENTATION_TASK}

TrainingProcessor = Callable[[Settings, sessionmaker[Session], str], bool]
TrainingServiceFactory = Callable[[Session, Settings], SemanticTrainingService]
ModelServiceFactory = Callable[[Session, Settings], SemanticModelService]


def _dict_parameter(parameters: dict[str, Any], key: str) -> dict[str, Any]:
    value = parameters.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError(f"Model Training parameter '{key}' must be an object")
    return dict(value)


def _initial_model(
    session: Session,
    *,
    project_id: str,
    task: str,
    model_payload: dict[str, Any] | None,
) -> ModelRegistration | None:
    if not model_payload:
        return None
    model_id = str(model_payload.get("model_id") or "")
    if not model_id:
        raise ValidationError("Model Training received an invalid initial-model reference")
    model = session.get(ModelRegistration, model_id)
    if model is None or model.project_id != project_id:
        raise ValidationError("Initial training model does not belong to this project")
    if task == "detect" and (model.purpose != "detector" or model.task != "detect"):
        raise ValidationError("Detection retraining requires a registered detector")
    if task == "segment" and (model.purpose != "segmenter" or model.task != "segment"):
        raise ValidationError("Instance-segmentation retraining requires a registered segmenter")
    if task == SEMANTIC_SEGMENTATION_TASK:
        raise ValidationError("Semantic nnU-Net training currently starts from scratch")
    return model


def _resolved_architecture(
    *,
    task: str,
    parameters: dict[str, Any],
    initial_model: ModelRegistration | None,
) -> str | None:
    explicit = str(parameters.get("architecture") or "").strip()
    if explicit:
        return explicit
    if task == SEMANTIC_SEGMENTATION_TASK:
        return NNUNET_CONFIGURATION
    if initial_model is not None:
        metadata = dict(initial_model.metadata_json or {})
        for key in ("source_architecture", "architecture"):
            candidate = str(metadata.get(key) or "").strip()
            if candidate:
                return candidate
    return None


def create_workflow_training_result(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    dataset_payload: dict[str, Any],
    parameters: dict[str, Any],
    initial_model_payload: dict[str, Any] | None = None,
    training_service_factory: TrainingServiceFactory = SemanticTrainingService,
    processor: TrainingProcessor = process_task_aware_training_job,
) -> dict[str, Any]:
    """Run one normal ReefVision training job inline and return immutable lineage metadata."""

    payload_project_id = dataset_payload.get("project_id")
    if payload_project_id is not None and str(payload_project_id) != project_id:
        raise ValidationError("Model Training received a dataset from another project")
    dataset_version_id = str(dataset_payload.get("dataset_version_id") or "")
    version = session.get(DatasetVersion, dataset_version_id)
    if version is None or version.project_id != project_id or version.status != "complete":
        raise ValidationError("Model Training requires a complete dataset version in this project")
    advertised_manifest = str(dataset_payload.get("manifest_sha256") or "")
    if advertised_manifest and advertised_manifest != version.manifest_sha256:
        raise ValidationError("Workflow dataset manifest no longer matches the persisted version")

    task = str(parameters.get("task") or "detect").strip()
    if task not in SUPPORTED_WORKFLOW_TRAINING_TASKS:
        raise ValidationError(
            "Model Training task must be detect, segment, or semantic_segment"
        )
    catalog_model_id = str(parameters.get("catalog_model_id") or "").strip() or None
    initial_model = _initial_model(
        session,
        project_id=project_id,
        task=task,
        model_payload=initial_model_payload,
    )
    if initial_model is not None and catalog_model_id is not None:
        raise ValidationError(
            "Choose either a registered initial model or a managed catalog model, not both"
        )

    architecture = _resolved_architecture(
        task=task,
        parameters=parameters,
        initial_model=initial_model,
    )
    if architecture is None and catalog_model_id is None:
        raise ValidationError(
            "Model Training requires an architecture unless catalog_model_id resolves one"
        )
    provider_id = str(parameters.get("provider_id") or "").strip() or (
        NNUNET_PROVIDER_ID if task == SEMANTIC_SEGMENTATION_TASK else "ultralytics"
    )
    run_name = str(parameters.get("run_name") or f"workflow-{task}").strip()
    if not run_name:
        raise ValidationError("Model Training run_name cannot be blank")

    initial_checkpoint_source = (
        "registered_model"
        if initial_model is not None
        else "managed_catalog"
        if catalog_model_id is not None
        else "scratch"
    )
    draft_request = TrainingDraftWriteRequest(
        name=str(parameters.get("draft_name") or f"Workflow {run_name}"),
        run_name=run_name,
        notes=str(parameters.get("notes") or "").strip() or None,
        dataset_version_id=version.id,
        task=task,
        catalog_model_id=catalog_model_id,
        provider_id=provider_id,
        architecture=architecture,
        initial_checkpoint_source=initial_checkpoint_source,
        initial_checkpoint_model_id=initial_model.id if initial_model is not None else None,
        device=str(parameters.get("device") or "auto"),
        precision=str(parameters.get("precision") or "fp32"),
        random_seed=(
            int(parameters["random_seed"])
            if parameters.get("random_seed") is not None
            else None
        ),
        tiling_config=_dict_parameter(parameters, "tiling_config"),
        training_config=_dict_parameter(parameters, "training_config"),
        tuning_config=_dict_parameter(parameters, "tuning_config"),
        evaluation_config=_dict_parameter(parameters, "evaluation_config"),
        resource_limits=_dict_parameter(parameters, "resource_limits"),
    )

    training = training_service_factory(session, settings)
    draft = training.create_draft(project_id, draft_request)
    run_response = training.create_run(
        project_id,
        TrainingRunCreateRequest(draft_id=draft.id),
    )
    if not run_response.job_id:
        raise ValidationError("Training run was created without a background job")

    child_factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    processed = processor(settings, child_factory, run_response.job_id)
    session.expire_all()
    job = session.get(Job, run_response.job_id)
    run = session.get(TrainingRun, run_response.id)
    if not processed or job is None or run is None:
        raise ValidationError("Workflow training child job did not complete")
    if job.status != "succeeded" or run.status != "completed":
        detail = run.error_message or job.error_message or f"job={job.status}, run={run.status}"
        raise ValidationError(f"Workflow training child job failed: {detail}")
    if not run.result_checkpoint_path:
        raise ValidationError("Completed workflow training did not produce a checkpoint")

    checkpoint_path = resolve_managed_project_path(settings, run.result_checkpoint_path)
    if not checkpoint_path.is_file():
        raise ValidationError("Completed workflow training checkpoint is missing")
    checkpoint_sha256, checkpoint_size = hash_model_file(checkpoint_path)
    experiment = session.scalar(
        select(ExperimentRecord).where(ExperimentRecord.training_run_id == run.id)
    )

    return {
        "schema_version": "workflow-training-result-0001",
        "project_id": project_id,
        "created_by_workflow": True,
        "training_run_id": run.id,
        "training_job_id": job.id,
        "training_draft_id": draft.id,
        "experiment_id": experiment.id if experiment is not None else None,
        "dataset_version_id": run.dataset_version_id,
        "dataset_manifest_sha256": run.dataset_manifest_sha256,
        "split_manifest_sha256": run.split_manifest_sha256,
        "task": run.task,
        "provider_id": run.provider_id,
        "architecture": run.architecture,
        "catalog_model_id": run.catalog_model_id,
        "initial_checkpoint_source": run.initial_checkpoint_source,
        "initial_checkpoint_model_id": run.initial_checkpoint_model_id,
        "resolved_model_asset_id": run.resolved_model_asset_id,
        "resolved_model_checksum": run.resolved_model_checksum,
        "parameter_registry_version": run.parameter_registry_version,
        "selected_preset": run.selected_preset,
        "installation_state": run.installation_state,
        "device": run.device,
        "precision": run.precision,
        "run_name": run.run_name,
        "random_seed": run.random_seed,
        "metrics": dict(run.metrics_json or {}),
        "metrics_history": dict(run.metrics_history_json or {}),
        "warnings": list(run.warnings_json or []),
        "artifact_manifest": dict(run.artifact_manifest_json or {}),
        "logs_path": run.logs_path,
        "result_checkpoint_path": run.result_checkpoint_path,
        "result_checkpoint_sha256": checkpoint_sha256,
        "result_checkpoint_size_bytes": checkpoint_size,
    }


def register_workflow_trained_model(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    training_payload: dict[str, Any],
    parameters: dict[str, Any],
    model_service_factory: ModelServiceFactory = SemanticModelService,
) -> dict[str, Any]:
    """Register a completed workflow training result through the normal model registry."""

    if training_payload.get("project_id") != project_id:
        raise ValidationError("Register Trained Model received a result from another project")
    run_id = str(training_payload.get("training_run_id") or "")
    run = session.get(TrainingRun, run_id)
    if run is None or run.project_id != project_id:
        raise ValidationError("Workflow training run does not belong to this project")
    if run.status != "completed" or not run.result_checkpoint_path:
        raise ValidationError("Only completed workflow training runs can be registered")
    expected_sha = str(training_payload.get("result_checkpoint_sha256") or "")
    checkpoint = resolve_managed_project_path(settings, run.result_checkpoint_path)
    actual_sha, _ = hash_model_file(checkpoint)
    if expected_sha and actual_sha != expected_sha:
        raise ValidationError("Training checkpoint checksum changed before model registration")

    service = model_service_factory(session, settings)
    registered = service.register_model_from_run(
        project_id,
        RegisterModelFromRunRequest(
            training_run_id=run.id,
            display_name=str(parameters.get("display_name") or "").strip() or None,
            notes=str(parameters.get("notes") or "").strip() or None,
        ),
    )
    metadata = dict(registered.metadata_json or {})
    return {
        "schema_version": "workflow-model-reference-0001",
        "project_id": project_id,
        "model_id": registered.id,
        "model_sha256": registered.sha256,
        "purpose": registered.purpose,
        "task": registered.task,
        "provider_name": registered.provider_name,
        "provider_version": registered.provider_version,
        "framework": registered.framework,
        "source_training_run_id": run.id,
        "source_experiment_id": metadata.get("source_experiment_id"),
        "source_dataset_version_id": metadata.get("source_dataset_version_id"),
        "source_dataset_manifest_sha256": metadata.get("source_dataset_manifest_sha256"),
        "source_split_manifest_sha256": metadata.get("source_split_manifest_sha256"),
        "registered_from_workflow": True,
    }

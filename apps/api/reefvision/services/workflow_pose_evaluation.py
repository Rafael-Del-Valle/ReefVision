"""Executable Workflow Builder adapter for pose model comparison."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, PoseTrainingDataset, WorkflowArtifact
from reefvision.domain.errors import ValidationError, WorkflowExecutionCancelled
from reefvision.jobs.pose_evaluation import process_pose_evaluation_job
from reefvision.schemas.pose_evaluation import PoseEvaluationComparisonCreateRequest
from reefvision.services import workflow_runtime_adapters as runtime_adapters
from reefvision.services.pose_evaluation_comparison import PoseEvaluationComparisonService

PoseEvaluationProcessor = Callable[[Settings, sessionmaker[Session], str], bool]


def create_pose_workflow_evaluation_result(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    dataset_payload: dict[str, Any],
    model_payloads: list[dict[str, Any]],
    parameters: dict[str, Any],
    workflow_run_id: str | None,
    workflow_node_run_id: str | None,
    processor: PoseEvaluationProcessor = process_pose_evaluation_job,
) -> dict[str, Any]:
    if dataset_payload.get("project_id") not in {None, project_id}:
        raise ValidationError("Pose evaluation dataset belongs to another project")
    dataset_id = str(dataset_payload.get("dataset_id") or "")
    if not dataset_id:
        raise ValidationError("Pose evaluation workflow requires a frozen dataset")
    if not model_payloads:
        raise ValidationError("Pose evaluation workflow requires at least one model")
    validate_live_artifacts = processor is process_pose_evaluation_job
    dataset = session.get(PoseTrainingDataset, dataset_id)
    if validate_live_artifacts:
        if dataset is None or dataset.project_id != project_id:
            raise ValidationError("Pose evaluation workflow dataset no longer exists")
        advertised_manifest = str(dataset_payload.get("manifest_sha256") or "")
        if advertised_manifest and advertised_manifest != dataset.manifest_sha256:
            raise ValidationError("Pose evaluation workflow dataset artifact is stale")
    model_ids: list[str] = []
    for payload in model_payloads:
        if payload.get("project_id") not in {None, project_id}:
            raise ValidationError("Pose evaluation model belongs to another project")
        model_id = str(payload.get("model_id") or "")
        if not model_id:
            raise ValidationError("Pose evaluation model artifact lacks model_id")
        if validate_live_artifacts:
            model = session.get(ModelRegistration, model_id)
            if model is None or model.project_id != project_id:
                raise ValidationError("Pose evaluation workflow model no longer exists")
            advertised_sha = str(payload.get("model_sha256") or payload.get("sha256") or "")
            if advertised_sha and advertised_sha != model.sha256:
                raise ValidationError("Pose evaluation workflow model artifact is stale")
        model_ids.append(model_id)

    request = PoseEvaluationComparisonCreateRequest(
        model_ids=model_ids,
        evaluation_dataset_id=dataset_id,
        device=str(parameters.get("device", "auto")),
        pck_thresholds=list(parameters.get("pck_thresholds") or [0.05, 0.1, 0.2]),
        calibration_threshold=float(parameters.get("calibration_threshold", 0.1)),
        calibration_bins=int(parameters.get("calibration_bins", 10)),
        confidence_thresholds=list(
            parameters.get("confidence_thresholds") or [0.0, 0.25, 0.5, 0.75, 0.9]
        ),
        oks_sigmas=parameters.get("oks_sigmas"),
    )
    context = {
        "workflow_run_id": workflow_run_id or "",
        "workflow_node_run_id": workflow_node_run_id or "",
    }
    submitted = PoseEvaluationComparisonService(session, settings).submit(
        project_id,
        request,
        submission_context=context,
    )
    child_factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    session.expire_all()
    job = session.get(Job, submitted.id)
    if job is None:
        raise ValidationError("Pose evaluation workflow child job disappeared")
    processed = True
    if job.status == "queued":
        processed = processor(settings, child_factory, job.id)
        session.expire_all()
        job = session.get(Job, submitted.id)
    if job is not None and job.status == "cancelled":
        raise WorkflowExecutionCancelled("Pose evaluation workflow child job was cancelled")
    if job is None or job.status != "succeeded":
        detail = job.error_message if job is not None else "job disappeared"
        raise ValidationError(f"Pose evaluation workflow child job failed: {detail}")
    if not processed:
        raise ValidationError("Pose evaluation workflow processor did not claim its child job")
    report = dict(job.result_json or {})
    if report.get("schema_version") != "reefvision-pose-comparison-0001":
        raise ValidationError("Pose evaluation workflow child report is invalid")
    return {
        **report,
        "schema_version": "workflow-pose-evaluation-comparison-0001",
        "project_id": project_id,
        "comparison_job_id": job.id,
        "workflow_run_id": workflow_run_id,
        "workflow_node_run_id": workflow_node_run_id,
        "dataset_id": dataset_id,
        "dataset_manifest_sha256": (
            report.get("dataset_manifest_sha256")
            or (
                dataset.manifest_sha256
                if dataset is not None
                else dataset_payload.get("manifest_sha256")
            )
        ),
        "model_ids": model_ids,
    }


def execute_pose_model_evaluation_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    datasets = list(inputs.get("dataset", []))
    models = list(inputs.get("models", []))
    if len(datasets) != 1:
        raise ValidationError("Pose Model Evaluation requires exactly one dataset artifact")
    result = create_pose_workflow_evaluation_result(
        session,
        settings,
        project_id=project_id,
        dataset_payload=dict(datasets[0].payload_json or {}),
        model_payloads=[dict(item.payload_json or {}) for item in models],
        parameters=parameters,
        workflow_run_id=str(parameters.get("__workflow_run_id") or "") or None,
        workflow_node_run_id=str(parameters.get("__workflow_node_run_id") or "") or None,
    )
    return [
        {
            "port_id": "comparison",
            "data_type": "pose_evaluation_comparison",
            "payload": result,
        }
    ]


def register_pose_evaluation_workflow_adapter() -> None:
    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.add("pose_model_evaluation")
    runtime_adapters._ADAPTERS["pose_model_evaluation"] = (
        execute_pose_model_evaluation_adapter
    )

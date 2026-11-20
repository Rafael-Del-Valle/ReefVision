"""Admission policy for executable workflows that may run without an open editor."""

from __future__ import annotations

import re
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    EcologyAnalysisRecord,
    Job,
    ModelRegistration,
    ModelRuntimeSelection,
    Project,
    VideoAsset,
    WorkflowRun,
)
from reefvision.db.models.field_capture import FieldCaptureBatch
from reefvision.db.models.workflow_schedule import WorkflowSchedule, WorkflowScheduleOccurrence
from reefvision.domain.errors import ValidationError
from reefvision.schemas.workflow_graphs import WorkflowGraphPlanResponse, WorkflowPlanStep
from reefvision.services.ecology_event_summary import EVENT_SUMMARY_JOB
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.results_packages import sha256_file

_INFERENCE_OUTPUTS = {
    "detection_inference": "detection_proposals",
    "segmentation_inference": "mask_proposals",
    "classification_inference": "classification_predictions",
    "pose_inference": "pose_tracks",
    "video_tracking": "video_tracks",
}
_REVIEW_OUTPUTS = {
    "detection_review_gate": "reviewed_boxes",
    "mask_review_gate": "reviewed_masks",
    "classification_review_gate": "reviewed_labels",
}
_PURPOSE_OUTPUTS = {
    "acquisition": {
        "field_capture_reconcile": "field_capture_reconciliation",
        "acquisition_source_capture": "acquisition_capture_receipt",
    },
    "inference": {**_INFERENCE_OUTPUTS, **_REVIEW_OUTPUTS},
    "qc": {
        "qc_review_queue": "review_queue_reference",
        "image_acquisition_quality": "acquisition_quality_result",
    },
    "report": {
        "ecology_event_summary": "reviewed_ecology_event_summary",
        "paired_growth_contrast": "paired_growth_contrast",
        "monitoring_assessment": "monitoring_assessment",
    },
}
_ALLOWED_NODES = {
    "project_source",
    "project_images",
    "project_video_source",
    "dataset_version_source",
    "registered_model_source",
    "reviewed_model_runtime",
    *(node_type for outputs in _PURPOSE_OUTPUTS.values() for node_type in outputs),
}


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValidationError(f"Schedule requires a valid {label} SHA-256 pin")
    return value


def _identifier(parameters: dict[str, Any], name: str) -> str:
    value = parameters.get(name)
    try:
        if isinstance(value, str):
            return str(UUID(value))
    except ValueError:
        pass
    raise ValidationError(f"Schedule requires a pinned {name} UUID in the saved graph")


_ScheduleReference = TypeVar(
    "_ScheduleReference",
    DatasetVersion,
    EcologyAnalysisRecord,
    FieldCaptureBatch,
    Job,
    ModelRegistration,
    ModelRuntimeSelection,
    VideoAsset,
)


def _owned_record(
    session: Session, model: type[_ScheduleReference], identifier: str, project_id: str
) -> _ScheduleReference:
    record = session.get(model, identifier)
    if record is None or record.project_id != project_id:
        raise ValidationError("A pinned schedule reference is missing from this project")
    return record


def _reference(
    node: WorkflowPlanStep, identifier: str, digest: Any, **detail: str | None
) -> dict[str, str | None]:
    return {
        "node_id": node.node_id,
        "kind": node.node_type,
        "id": identifier,
        "sha256": _digest(digest, node.display_name),
        **detail,
    }


def _source_reference(
    session: Session, project_id: str, node: WorkflowPlanStep
) -> dict[str, str | None] | None:
    parameters = node.parameters
    match node.node_type:
        case "dataset_version_source":
            identifier = _identifier(parameters, "dataset_version_id")
            dataset = _owned_record(session, DatasetVersion, identifier, project_id)
            if dataset.status != "complete":
                raise ValidationError("Scheduled inference or QC requires a complete dataset")
            split = parameters.get("split")
            if split is not None and split not in ("train", "validation", "test"):
                raise ValidationError("Choose a valid split for the frozen dataset")
            return _reference(node, identifier, dataset.manifest_sha256, split=split)
        case "project_video_source":
            identifier = _identifier(parameters, "video_id")
            video = _owned_record(session, VideoAsset, identifier, project_id)
            return _reference(node, identifier, video.sha256)
        case "registered_model_source":
            identifier = _identifier(parameters, "model_id")
            model = _owned_record(session, ModelRegistration, identifier, project_id)
            return _reference(node, identifier, model.sha256)
        case "reviewed_model_runtime":
            identifier = _identifier(parameters, "selection_id")
            selection = _owned_record(session, ModelRuntimeSelection, identifier, project_id)
            model = _owned_record(session, ModelRegistration, selection.model_id, project_id)
            if selection.content_sha256 != _digest(parameters.get("selection_sha256"), "runtime"):
                raise ValidationError("The selected model runtime does not match its graph pin")
            return _reference(
                node,
                identifier,
                selection.content_sha256,
                model_sha256=_digest(model.sha256, "model"),
            )
        case "field_capture_reconcile":
            identifier = _identifier(parameters, "batch_id")
            batch = _owned_record(session, FieldCaptureBatch, identifier, project_id)
            if batch.manifest_sha256 != _digest(parameters.get("manifest_sha256"), "field batch"):
                raise ValidationError("Use the sealed field batch and its original manifest digest")
            return _reference(node, identifier, batch.manifest_sha256)
        case "ecology_event_summary":
            identifier = _identifier(parameters, "summary_id")
            summary = _owned_record(session, Job, identifier, project_id)
            if (
                parameters.get("configuration")
                or summary.job_type != EVENT_SUMMARY_JOB
                or summary.status != "succeeded"
            ):
                raise ValidationError(
                    "Scheduled event reporting requires an already reviewed summary"
                )
            return _reference(node, identifier, (summary.result_json or {}).get("content_sha256"))
        case "paired_growth_contrast":
            identifier = _identifier(parameters, "analysis_id")
            analysis = _owned_record(session, EcologyAnalysisRecord, identifier, project_id)
            if analysis.content_sha256 != _digest(parameters.get("source_sha256"), "growth source"):
                raise ValidationError("The reviewed growth source does not match its graph pin")
            return _reference(node, identifier, analysis.content_sha256)
        case "acquisition_source_capture":
            identifier = _identifier(parameters, "source_id")
            return _reference(node, identifier, parameters.get("source_sha256"))
        case "monitoring_assessment":
            identifier = _identifier(parameters, "rule_id")
            return _reference(node, identifier, parameters.get("rule_sha256"))
        case _:
            return None


def schedule_graph_inputs(
    session: Session,
    project_id: str,
    purpose: str,
    plan: WorkflowGraphPlanResponse,
) -> dict[str, Any]:
    """Validate the entire typed DAG and capture its non-configurable source identities."""
    if not plan.executable:
        raise ValidationError("The saved workflow must be executable before scheduling")
    steps = {step.node_id: step for step in plan.steps}
    upstream = {edge.source_node_id for step in plan.steps for edge in step.input_bindings}
    for step in plan.steps:
        if step.node_type not in _ALLOWED_NODES:
            raise ValidationError(f"{step.display_name} is not supported in unattended schedules")
    terminals = [step for step in plan.steps if step.node_id not in upstream]
    accepted = _PURPOSE_OUTPUTS.get(purpose, {})
    if not terminals or any(
        accepted.get(step.node_type)
        not in {data_type for port in step.output_types.values() for data_type in port}
        for step in terminals
    ):
        raise ValidationError(f"The saved workflow must end in a typed {purpose} result")
    if purpose == "inference" and not any(
        step.node_type in _INFERENCE_OUTPUTS for step in plan.steps
    ):
        raise ValidationError("An inference schedule must run a supported local inference node")

    for step in plan.steps:
        if step.node_type in _INFERENCE_OUTPUTS:
            for binding in step.input_bindings:
                source = steps[binding.source_node_id]
                if binding.target_port_id == "model" and source.node_type not in {
                    "registered_model_source",
                    "reviewed_model_runtime",
                }:
                    raise ValidationError("Schedule inference needs a pinned local model source")
                if (
                    binding.target_port_id == "images"
                    and source.node_type == "dataset_version_source"
                    and source.parameters.get("split") is None
                ):
                    raise ValidationError("Choose the frozen dataset split for scheduled inference")

    refs = [
        ref
        for step in plan.steps
        if (ref := _source_reference(session, project_id, step)) is not None
    ]
    return {"references": refs} if refs else {}


def verify_scheduled_run(
    session: Session, settings: Settings, run: WorkflowRun, plan: WorkflowGraphPlanResponse
) -> None:
    """Fail before node execution if a queued run's scientific pins have changed."""
    tracking = session.execute(
        select(WorkflowScheduleOccurrence, WorkflowSchedule)
        .join(WorkflowSchedule, WorkflowSchedule.id == WorkflowScheduleOccurrence.schedule_id)
        .where(WorkflowScheduleOccurrence.workflow_run_id == run.id)
    ).one_or_none()
    if tracking is None:
        return
    occurrence, schedule = tracking
    project = session.get(Project, run.project_id)
    if project is None or project.archived_at is not None:
        raise ValidationError("Restore the archived project before running scheduled work")
    inputs = schedule_graph_inputs(session, run.project_id, schedule.purpose, plan)
    if (
        occurrence.project_id != run.project_id
        or schedule.project_id != run.project_id
        or run.workflow_graph_record_id != schedule.workflow_graph_record_id
        or occurrence.graph_sha256 != run.graph_sha256
        or occurrence.graph_sha256 != schedule.graph_sha256
        or occurrence.inputs_sha256 != schedule.inputs_sha256
        or canonical_json_sha256(inputs) != occurrence.inputs_sha256
        or inputs != run.input_json
    ):
        raise ValidationError(
            "The scheduled workflow or its pinned inputs changed before execution"
        )

    for pin in inputs.get("references", []):
        # Reviewed runtime selections and sealed field batches verify their bytes in
        # the same adapter used by standalone execution. Bare models and videos
        # additionally need their original managed bytes verified before a scheduled run.
        record: ModelRegistration | VideoAsset
        if pin["kind"] == "registered_model_source":
            record = _owned_record(session, ModelRegistration, pin["id"], run.project_id)
        elif pin["kind"] == "project_video_source":
            record = _owned_record(session, VideoAsset, pin["id"], run.project_id)
        else:
            continue
        path = resolve_managed_project_path(settings, record.managed_path)
        try:
            actual = sha256_file(path)
        except OSError as exc:
            raise ValidationError("Original managed input bytes are unavailable") from exc
        if actual != pin["sha256"]:
            raise ValidationError(
                "Original managed input bytes do not match the scheduled checksum"
            )

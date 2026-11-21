"""Rebind saved pose-workflow evidence to an already validated local training run."""

from __future__ import annotations

import re
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Job,
    ModelRegistration,
    Project,
    TrainingRun,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.services.workflow_provenance import (
    build_workflow_run_provenance,
    verify_succeeded_node_artifacts,
    verify_workflow_artifact,
)
from reefvision.storage.datasets import canonical_json_sha256

_CHECKPOINT_PATHS = (
    "best_checkpoint_path",
    "last_checkpoint_path",
    "resume_checkpoint_path",
    "resume_best_checkpoint_path",
)


def _require(condition: bool, field: str) -> None:
    if not condition:
        raise ValidationError(f"Saved pose training history disagrees with its {field}")


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _managed_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValidationError("Saved pose training history has an invalid managed path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValidationError("Saved pose training history has an invalid managed path")
    return value


@dataclass(frozen=True)
class _TrainingBinding:
    run: TrainingRun
    source_split_sha256: str
    source_dataset_sha256: str
    source_root: str
    target_root: str
    split: dict[str, Any]
    checkpoint_sha256: str

    def _local_path(self, value: object) -> str:
        path = _managed_path(value)
        source_prefix = self.source_root + "/"
        if path.startswith(source_prefix):
            return self.target_root + "/" + path[len(source_prefix) :]
        _require(path.startswith(self.target_root + "/"), "project storage root")
        return path

    def _path(self, record: dict[str, Any], field: str, expected_path: object) -> None:
        if field not in record:
            return
        old_path = record[field]
        if expected_path is None:
            _require(old_path is None, field)
            return
        local = self._local_path(expected_path)
        _require(old_path is not None and self._local_path(old_path) == local, field)
        record[field] = local

    def _pin(self, record: dict[str, Any], field: str, source: str, local: str) -> None:
        if field in record:
            _require(record[field] == source or record[field] == local, field)
            record[field] = local

    def _dataset_pin(self, record: dict[str, Any], field: str) -> None:
        self._pin(record, field, self.source_dataset_sha256, self.run.dataset_manifest_sha256)

    def _split_pin(self, record: dict[str, Any], field: str) -> None:
        self._pin(record, field, self.source_split_sha256, self.run.split_manifest_sha256)

    def _training_dataset(self, record: dict[str, Any], field: str) -> None:
        if field in record:
            _require(record[field] == self.split["training_dataset_id"], field)

    def _checkpoint(self, record: dict[str, Any], field: str) -> None:
        if field in record:
            _require(record[field] == self.checkpoint_sha256, field)

    def training_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        run = self.run
        _require(
            payload.get("project_id") == run.project_id
            and payload.get("training_run_id") == run.id
            and payload.get("training_job_id") == run.job_id
            and payload.get("task") == "pose"
            and payload.get("provider_id") == run.provider_id,
            "training run identity",
        )
        _require(
            payload.get("result_checkpoint_sha256") == self.checkpoint_sha256,
            "selected checkpoint",
        )
        result = deepcopy(payload)
        self._dataset_pin(result, "dataset_manifest_sha256")
        self._split_pin(result, "split_manifest_sha256")
        self._training_dataset(result, "pose_training_dataset_id")
        self._path(result, "result_checkpoint_path", run.result_checkpoint_path)
        self._path(result, "logs_path", run.logs_path)
        manifest = result.get("artifact_manifest")
        if not isinstance(manifest, dict):
            raise ValidationError("Saved pose training result is missing its artifact manifest")

        self._dataset_pin(manifest, "pose_training_dataset_manifest_sha256")
        self._split_pin(manifest, "pose_split_manifest_sha256")
        self._training_dataset(manifest, "pose_training_dataset_id")
        self._checkpoint(manifest, "result_checkpoint_sha256")
        persisted_split = manifest.get("pose_split_manifest")
        if persisted_split is not None:
            if not isinstance(persisted_split, dict):
                raise ValidationError("Saved pose training result has an invalid split manifest")
            split = dict(persisted_split)
            self._dataset_pin(split, "training_dataset_manifest_sha256")
            _require(split == self.split, "local frozen split")
            manifest["pose_split_manifest"] = split

        for field in _CHECKPOINT_PATHS:
            self._path(manifest, field, run.artifact_manifest_json.get(field))
        self._path(manifest, "logs_path", run.logs_path)
        self._path(manifest, "result_checkpoint_path", run.result_checkpoint_path)
        return result

    def model_source(self, payload: dict[str, Any], *, checkpoint_field: str) -> dict[str, Any]:
        run = self.run
        _require(payload.get("source_training_run_id") == run.id, "model source training ID")
        result = dict(payload)
        self._checkpoint(result, checkpoint_field)
        self._dataset_pin(result, "source_dataset_manifest_sha256")
        self._split_pin(result, "source_split_manifest_sha256")
        self._training_dataset(result, "source_pose_training_dataset_id")
        self._path(result, "source_result_checkpoint_path", run.result_checkpoint_path)
        return result


def _update_artifact_refs(
    result: dict[str, Any],
    field: str,
    changes: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    if field not in result:
        return result
    refs = result[field]
    if not isinstance(refs, list):
        raise ValidationError("Saved pose workflow has invalid artifact references")
    updated = []
    for value in refs:
        if not isinstance(value, dict):
            raise ValidationError("Saved pose workflow has invalid artifact references")
        artifact_id = value.get("artifact_id")
        replacement = changes.get(artifact_id) if isinstance(artifact_id, str) else None
        if replacement is not None:
            _require(value.get("payload_sha256") in replacement, "workflow artifact checksum")
            value = {**value, "payload_sha256": replacement[1]}
        updated.append(value)
    return {**result, field: updated}


def _update_workflow_history(
    session: Session,
    parent: WorkflowRun,
    changes: list[tuple[WorkflowArtifact, WorkflowNodeRun, dict[str, Any]]],
) -> dict[str, str]:
    node_results: dict[str, tuple[WorkflowNodeRun, dict[str, Any]]] = {}
    by_artifact: dict[str, tuple[str, str]] = {}
    digests: dict[str, str] = {}
    for artifact, producer, payload in changes:
        new_digest = canonical_json_sha256(payload)
        by_artifact[artifact.id] = (artifact.payload_sha256, new_digest)
        digests[artifact.payload_sha256] = new_digest
        node_results.setdefault(producer.id, (producer, dict(producer.result_json or {})))
    for key, (node, result) in node_results.items():
        node_results[key] = (node, _update_artifact_refs(result, "outputs", by_artifact))
    result = _update_artifact_refs(dict(parent.result_json or {}), "artifacts", by_artifact)
    prior_provenance = result.get("provenance_manifest")
    prior_digest = result.get("provenance_sha256")
    if prior_provenance is not None or prior_digest is not None:
        _require(
            isinstance(prior_provenance, dict)
            and isinstance(prior_digest, str)
            and canonical_json_sha256(prior_provenance) == prior_digest,
            "workflow run provenance",
        )
    parent_job = session.get(Job, parent.job_id) if parent.job_id else None
    if parent_job is not None:
        _require(
            parent_job.project_id == parent.project_id
            and parent_job.job_type == "workflow_run"
            and parent_job.request_json.get("workflow_run_id") == parent.id,
            "parent workflow job identity",
        )
        parent_job_result = dict(parent_job.result_json or {})
        if "provenance_sha256" in parent_job_result:
            _require(
                parent_job_result["provenance_sha256"] == prior_digest,
                "parent workflow job provenance",
            )

    for artifact, _, payload in changes:
        artifact.payload_json = payload
        artifact.payload_sha256 = by_artifact[artifact.id][1]
    for node, summary in node_results.values():
        node.result_json = summary
    parent.result_json = result

    try:
        for node, _ in node_results.values():
            verify_succeeded_node_artifacts(session, run_id=parent.id, node_run=node)
        if isinstance(prior_digest, str):
            provenance = build_workflow_run_provenance(session, run_id=parent.id)
            new_digest = canonical_json_sha256(provenance)
            if prior_digest != new_digest:
                digests[prior_digest] = new_digest
            parent.result_json = {
                **result,
                "provenance_manifest": provenance,
                "provenance_sha256": new_digest,
            }
            if parent_job is not None and "provenance_sha256" in parent_job_result:
                parent_job.result_json = {**parent_job_result, "provenance_sha256": new_digest}
    except ConflictError as error:
        raise ValidationError(str(error)) from error
    return digests


def restore_pose_training_history(
    session: Session,
    run: TrainingRun,
    *,
    source_split_sha256: str,
    source_dataset_sha256: str,
    source_storage_root: str,
    target_storage_root: str,
) -> dict[str, str]:
    """Restore typed, locally bound evidence without touching source files or model bytes."""
    if run.task != "pose" or run.status != "completed":
        return {}
    split = run.artifact_manifest_json.get("pose_split_manifest")
    if not isinstance(split, dict) or not run.result_checkpoint_path:
        return {}
    project = session.get(Project, run.project_id)
    source_root = _managed_path(source_storage_root.rstrip("/"))
    target_root = _managed_path(target_storage_root.rstrip("/"))
    _require(
        project is not None
        and project.storage_root == target_root
        and _managed_path(run.result_checkpoint_path).startswith(target_root + "/"),
        "target project storage identity",
    )
    _require(
        _digest(source_split_sha256)
        and _digest(source_dataset_sha256)
        and canonical_json_sha256(split) == run.split_manifest_sha256
        and split.get("training_dataset_manifest_sha256") == run.dataset_manifest_sha256,
        "validated source and local split",
    )
    manifest = run.artifact_manifest_json
    selected_key = (
        "last_checkpoint_sha256"
        if PurePosixPath(run.result_checkpoint_path).name == "last.pt"
        else "best_checkpoint_sha256"
    )
    checkpoint_sha = manifest.get("result_checkpoint_sha256", manifest.get(selected_key))
    if not isinstance(checkpoint_sha, str) or not _digest(checkpoint_sha):
        raise ValidationError("Saved pose training lacks the selected checkpoint checksum")
    binding = _TrainingBinding(
        run,
        source_split_sha256,
        source_dataset_sha256,
        source_root,
        target_root,
        split,
        checkpoint_sha,
    )

    artifacts = session.scalars(
        select(WorkflowArtifact)
        .join(WorkflowRun, WorkflowRun.id == WorkflowArtifact.workflow_run_id)
        .where(
            WorkflowRun.project_id == run.project_id,
            or_(
                (WorkflowArtifact.data_type == "training_result")
                & (WorkflowArtifact.payload_json["training_run_id"].as_string() == run.id),
                (WorkflowArtifact.data_type == "model_reference")
                & (WorkflowArtifact.payload_json["source_training_run_id"].as_string() == run.id),
            ),
        )
    )
    updates: dict[str, list[tuple[WorkflowArtifact, WorkflowNodeRun, dict[str, Any]]]] = (
        defaultdict(list)
    )
    for artifact in artifacts:
        producer = session.get(WorkflowNodeRun, artifact.producer_node_run_id)
        training_result = artifact.data_type == "training_result"
        _require(
            producer is not None
            and artifact.workflow_run_id == producer.workflow_run_id
            and producer.status == "succeeded"
            and producer.node_type
            == ("pose_model_training" if training_result else "register_trained_model")
            and artifact.id in producer.output_artifact_ids_json,
            "producer identity",
        )
        assert producer is not None
        try:
            verify_workflow_artifact(artifact, expected_run_id=producer.workflow_run_id)
            verify_succeeded_node_artifacts(
                session, run_id=producer.workflow_run_id, node_run=producer
            )
        except ConflictError as error:
            raise ValidationError(str(error)) from error
        payload = artifact.payload_json
        if training_result:
            for field, expected in (
                ("workflow_run_id", producer.workflow_run_id),
                ("workflow_node_run_id", producer.id),
            ):
                if payload.get(field) is not None:
                    _require(payload[field] == expected, field)
            restored = binding.training_result(payload)
        else:
            _require(
                payload.get("project_id") == run.project_id
                and payload.get("task") == "pose"
                and payload.get("model_sha256") == checkpoint_sha,
                "registered model reference",
            )
            restored = binding.model_source(payload, checkpoint_field="model_sha256")
        if restored != payload:
            updates[artifact.workflow_run_id].append((artifact, producer, restored))

    models = session.scalars(
        select(ModelRegistration).where(
            ModelRegistration.project_id == run.project_id,
            ModelRegistration.metadata_json["source_training_run_id"].as_string() == run.id,
        )
    )
    model_updates = []
    for model in models:
        _require(
            model.task == "pose"
            and model.provider_name == run.provider_id
            and model.sha256 == checkpoint_sha,
            "registered model checkpoint",
        )
        model_updates.append(
            (
                model,
                binding.model_source(
                    model.metadata_json, checkpoint_field="source_checkpoint_sha256"
                ),
            )
        )
    child = session.get(Job, run.job_id) if run.job_id else None
    child_result = dict(child.result_json or {}) if child is not None else {}
    if child is not None and "result_checkpoint_path" in child_result:
        _require(
            child.project_id == run.project_id
            and child.job_type == "training"
            and child.request_json.get("training_run_id") == run.id,
            "child training job identity",
        )
        binding._path(child_result, "result_checkpoint_path", run.result_checkpoint_path)

    digests: dict[str, str] = {}
    for parent_id, changes in updates.items():
        parent = session.get(WorkflowRun, parent_id)
        assert parent is not None
        digests.update(_update_workflow_history(session, parent, changes))
    for model, metadata in model_updates:
        if metadata != model.metadata_json:
            model.metadata_json = metadata
    if child is not None and child_result and child_result != child.result_json:
        child.result_json = child_result
    return digests

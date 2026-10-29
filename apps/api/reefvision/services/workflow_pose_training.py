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
    PoseLandmarkSchema,
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
from reefvision.services.pose_training_datasets import frozen_pose_item_fingerprints_match
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
    # A connected artifact's explicit project identity is a provenance assertion.
    # Null must not be interpreted as an omitted project when replaying a graph.
    if "project_id" in payload and str(payload["project_id"]) != project_id:
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

    if dataset.status != "complete" or (dataset.item_count or 0) < 1:
        raise ValidationError(f"Pose {role} dataset must be complete and contain verified items")

    if not isinstance(dataset.manifest_json, dict):
        raise ValidationError(f"Pose {role} dataset manifest must be a JSON object")

    if canonical_json_sha256(dataset.manifest_json) != dataset.manifest_sha256:
        raise ValidationError(
            f"Pose {role} dataset manifest checksum no longer matches frozen truth"
        )

    manifest = dataset.manifest_json
    manifest_schema = manifest.get("pose_schema")
    if (
        manifest.get("dataset_id") != dataset.id
        or manifest.get("project_id") != dataset.project_id
        or manifest.get("source_round_id") != dataset.source_round_id
        or manifest.get("source_selection_sha256") != dataset.source_selection_sha256
        or manifest.get("source_retraining_manifest_sha256")
        != dataset.source_retraining_manifest_sha256
        or not isinstance(manifest_schema, dict)
        or manifest_schema.get("schema_id") != dataset.pose_schema_id
        or manifest_schema.get("schema_revision") != dataset.pose_schema_revision
        or manifest_schema.get("content_hash") != dataset.pose_schema_content_hash
    ):
        raise ValidationError(
            f"Pose {role} dataset manifest lineage no longer matches frozen truth"
        )

    if (
        dataset.manifest_json.get("truth_policy") != "scientist_verified_only"
        or dataset.manifest_json.get("skipped_candidates_included") is not False
        or dataset.manifest_json.get("pending_candidates_included") is not False
    ):
        raise ValidationError(
            f"Pose {role} dataset manifest must contain only scientist-verified items"
        )

    if (
        not isinstance(dataset.manifest_json.get("items"), list)
        or dataset.manifest_json.get("item_count") != dataset.item_count
        or len(dataset.manifest_json["items"]) != dataset.item_count
    ):
        raise ValidationError(f"Pose {role} dataset item count no longer matches frozen manifest")

    if not frozen_pose_item_fingerprints_match(session, dataset):
        raise ValidationError(
            f"Pose {role} dataset item fingerprints no longer match persisted frozen truth"
        )

    # The planner validates frozen truth, but the execution adapter must also
    # reject schema drift after planning or when invoked independently.
    schema = session.get(PoseLandmarkSchema, dataset.pose_schema_id)
    revision = session.scalar(
        select(PoseLandmarkSchemaRevision).where(
            PoseLandmarkSchemaRevision.schema_id == dataset.pose_schema_id,
            PoseLandmarkSchemaRevision.revision == dataset.pose_schema_revision,
        )
    )
    if (
        schema is None
        or schema.project_id != project_id
        or revision is None
        or revision.content_hash != dataset.pose_schema_content_hash
    ):
        raise ValidationError(f"Pose {role} dataset landmark schema no longer matches frozen truth")

    # An explicitly supplied checksum is a provenance assertion. Do not
    # treat false, zero, or a blank digest as if no assertion was supplied.
    if "manifest_sha256" in payload:
        advertised_manifest = payload["manifest_sha256"]
        if (
            not isinstance(advertised_manifest, str)
            or advertised_manifest != dataset.manifest_sha256
        ):
            raise ValidationError(f"Pose {role} dataset manifest no longer matches persisted truth")

    # Explicit source-round and active-learning digests are scientific
    # lineage assertions, even when the dataset ID and manifest still resolve.
    source_lineage_fields = (
        ("source_round_id", dataset.source_round_id),
        ("source_selection_sha256", dataset.source_selection_sha256),
        ("source_retraining_manifest_sha256", dataset.source_retraining_manifest_sha256),
    )
    if any(
        payload[field] != expected for field, expected in source_lineage_fields if field in payload
    ):
        raise ValidationError(
            f"Pose {role} dataset artifact source lineage no longer matches frozen truth"
        )

    # Downstream training must not silently accept a stale or substituted
    # landmark schema identity from a persisted Workflow Builder artifact.
    schema_fields = (
        "pose_schema_id",
        "pose_schema_revision",
        "pose_schema_content_hash",
    )
    if any(
        str(payload[field]) != str(getattr(dataset, field))
        for field in schema_fields
        if field in payload
    ):
        raise ValidationError(
            f"Pose {role} dataset artifact landmark schema metadata no longer matches frozen truth"
        )

    return dataset


def _seed_pose_model(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    payload: dict[str, Any],
    dataset: PoseTrainingDataset,
) -> ModelRegistration:
    # The model ID must resolve locally, but a persisted model-reference
    # artifact must also retain its explicitly asserted project lineage.
    if "project_id" in payload and payload["project_id"] != project_id:
        raise ValidationError("Pose retraining seed artifact project lineage changed")

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

    # A model-reference artifact may pin the original registered checkpoint.
    # Its digest is an explicit lineage assertion, not a hint to discard when
    # the model ID still resolves to an intact but different registration.
    for digest_field in ("sha256", "source_model_sha256", "model_sha256"):
        if digest_field in payload and payload[digest_field] != model.sha256:
            raise ValidationError("Pose retraining seed artifact checksum changed")

    # The actual registered_model_source node also pins the model's type and
    # provider. Reject altered metadata before using its local checkpoint.
    for metadata_field in ("purpose", "task", "provider_name", "provider_version"):
        if metadata_field in payload and payload[metadata_field] != getattr(model, metadata_field):
            raise ValidationError("Pose retraining seed artifact metadata changed")

    binding = session.get(
        PoseModelSchemaBinding,
        model.id,
    )

    if binding is None:
        raise ValidationError("Pose retraining seed requires a bound ReefVision landmark schema")

    # Matching keypoint definitions are not sufficient provenance: distinct
    # schema identities can have identical content hashes. Require the exact
    # frozen schema revision before using a locally registered checkpoint.
    if (
        binding.schema_id != dataset.pose_schema_id
        or binding.schema_revision != dataset.pose_schema_revision
    ):
        raise ValidationError(
            "Pose retraining seed landmark schema identity does not match frozen training dataset"
        )

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


def _completed_workflow_pose_training_run(
    session: Session,
    *,
    project_id: str,
    workflow_run_id: str | None,
    workflow_node_run_id: str | None,
    dataset: PoseTrainingDataset,
    validation_dataset: PoseTrainingDataset | None,
    split_manifest_sha256: str,
    seed_model: ModelRegistration | None,
    architecture: str,
    run_name: str,
    notes: str | None,
    device: str,
    precision: str,
    random_seed: int | None,
    training_config: dict[str, Any],
    resource_limits: dict[str, Any],
) -> TrainingRun | None:
    """Find completed child science created by this exact workflow node."""

    if not workflow_run_id or not workflow_node_run_id:
        return None

    candidates = list(
        session.scalars(
            select(TrainingRun)
            .where(
                TrainingRun.project_id == project_id,
                TrainingRun.task == "pose",
            )
            .order_by(
                TrainingRun.created_at.desc(),
                TrainingRun.id,
            )
        )
    )

    expected_validation_id = validation_dataset.id if validation_dataset is not None else None

    for candidate in candidates:
        snapshot = dict(candidate.draft_snapshot_json or {})

        if (
            str(snapshot.get("workflow_run_id") or "") != workflow_run_id
            or str(snapshot.get("workflow_node_run_id") or "") != workflow_node_run_id
        ):
            continue

        snapshot_version = snapshot.get("schema_version")
        if snapshot_version not in (None, "pose-workflow-training-snapshot-0001"):
            raise ValidationError("Recovered pose-training node snapshot schema changed")

        if (
            snapshot.get("pose_training_dataset_id") != dataset.id
            or snapshot.get("pose_validation_dataset_id") != expected_validation_id
        ):
            raise ValidationError("Recovered pose-training node dataset identity changed")

        # The frozen seed identity is scientific provenance, even when the
        # registered model and its bytes still validate independently.
        expected_seed_mode = "registered_model" if seed_model else "random"
        if (
            snapshot.get("initialization_mode") != expected_seed_mode
            or snapshot.get("seed_model_id") != (seed_model.id if seed_model else None)
            or snapshot.get("seed_model_sha256") != (seed_model.sha256 if seed_model else None)
        ):
            raise ValidationError("Recovered pose-training node seed provenance changed")

        # Replaying a completed node must preserve the frozen dataset digests
        # and exact landmark schema identity, not just its dataset IDs.
        if (
            snapshot.get("pose_training_dataset_manifest_sha256") != dataset.manifest_sha256
            or snapshot.get("pose_validation_dataset_manifest_sha256")
            != (validation_dataset.manifest_sha256 if validation_dataset else None)
            or snapshot.get("pose_schema_id") != dataset.pose_schema_id
            or snapshot.get("pose_schema_revision") != dataset.pose_schema_revision
            or snapshot.get("pose_schema_content_hash") != dataset.pose_schema_content_hash
            or not isinstance(snapshot.get("split_manifest"), dict)
            or canonical_json_sha256(snapshot["split_manifest"]) != split_manifest_sha256
        ):
            raise ValidationError("Recovered pose-training node frozen provenance changed")

        if candidate.split_manifest_sha256 != split_manifest_sha256:
            raise ValidationError("Recovered pose-training node split manifest changed")

        if candidate.dataset_manifest_sha256 != dataset.manifest_sha256:
            raise ValidationError("Recovered pose-training node dataset checksum changed")

        expected_validation_mode = (
            "separate_frozen_pose_dataset" if validation_dataset is not None else "none"
        )
        if (
            dict(candidate.evaluation_config_json or {}).get("validation_mode")
            != expected_validation_mode
        ):
            raise ValidationError("Recovered pose-training node validation mode changed")

        # The persisted run's seed source and asset identity are returned to
        # downstream science nodes. They must agree with the registered seed,
        # not merely its checkpoint ID and checksum.
        expected_checkpoint_source = "registered_model" if seed_model else "scratch"
        expected_seed_id = seed_model.id if seed_model else None
        expected_seed_sha256 = seed_model.sha256 if seed_model else None
        expected_model_asset_id = (
            f"registered_model:{seed_model.id}"
            if seed_model
            else f"builtin_architecture:{architecture}"
        )
        if (
            candidate.initial_checkpoint_source != expected_checkpoint_source
            or candidate.initial_checkpoint_model_id != expected_seed_id
            or candidate.resolved_model_asset_id != expected_model_asset_id
            or candidate.resolved_model_checksum != expected_seed_sha256
        ):
            raise ValidationError("Recovered pose-training seed model changed")

        if (
            candidate.provider_id != "ultralytics"
            or candidate.architecture != architecture
            or candidate.run_name != run_name
            or candidate.notes != notes
            or candidate.device != device
            or candidate.precision != precision
            or candidate.random_seed != random_seed
            or dict(candidate.training_config_json or {}) != training_config
            or dict(candidate.resource_limits_json or {}) != resource_limits
        ):
            raise ValidationError("Recovered pose-training node configuration changed")

        if candidate.status == "completed":
            return candidate

        # Workflow retries must not start a second training job while the
        # original child run is queued or executing. Failed/cancelled attempts
        # may be retried, but an active run still owns this workflow node.
        if candidate.status not in {"failed", "cancelled"}:
            raise ValidationError("Pose-training workflow node already has an active child run")

    return None


def _reused_pose_training_result(
    session: Session,
    settings: Settings,
    *,
    run: TrainingRun,
    dataset: PoseTrainingDataset,
    validation_dataset: PoseTrainingDataset | None,
    workflow_run_id: str | None,
    workflow_node_run_id: str | None,
    checkpoint_integrity: tuple[str, int] | None = None,
) -> dict[str, Any]:
    """Recreate the workflow artifact from a completed persisted pose run."""

    if run.job_id is None or not run.result_checkpoint_path:
        raise ValidationError("Recovered pose training is missing its completed job/checkpoint")

    job = session.get(
        Job,
        run.job_id,
    )

    if job is None or job.status != "succeeded" or run.status != "completed":
        raise ValidationError("Recovered pose training is not durably complete")

    # A completed child job must still belong to the training run's project.
    # Corrupted job ownership must never authorize replay of its checkpoint.
    if job.project_id != run.project_id:
        raise ValidationError("Recovered pose training job project ownership changed")

    # The completed child job must still identify this exact frozen training
    # run and saved workflow node. A substituted request cannot authorize
    # replay of another node's checkpoint, even within the same project.
    request = job.request_json
    expected_validation_id = validation_dataset.id if validation_dataset is not None else None
    if (
        job.job_type != "training"
        or not isinstance(request, dict)
        or request.get("training_run_id") != run.id
        or request.get("pose_training_dataset_id") != dataset.id
        or request.get("pose_validation_dataset_id") != expected_validation_id
        or request.get("created_by_workflow") is not True
        or request.get("workflow_run_id") != workflow_run_id
        or request.get("workflow_node_run_id") != workflow_node_run_id
    ):
        raise ValidationError("Recovered pose training child job lineage changed")

    checkpoint = resolve_managed_project_path(
        settings,
        run.result_checkpoint_path,
    )

    # A valid checksum alone cannot prove this model came from this training
    # run: a worker could point to another run's perfectly intact weights.
    project = session.get(Project, run.project_id)
    if project is None:
        raise ValidationError("Recovered pose training project is missing")
    expected_weights_dir = resolve_managed_project_path(
        settings,
        f"{project.storage_root}/training/{run.id}/runs/pose/weights",
    )
    if checkpoint.resolve().parent != expected_weights_dir.resolve():
        raise ValidationError("Recovered pose training checkpoint belongs to another output")
    if checkpoint.name not in {"best.pt", "last.pt"}:
        raise ValidationError("Recovered pose training checkpoint belongs to another output")

    # Downstream nodes also receive the worker's best/last checkpoint paths.
    # A valid result checkpoint cannot authorize unrelated model artifacts
    # advertised through that same scientific provenance manifest.
    artifact_manifest = dict(run.artifact_manifest_json or {})
    for field, filename in (
        ("best_checkpoint_path", "best.pt"),
        ("last_checkpoint_path", "last.pt"),
    ):
        advertised = artifact_manifest.get(field)
        if advertised is None:
            continue
        if not isinstance(advertised, str):
            raise ValidationError("Recovered pose-training checkpoint artifact path changed")
        advertised_checkpoint = resolve_managed_project_path(settings, advertised)
        if (
            advertised_checkpoint.resolve() != (expected_weights_dir / filename).resolve()
            or not advertised_checkpoint.is_file()
        ):
            raise ValidationError(
                "Recovered pose-training checkpoint artifact path changed or is missing"
            )

    if not checkpoint.is_file():
        raise ValidationError("Recovered pose training checkpoint is missing")

    # First completion has already hashed these bytes while persisting the
    # checkpoint digest. Reuse that result rather than hashing large weights
    # twice; completed-node retries always rehash the on-disk checkpoint.
    checkpoint_sha256, checkpoint_size = (
        checkpoint_integrity if checkpoint_integrity is not None else hash_model_file(checkpoint)
    )

    # Completed workflow retries must not silently relabel changed model bytes
    # as the original scientific result. Legacy runs without a recorded digest
    # remain readable; newly completed runs always persist one below.
    frozen_checkpoint = dict(run.artifact_manifest_json or {})
    # This manifest is returned to downstream workflow nodes. Verify its
    # dataset and split lineage against the already-validated frozen snapshot.
    expected_artifact_lineage = {
        "pose_training_dataset_id": dataset.id,
        "pose_validation_dataset_id": (
            validation_dataset.id if validation_dataset is not None else None
        ),
        "pose_schema_id": dataset.pose_schema_id,
        "pose_schema_revision": dataset.pose_schema_revision,
        "pose_schema_content_hash": dataset.pose_schema_content_hash,
        "pose_split_manifest_sha256": run.split_manifest_sha256,
    }
    if any(frozen_checkpoint.get(key) != value for key, value in expected_artifact_lineage.items()):
        raise ValidationError("Recovered pose-training artifact provenance changed")
    if frozen_checkpoint.get("pose_split_manifest") != dict(run.draft_snapshot_json or {}).get(
        "split_manifest"
    ):
        raise ValidationError("Recovered pose-training artifact provenance changed")

    expected_sha256 = frozen_checkpoint.get("result_checkpoint_sha256")
    expected_path = frozen_checkpoint.get("result_checkpoint_path")
    # New workflow-created training runs always persist both fields. Missing
    # metadata must not turn a verified checkpoint into an unchecked legacy
    # replay; only older snapshots may use the backwards-compatible fallback.
    snapshot = dict(run.draft_snapshot_json or {})
    is_current_snapshot = (
        snapshot.get("schema_version") == "pose-workflow-training-snapshot-0001"
        or "pose_training_dataset_manifest_sha256" in snapshot
    )
    if is_current_snapshot and (
        not isinstance(expected_sha256, str)
        or not expected_sha256
        or not isinstance(expected_path, str)
        or not expected_path
    ):
        raise ValidationError("Recovered pose-training checkpoint provenance is missing")
    if expected_sha256 is not None and expected_sha256 != checkpoint_sha256:
        raise ValidationError("Recovered pose-training checkpoint checksum changed")
    if expected_path is not None and expected_path != run.result_checkpoint_path:
        raise ValidationError("Recovered pose-training checkpoint path changed")

    experiment = session.scalar(
        select(ExperimentRecord).where(ExperimentRecord.training_run_id == run.id)
    )

    validation_mode = str(dict(run.evaluation_config_json or {}).get("validation_mode") or "none")

    return {
        "schema_version": ("workflow-training-result-0001"),
        "project_id": run.project_id,
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
        "validation_mode": (validation_mode),
        "task": run.task,
        "provider_id": run.provider_id,
        "architecture": run.architecture,
        "initialization_mode": (
            "registered_model" if run.initial_checkpoint_model_id else "random"
        ),
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


def create_pose_workflow_training_result(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    dataset_payload: dict[str, Any],
    initial_model_payload: dict[str, Any] | None = None,
    parameters: dict[str, Any],
    validation_dataset_payload: dict[str, Any] | None = None,
    workflow_run_id: str | None = None,
    workflow_node_run_id: str | None = None,
    processor: PoseTrainingProcessor = process_pose_training_job,
) -> dict[str, Any]:
    """Execute real Ultralytics pose retraining from immutable verified truth."""

    # A saved workflow must identify both its run and its node. Accepting a
    # partial or blank identity would create a training job without durable
    # node-level provenance and bypass completed-node replay protection.
    if (workflow_run_id is None) != (workflow_node_run_id is None) or (
        workflow_run_id is not None
        and (
            not isinstance(workflow_run_id, str)
            or not workflow_run_id.strip()
            or not isinstance(workflow_node_run_id, str)
            or not workflow_node_run_id.strip()
        )
    ):
        raise ValidationError("Pose training workflow lineage requires both non-blank IDs")

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

    # Distinct frozen records are not independent validation truth if they
    # contain frames from the same source video (even different frames/tracks).
    if validation_dataset is not None:
        training_videos = {str(item["video_sha256"]) for item in dataset.manifest_json["items"]}
        validation_videos = {
            str(item["video_sha256"]) for item in validation_dataset.manifest_json["items"]
        }
        if training_videos & validation_videos:
            raise ValidationError("Pose validation dataset must use independent source videos")

    # Matching landmark definitions do not establish identical scientific
    # schema lineage: two reviewed schemas can share a content hash while
    # representing different identities or revisions.
    if validation_dataset is not None and (
        validation_dataset.pose_schema_id != dataset.pose_schema_id
        or validation_dataset.pose_schema_revision != dataset.pose_schema_revision
        or validation_dataset.pose_schema_content_hash != dataset.pose_schema_content_hash
    ):
        raise ValidationError(
            "Pose validation dataset must use the same landmark schema identity "
            "and revision as training truth"
        )

    # A truthy string such as "false" must not silently change whether
    # independent scientist-verified validation data is required.
    require_validation = parameters.get("require_validation_dataset", False)
    if not isinstance(require_validation, bool):
        raise ValidationError("Pose require_validation_dataset must be a boolean")

    if require_validation and validation_dataset is None:
        raise ValidationError(
            "This pose retraining configuration requires a separate frozen validation dataset"
        )

    # The planner's explicit "auto" default resolves from the connected
    # seed artifact; an explicit null/falsy mode remains invalid.
    requested_mode = parameters.get("initialization_mode", "auto")
    if not isinstance(requested_mode, str) or not requested_mode:
        raise ValidationError("Pose initialization_mode must be random or registered_model")
    if requested_mode == "auto":
        initialization_mode = "registered_model" if initial_model_payload is not None else "random"
    else:
        initialization_mode = requested_mode
    if initialization_mode not in {"random", "registered_model"}:
        raise ValidationError("Pose initialization_mode must be random or registered_model")
    if initialization_mode == "random" and initial_model_payload is not None:
        raise ValidationError("Random initialization cannot use an initial model")
    seed_model = (
        _seed_pose_model(
            session,
            settings,
            project_id=project_id,
            payload=initial_model_payload or {},
            dataset=dataset,
        )
        if initialization_mode == "registered_model"
        else None
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

    # An omitted config uses defaults; an explicit null is not a valid
    # saved scientific configuration and must not silently become defaults.
    if not isinstance(
        supplied_config,
        dict,
    ):
        raise ValidationError("Pose training_config must be an object")

    # Never silently reinterpret a scientist's explicit validation setting.
    # Only a separate frozen, verified dataset can authorize validation.
    if "val" in supplied_config and (
        not isinstance(supplied_config["val"], bool)
        or supplied_config["val"] != (validation_dataset is not None)
    ):
        raise ValidationError(
            "Pose training_config.val must match the separate frozen validation dataset"
        )

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

    metadata = dict(seed_model.metadata_json or {}) if seed_model else {}

    # An explicitly supplied architecture is part of the training lineage.
    # Never turn False, zero, or an empty container into a default model.
    if "architecture" in parameters:
        requested_architecture = parameters["architecture"]
        if not isinstance(requested_architecture, str) or not requested_architecture.strip():
            raise ValidationError("Pose training architecture must be a non-blank string")
        architecture = requested_architecture.strip()
    else:
        architecture = str(
            metadata.get("source_architecture")
            or (seed_model.source_filename if seed_model else "yolo11n-pose.yaml")
        ).strip()

    if seed_model is None and architecture not in {f"yolo11{scale}-pose.yaml" for scale in "nslmx"}:
        raise ValidationError("Random pose training requires a YOLO11 n/s/m/l/x pose architecture")

    # An explicit falsy or non-string name must not silently become a
    # different persisted training identity on a saved workflow replay.
    requested_run_name = parameters.get("run_name")
    if requested_run_name is None:
        run_name = "workflow-pose-retrain"
    elif not isinstance(requested_run_name, str):
        raise ValidationError("Pose training run_name must be a string")
    else:
        run_name = requested_run_name.strip()

    if not run_name:
        raise ValidationError("Pose training run_name cannot be blank")

    # Notes are persisted experiment context; changing them must not reuse
    # an earlier completed workflow node under a different scientific label.
    requested_notes = parameters.get("notes")
    if requested_notes is None:
        notes = None
    elif not isinstance(requested_notes, str):
        raise ValidationError("Pose training notes must be a string or null")
    else:
        notes = requested_notes.strip() or None

    # Device selection is persisted as experimental configuration. Reject
    # lossy string coercion before queuing a GPU job or recording its lineage.
    requested_device = parameters.get("device", "auto")
    if not isinstance(requested_device, str) or not requested_device.strip():
        raise ValidationError("Pose training device must be a non-blank string")
    device = requested_device.strip()

    # Ultralytics also accepts a seed in training_config. When no top-level
    # seed is supplied, persist that effective seed in the training run rather
    # than recording null while the worker trains with a different value.
    configured_seed_supplied = "seed" in supplied_config
    # A coerced boolean, fractional float, or negative seed changes the
    # scientist's requested random state (or can crash before a job exists).
    # Preserve the legacy decimal-string input without silently truncating it.
    raw_seed = parameters.get("random_seed")
    if raw_seed is None and configured_seed_supplied:
        raw_seed = supplied_config["seed"]
    if raw_seed is None:
        random_seed = None
    elif isinstance(raw_seed, bool) or not (
        isinstance(raw_seed, int)
        or (
            isinstance(raw_seed, str)
            and raw_seed.strip().isascii()
            and raw_seed.strip().isdecimal()
        )
    ):
        raise ValidationError("Pose training random_seed must be a non-negative integer")
    else:
        # SQLite stores signed 64-bit integers. Reject out-of-range seeds
        # before creating a run instead of failing at persistence time.
        try:
            random_seed = int(raw_seed)
        except ValueError as exc:
            raise ValidationError(
                "Pose training random_seed must be a non-negative integer"
            ) from exc
        if not 0 <= random_seed <= (2**63 - 1):
            raise ValidationError("Pose training random_seed must be a non-negative integer")

    # A conflicting second seed would make the saved scientific configuration
    # disagree with the actual worker invocation (which uses random_seed).
    if configured_seed_supplied and supplied_config["seed"] != random_seed:
        raise ValidationError("Pose training_config.seed must match random_seed")

    # Missing limits use the unrestricted default, but an explicit null in
    # a saved workflow must not silently discard its resource policy.
    resource_limits = parameters.get("resource_limits", {})
    if not isinstance(resource_limits, dict):
        raise ValidationError("Pose training resource_limits must be an object")
    resource_limits = dict(resource_limits)

    warning_list: list[str] = []

    if validation_dataset is None:
        warning_list.append(
            "No separate frozen validation dataset was supplied. "
            "Validation is disabled and training metrics must not be "
            "reported as independent validation performance."
        )

    existing_completed_run = _completed_workflow_pose_training_run(
        session,
        project_id=project_id,
        workflow_run_id=(workflow_run_id),
        workflow_node_run_id=(workflow_node_run_id),
        dataset=dataset,
        validation_dataset=(validation_dataset),
        split_manifest_sha256=(split_manifest_sha256),
        seed_model=seed_model,
        architecture=architecture,
        run_name=run_name,
        notes=notes,
        device=device,
        precision=precision,
        random_seed=random_seed,
        training_config=(training_config),
        resource_limits=resource_limits,
    )

    if existing_completed_run is not None:
        return _reused_pose_training_result(
            session,
            settings,
            run=existing_completed_run,
            dataset=dataset,
            validation_dataset=(validation_dataset),
            workflow_run_id=(workflow_run_id),
            workflow_node_run_id=(workflow_node_run_id),
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
        initial_checkpoint_source=("registered_model" if seed_model else "scratch"),
        initial_checkpoint_model_id=(seed_model.id if seed_model else None),
        resolved_model_asset_id=(
            f"registered_model:{seed_model.id}"
            if seed_model
            else f"builtin_architecture:{architecture}"
        ),
        resolved_model_checksum=(seed_model.sha256 if seed_model else None),
        parameter_registry_version=(provider_spec("ultralytics").provider_version),
        selected_preset=None,
        installation_state="ready",
        device=device,
        precision=precision,
        run_name=run_name,
        notes=notes,
        random_seed=random_seed,
        tiling_config_json={"mode": "none"},
        training_config_json=(training_config),
        tuning_config_json={"mode": "disabled"},
        evaluation_config_json={"validation_mode": (split_manifest["validation_mode"])},
        resource_limits_json=resource_limits,
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
            "initialization_mode": initialization_mode,
            "seed_model_id": (seed_model.id if seed_model else None),
            "seed_model_sha256": (seed_model.sha256 if seed_model else None),
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

    # A worker must not replace the queued child job with another successful
    # job, even if its request claims the same workflow and training run.
    if run.job_id != job.id:
        raise ValidationError("Completed pose training child job identity changed")

    if job.status != "succeeded" or run.status != "completed":
        detail = run.error_message or job.error_message or (f"job={job.status}, run={run.status}")

        raise ValidationError("Pose training child job failed: " + detail)

    # First execution must verify the same persisted child-job lineage as
    # checkpoint reuse. A worker must not substitute another workflow node's
    # successful job and expose its model as this node's scientific result.
    request = job.request_json
    if (
        job.project_id != project_id
        or job.job_type != "training"
        or not isinstance(request, dict)
        or request.get("training_run_id") != run.id
        or request.get("pose_training_dataset_id") != dataset.id
        or request.get("pose_validation_dataset_id")
        != (validation_dataset.id if validation_dataset is not None else None)
        or request.get("created_by_workflow") is not True
        or request.get("workflow_run_id") != workflow_run_id
        or request.get("workflow_node_run_id") != workflow_node_run_id
    ):
        raise ValidationError("Completed pose training child job lineage changed")

    # Validate the persisted run itself before first exposing its checkpoint.
    # A worker can change training configuration after the job was queued;
    # replay validation already rejects that drift, so first completion must too.
    if workflow_run_id and workflow_node_run_id:
        recovered = _completed_workflow_pose_training_run(
            session,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
            dataset=dataset,
            validation_dataset=validation_dataset,
            split_manifest_sha256=split_manifest_sha256,
            seed_model=seed_model,
            architecture=architecture,
            run_name=run_name,
            notes=notes,
            device=device,
            precision=precision,
            random_seed=random_seed,
            training_config=training_config,
            resource_limits=resource_limits,
        )
        if recovered is None or recovered.id != run.id:
            raise ValidationError("Completed pose training run lineage changed")

    # The worker ran after frozen-truth preflight. Recheck the persisted
    # scientist-reviewed rows before returning the checkpoint: a worker or
    # concurrent writer must not mutate verified landmarks/review evidence
    # after training was queued and still expose the result as frozen truth.
    _pose_dataset(
        session,
        project_id=project_id,
        payload={"dataset_id": dataset.id, "manifest_sha256": dataset.manifest_sha256},
        role="training",
    )
    if validation_dataset is not None:
        _pose_dataset(
            session,
            project_id=project_id,
            payload={
                "dataset_id": validation_dataset.id,
                "manifest_sha256": validation_dataset.manifest_sha256,
            },
            role="validation",
        )

    # The registered seed was verified before launching the worker. Recheck
    # its local bytes and schema binding after training: a concurrent change
    # must not be published as reproducible checkpoint lineage.
    if seed_model is not None:
        _seed_pose_model(
            session,
            settings,
            project_id=project_id,
            payload={"model_id": seed_model.id, "sha256": seed_model.sha256},
            dataset=dataset,
        )

    if not run.result_checkpoint_path:
        raise ValidationError("Completed pose training did not produce a checkpoint")

    checkpoint = resolve_managed_project_path(
        settings,
        run.result_checkpoint_path,
    )

    if not checkpoint.is_file():
        raise ValidationError("Completed pose training checkpoint is missing")

    checkpoint_sha256, checkpoint_size = hash_model_file(checkpoint)

    # A worker may have already recorded a checkpoint identity. Do not
    # overwrite conflicting evidence when finalizing a saved workflow node.
    # Otherwise first completion could conceal an altered worker manifest,
    # while a subsequent replay would appear to have valid provenance.
    worker_manifest = dict(run.artifact_manifest_json or {})
    if (
        "result_checkpoint_sha256" in worker_manifest
        and worker_manifest["result_checkpoint_sha256"] != checkpoint_sha256
    ):
        raise ValidationError("Completed pose training worker checkpoint checksum changed")
    if (
        "result_checkpoint_path" in worker_manifest
        and worker_manifest["result_checkpoint_path"] != run.result_checkpoint_path
    ):
        raise ValidationError("Completed pose training worker checkpoint path changed")

    # Bind the completed training result to its on-disk checkpoint so a
    # retried Workflow Builder node cannot reuse different model weights.
    run.artifact_manifest_json = {
        **worker_manifest,
        "result_checkpoint_path": run.result_checkpoint_path,
        "result_checkpoint_sha256": checkpoint_sha256,
    }
    session.commit()

    # Apply the same persisted child-job, frozen-artifact, and checkpoint
    # provenance checks on first completion as on a saved-workflow retry.
    # Never expose a worker-mutated manifest to downstream science nodes.
    return _reused_pose_training_result(
        session,
        settings,
        run=run,
        dataset=dataset,
        validation_dataset=validation_dataset,
        workflow_run_id=workflow_run_id,
        workflow_node_run_id=workflow_node_run_id,
        checkpoint_integrity=(checkpoint_sha256, checkpoint_size),
    )


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

    initial_model = _optional_payload(
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


def execute_pose_training_dataset_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    dataset = _pose_dataset(session, project_id=project_id, payload=parameters, role="training")
    return [
        {
            "port_id": "dataset",
            "data_type": "pose_training_dataset",
            "payload": {
                "project_id": project_id,
                "dataset_id": dataset.id,
                "manifest_sha256": dataset.manifest_sha256,
                "source_round_id": dataset.source_round_id,
                "source_selection_sha256": dataset.source_selection_sha256,
                "source_retraining_manifest_sha256": dataset.source_retraining_manifest_sha256,
                "pose_schema_id": dataset.pose_schema_id,
                "pose_schema_revision": dataset.pose_schema_revision,
                "pose_schema_content_hash": dataset.pose_schema_content_hash,
            },
        }
    ]


_POSE_TRAINING_ADAPTERS = {
    "pose_training_dataset": execute_pose_training_dataset_adapter,
    "pose_model_training": (execute_pose_model_training_adapter),
}


def register_pose_training_workflow_adapter() -> None:
    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.update(_POSE_TRAINING_ADAPTERS)

    runtime_adapters._ADAPTERS.update(_POSE_TRAINING_ADAPTERS)

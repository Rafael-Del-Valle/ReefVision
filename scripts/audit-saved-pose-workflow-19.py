#!/usr/bin/env python3
"""Audit one EXISTING, completed pose Workflow Builder run without writing data.

This is a manual scientific acceptance gate, not a synthetic CI fixture.
A PASS requires a saved run, reviewed frozen truth, finished training, a
checkpoint, and a registered local model whose actual file digests match.
It does not certify the Windows installer or GPU hardware independently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _digest(path: Path) -> str:
    hash_value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hash_value.update(chunk)
    return hash_value.hexdigest()


def _managed_file(root: Path, value: str) -> Path:
    _require(isinstance(value, str) and bool(value), "Missing local checkpoint path")
    candidate = Path(value)
    _require(".." not in candidate.parts, "Evidence path must not traverse parent directories")
    unresolved = candidate if candidate.is_absolute() else root / candidate
    _require(unresolved.is_relative_to(root), "Checkpoint escapes the selected data directory")
    # Check each original path component *before* resolve() follows redirects.
    # A symlink or NTFS junction inside the managed root can alias a different
    # run's checkpoint while retaining a valid digest, hiding broken lineage.
    current = root
    for part in unresolved.relative_to(root).parts:
        current = current / part
        metadata = current.lstat()
        _require(
            not current.is_symlink()
            and not (getattr(metadata, "st_file_attributes", 0) & 0x400),
            "Evidence path contains a symlink or Windows reparse point",
        )
    resolved = unresolved.resolve(strict=True)
    _require(resolved.is_file(), "Checkpoint is not a regular file")
    _require(resolved.is_relative_to(root), "Checkpoint escapes the selected data directory")
    return resolved


def inspect(db: Path, run_id: str, data_dir: Path) -> dict[str, Any]:
    # The app imports are delayed so the script works from a source checkout.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import Session

    from reefvision.db.models import (
        ExperimentRecord,
        Job,
        ModelRegistration,
        PoseLandmarkSchemaRevision,
        PoseModelSchemaBinding,
        PoseTrainingDataset,
        Project,
        TrainingRun,
        VideoAsset,
        WorkflowArtifact,
        WorkflowNodeRun,
        WorkflowRun,
    )
    from reefvision.services.pose_training_datasets import PoseTrainingDatasetService
    from reefvision.services.workflow_provenance import build_workflow_run_provenance
    from reefvision.storage.datasets import canonical_json_sha256

    _require(db.is_file(), "An existing local SQLite database is required")
    _require(data_dir.is_dir(), "An existing model and checkpoint data directory is required")
    root = data_dir.resolve(strict=True)

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(db.resolve(strict=True).as_uri() + "?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        return connection

    engine = create_engine("sqlite://", creator=connect)

    # This audit compares several independently persisted scientific records.
    # A SQLAlchemy Session alone does not pin SQLite SELECTs to one snapshot
    # under the sqlite3 legacy transaction mode. Start a real read transaction
    # when the Session begins so concurrent app writes cannot mix revisions.
    @event.listens_for(engine, "begin")
    def begin_snapshot(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    try:
        with Session(engine) as session:
            run = session.get(WorkflowRun, run_id)
            _require(run is not None and run.status == "succeeded", "Saved run did not succeed")
            # The durable parent job proves that this saved graph was executed
            # by the workflow worker for this project, not only marked succeeded.
            parent_job = session.get(Job, run.job_id)
            _require(
                parent_job is not None
                and parent_job.project_id == run.project_id
                and parent_job.job_type == "workflow_run"
                and parent_job.status == "succeeded"
                and isinstance(parent_job.request_json, dict)
                and parent_job.request_json.get("workflow_run_id") == run.id,
                "Saved workflow parent job does not match the completed execution",
            )
            # Reuse the app's checksum, node-graph, artifact and closeout validators.
            provenance = build_workflow_run_provenance(session, run_id=run_id)
            _require(bool(provenance), "Saved workflow provenance is missing")

            nodes = session.scalars(
                select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
            ).all()
            producers = {node.id: node for node in nodes}
            artifacts = session.scalars(
                select(WorkflowArtifact).where(WorkflowArtifact.workflow_run_id == run_id)
            ).all()

            def one(node_type: str, data_type: str) -> dict[str, Any]:
                matches = [
                    artifact.payload_json
                    for artifact in artifacts
                    if artifact.data_type == data_type
                    and artifact.producer_node_run_id in producers
                    and producers[artifact.producer_node_run_id].node_type == node_type
                ]
                _require(len(matches) == 1, f"Expected exactly one {node_type} output")
                _require(isinstance(matches[0], dict), "Output is not a JSON object")
                return matches[0]

            frozen = one("pose_training_dataset", "pose_training_dataset")
            result = one("pose_model_training", "training_result")
            registered = one("register_trained_model", "model_reference")

            dataset = session.get(PoseTrainingDataset, frozen.get("dataset_id"))
            _require(dataset is not None, "Frozen pose training dataset was not found")
            _require(
                dataset.project_id == run.project_id,
                "Frozen dataset belongs to another project",
            )
            _require(
                frozen.get("manifest_sha256") == dataset.manifest_sha256,
                "Workflow dataset manifest fingerprint changed",
            )
            # Performs the app's deep verification of human review, frozen
            # canonical poses, source model/job identities and signed summaries.
            PoseTrainingDatasetService(session).manifest(dataset.id)

            training = session.get(TrainingRun, result.get("training_run_id"))
            _require(
                training is not None and training.status == "completed",
                "Training is incomplete",
            )
            _require(training.task == "pose", "Training result is not a pose model")
            _require(training.project_id == run.project_id, "Training belongs to another project")
            _require(result.get("workflow_run_id") == run_id, "Training run provenance changed")
            _require(
                result.get("pose_training_dataset_id") == dataset.id,
                "Training used another dataset",
            )
            # TrainingRun has its own canonical dataset digest, independent
            # of the pose-specific worker artifact manifest. Both must name
            # the same scientist-reviewed frozen source at acceptance.
            _require(
                training.dataset_manifest_sha256 == dataset.manifest_sha256,
                "Training run dataset digest differs from frozen pose truth",
            )
            _require(
                training.artifact_manifest_json.get("pose_training_dataset_manifest_sha256")
                == dataset.manifest_sha256,
                "Training's frozen dataset digest is missing or mismatched",
            )
            # Training and registration must use the identical frozen anatomy
            # and split contract. A matching training-dataset ID alone cannot
            # prove landmark ordering or the held-out evaluation partition.
            manifest = training.artifact_manifest_json
            _require(
                type(result.get("pose_schema_revision")) is int
                and result.get("pose_schema_id") == dataset.pose_schema_id
                and result.get("pose_schema_revision") == dataset.pose_schema_revision
                and result.get("pose_schema_content_hash") == dataset.pose_schema_content_hash
                and manifest.get("pose_schema_id") == dataset.pose_schema_id
                and manifest.get("pose_schema_revision") == dataset.pose_schema_revision
                and manifest.get("pose_schema_content_hash") == dataset.pose_schema_content_hash
                and result.get("split_manifest_sha256") == training.split_manifest_sha256
                and manifest.get("pose_split_manifest_sha256") == training.split_manifest_sha256
                and isinstance(manifest.get("pose_split_manifest"), dict)
                and canonical_json_sha256(manifest["pose_split_manifest"])
                == training.split_manifest_sha256,
                "Pose anatomy or train/validation split no longer matches frozen training",
            )
            validation_id = result.get("pose_validation_dataset_id")
            _require(
                validation_id == manifest.get("pose_validation_dataset_id"),
                "Saved validation dataset differs from completed training",
            )
            # A completed pose worker runs with AMP disabled and controls
            # validation exclusively from a separate frozen dataset. Check
            # effective persisted settings, not only the split manifest:
            # otherwise the audit could certify scores from an altered run
            # claiming AMP or independent validation it never performed.
            expected_validation_mode = (
                "separate_frozen_pose_dataset" if validation_id is not None else "none"
            )
            _require(
                training.precision == "fp32"
                and isinstance(training.training_config_json, dict)
                and training.training_config_json.get("amp") is False
                and type(training.training_config_json.get("val")) is bool
                and training.training_config_json["val"] == (validation_id is not None)
                and isinstance(training.evaluation_config_json, dict)
                and training.evaluation_config_json.get("validation_mode")
                == expected_validation_mode,
                "Effective pose precision or independent validation policy changed",
            )
            if validation_id is not None:
                validation_dataset = session.get(PoseTrainingDataset, validation_id)
                _require(
                    validation_dataset is not None
                    and validation_dataset.project_id == run.project_id
                    and validation_dataset.pose_schema_id == dataset.pose_schema_id
                    and validation_dataset.pose_schema_revision == dataset.pose_schema_revision
                    and validation_dataset.pose_schema_content_hash
                    == dataset.pose_schema_content_hash,
                    "Saved validation dataset is missing, foreign, or anatomically incompatible",
                )
                PoseTrainingDatasetService(session).manifest(validation_id)
                # Match the production pose-workflow training contract: a
                # validation dataset must be distinct and share *no source
                # videos*, even when the selected frame indices differ.
                # Frame-only comparison misses correlated adjacent frames.
                _require(
                    validation_id != dataset.id,
                    "Validation dataset is the training dataset",
                )
                train_items = dataset.manifest_json["items"]
                validation_items = validation_dataset.manifest_json["items"]
                _require(
                    {item["video_id"] for item in train_items}.isdisjoint(
                        {item["video_id"] for item in validation_items}
                    )
                    and {item["video_sha256"] for item in train_items}.isdisjoint(
                        {item["video_sha256"] for item in validation_items}
                    ),
                    "Separate frozen validation dataset reuses source video identity or content",
                )
            # The split digest alone only proves internal consistency. Rebuild
            # the production split contract from independently verified rows
            # so a rehashed manifest cannot silently misstate its inputs.
            expected_split = {
                "schema_version": "pose-training-split-0001",
                "training_dataset_id": dataset.id,
                "training_dataset_manifest_sha256": dataset.manifest_sha256,
                "validation_dataset_id": validation_id,
                "validation_dataset_manifest_sha256": (
                    validation_dataset.manifest_sha256 if validation_id is not None else None
                ),
                "validation_mode": expected_validation_mode,
                "pose_schema_id": dataset.pose_schema_id,
                "pose_schema_revision": dataset.pose_schema_revision,
                "pose_schema_content_hash": dataset.pose_schema_content_hash,
            }
            _require(
                manifest["pose_split_manifest"] == expected_split
                and result.get("validation_mode") == expected_validation_mode,
                "Frozen split manifest or result misstates the verified scientific inputs",
            )
            # A frozen pose manifest proves what videos were reviewed, not
            # that the original media still exists or has the recorded bytes.
            # Hash each unique training/held-out source once. Missing or
            # modified footage cannot pass real scientific acceptance even
            # when database snapshots and model checkpoints still agree.
            video_digests: dict[str, str] = {}
            verified_source_bytes = 0
            source_items = dataset.manifest_json["items"] + (
                validation_dataset.manifest_json["items"] if validation_id is not None else []
            )
            for source_item in source_items:
                video_id = source_item["video_id"]
                expected_video_sha = source_item["video_sha256"]
                _require(
                    video_digests.get(video_id, expected_video_sha) == expected_video_sha,
                    "Frozen datasets disagree on a source video's checksum",
                )
                if video_id in video_digests:
                    continue
                source_video = session.get(VideoAsset, video_id)
                _require(
                    source_video is not None
                    and source_video.project_id == run.project_id
                    and source_video.sha256 == expected_video_sha,
                    "Frozen source video registration no longer matches saved truth",
                )
                video_file = _managed_file(root, source_video.managed_path)
                video_size = video_file.stat().st_size
                _require(
                    video_size > 0 and _digest(video_file) == expected_video_sha,
                    "Frozen source video bytes are missing or changed",
                )
                video_digests[video_id] = expected_video_sha
                verified_source_bytes += video_size
            job = session.get(Job, training.job_id)
            _require(
                job is not None and job.status == "succeeded",
                "Pose training job did not succeed",
            )
            # Check the actual queued worker request independently of the
            # checksum-valid Workflow Builder artifact: a succeeded job from
            # another node or frozen dataset cannot prove this experiment.
            training_nodes = [node for node in nodes if node.node_type == "pose_model_training"]
            _require(len(training_nodes) == 1, "Saved pose training node is ambiguous")
            training_node_id = training_nodes[0].id
            request = job.request_json
            _require(
                job.project_id == run.project_id
                and job.job_type == "training"
                and isinstance(request, dict)
                and request.get("created_by_workflow") is True
                and request.get("workflow_run_id") == run_id
                and request.get("workflow_node_run_id") == training_node_id
                and request.get("training_run_id") == training.id
                and request.get("pose_training_dataset_id") == dataset.id
                and request.get("pose_training_dataset_manifest_sha256") == dataset.manifest_sha256
                and result.get("workflow_node_run_id") == training_node_id
                and result.get("training_job_id") == job.id,
                "Saved pose-training job request or producer lineage changed",
            )
            # The queued child job independently pins the held-out dataset and
            # split. The draft also fingerprints the *entire* submitted request,
            # protecting scientific settings beyond the three dataset digests.
            _require(
                request.get("pose_validation_dataset_id") == validation_id
                and request.get("pose_validation_dataset_manifest_sha256")
                == (validation_dataset.manifest_sha256 if validation_id is not None else None)
                and request.get("pose_split_manifest_sha256") == training.split_manifest_sha256,
                "Queued training job disagrees with frozen validation or split lineage",
            )
            snapshot = training.draft_snapshot_json
            _require(
                isinstance(snapshot, dict)
                and isinstance(snapshot.get("pose_child_job_request_sha256"), str)
                and canonical_json_sha256(request) == snapshot["pose_child_job_request_sha256"],
                "Queued training job request differs from its frozen fingerprint",
            )
            # Independently reconcile the original queued snapshot with the
            # saved workflow and worker manifest. Checksum-valid job requests
            # cannot establish that the separately persisted training draft
            # still describes the same frozen truth and validation partition.
            _require(
                snapshot.get("workflow_run_id") == run_id
                and snapshot.get("workflow_node_run_id") == training_node_id
                and snapshot.get("pose_training_dataset_id") == dataset.id
                and snapshot.get("pose_training_dataset_manifest_sha256")
                == dataset.manifest_sha256
                and snapshot.get("pose_validation_dataset_id") == validation_id
                and snapshot.get("pose_validation_dataset_manifest_sha256")
                == (validation_dataset.manifest_sha256 if validation_id is not None else None)
                and snapshot.get("pose_schema_id") == dataset.pose_schema_id
                and type(snapshot.get("pose_schema_revision")) is int
                and snapshot.get("pose_schema_revision") == dataset.pose_schema_revision
                and snapshot.get("pose_schema_content_hash") == dataset.pose_schema_content_hash
                and isinstance(snapshot.get("split_manifest"), dict)
                and snapshot["split_manifest"] == manifest.get("pose_split_manifest")
                and canonical_json_sha256(snapshot["split_manifest"])
                == training.split_manifest_sha256,
                "Frozen pose-training draft differs from saved workflow or validation split",
            )
            # The saved result also records the requested scientific run settings.
            # A rehashed result must not misrepresent the device, provider, seed
            # or registry version while still pointing at the same checkpoint.
            _require(
                result.get("schema_version") == "workflow-training-result-0001"
                and result.get("project_id") == run.project_id
                and result.get("created_by_workflow") is True
                and result.get("dataset_version_id") == training.dataset_version_id
                and result.get("dataset_manifest_sha256") == training.dataset_manifest_sha256
                and result.get("task") == training.task
                and result.get("provider_id") == training.provider_id == "ultralytics"
                and result.get("architecture") == training.architecture
                and result.get("device") == training.device
                and result.get("precision") == training.precision
                and result.get("run_name") == training.run_name
                and type(result.get("random_seed")) is type(training.random_seed)
                and result.get("random_seed") == training.random_seed
                and isinstance(snapshot.get("parameter_registry_version"), str)
                and bool(snapshot["parameter_registry_version"])
                and result.get("parameter_registry_version")
                == training.parameter_registry_version
                == snapshot["parameter_registry_version"]
                and result.get("warnings") == training.warnings_json,
                "Saved pose-training result misstates persisted scientific configuration",
            )
            # First completion freezes the complete epoch history separately
            # from the final scores. Compare both persisted training records
            # with the saved Workflow Builder result: altered learning curves
            # must not pass just because checkpoint bytes remain unchanged.
            _require(
                snapshot.get("schema_version") == "pose-workflow-training-snapshot-0004"
                and isinstance(training.metrics_history_json, dict)
                and canonical_json_sha256(training.metrics_history_json)
                == snapshot.get("metrics_history_sha256")
                and result.get("metrics_history") == training.metrics_history_json
                and result.get("metrics") == training.metrics_json,
                "Saved pose-training metric history or summary disagrees with worker evidence",
            )
            # A checksum-valid workflow artifact is not proof that the durable
            # experiment registry still belongs to this training run. Verify
            # the separately persisted scientific summary and environment.
            experiment_id = result.get("experiment_id")
            _require(
                isinstance(experiment_id, str) and bool(experiment_id),
                "Saved pose training experiment ID is missing",
            )
            experiment = session.get(ExperimentRecord, experiment_id)
            _require(
                experiment is not None
                and experiment.project_id == run.project_id
                and experiment.training_run_id == training.id
                and experiment.dataset_version_id == training.dataset_version_id
                and experiment.dataset_manifest_sha256 == training.dataset_manifest_sha256
                and experiment.split_manifest_sha256 == training.split_manifest_sha256
                and experiment.task == training.task
                and experiment.provider_id == training.provider_id
                and experiment.architecture == training.architecture
                and isinstance(experiment.summary_metrics_json, dict)
                and experiment.summary_metrics_json == training.metrics_json
                and isinstance(experiment.comparison_warnings_json, list)
                and experiment.comparison_warnings_json == training.warnings_json
                and isinstance(experiment.artifact_manifest_json, dict)
                and experiment.artifact_manifest_json == training.artifact_manifest_json
                and isinstance(experiment.package_versions_json, dict),
                "Persisted experiment registry no longer matches completed pose training",
            )
            # First completion also freezes the environment digest in the v4
            # training snapshot, separately from the worker's artifact manifest.
            # Match replay's three-way package-version provenance contract.
            _require(
                canonical_json_sha256(experiment.package_versions_json)
                == training.artifact_manifest_json.get("experiment_package_versions_sha256")
                == snapshot.get("experiment_package_versions_sha256"),
                "Recorded experiment package versions differ from frozen training evidence",
            )
            # The production replay contract only accepts best.pt/last.pt
            # inside *this* training run's output tree. A valid checksum in
            # a different run's weights file does not prove local lineage.
            project = session.get(Project, run.project_id)
            _require(project is not None, "Training project was not found")
            # A successful retraining run must still be traceable to its
            # original local registered pose model, not only to the output
            # checkpoint. Preserve and authenticate user-trained seed weights.
            seed_id = training.initial_checkpoint_model_id
            if seed_id is None:
                _require(
                    training.initial_checkpoint_source == "scratch"
                    and training.resolved_model_asset_id
                    == f"builtin_architecture:{training.architecture}"
                    and training.resolved_model_checksum is None
                    and snapshot.get("initialization_mode") == "random"
                    and snapshot.get("seed_model_id") is None
                    and snapshot.get("seed_model_sha256") is None,
                    "Random-initialized pose training provenance changed",
                )
            else:
                seed = session.get(ModelRegistration, seed_id)
                seed_binding = session.get(PoseModelSchemaBinding, seed_id)
                _require(
                    seed is not None
                    and seed.project_id == run.project_id
                    and seed.purpose == "detector"
                    and seed.task == "pose"
                    and seed.provider_name == "ultralytics"
                    and isinstance(seed.sha256, str)
                    and len(seed.sha256) == 64
                    and training.initial_checkpoint_source == "registered_model"
                    and training.resolved_model_asset_id == f"registered_model:{seed_id}"
                    and training.resolved_model_checksum == seed.sha256
                    and snapshot.get("initialization_mode") == "registered_model"
                    and snapshot.get("seed_model_id") == seed_id
                    and snapshot.get("seed_model_sha256") == seed.sha256
                    and seed_binding is not None
                    and seed_binding.schema_id == dataset.pose_schema_id
                    and seed_binding.schema_revision == dataset.pose_schema_revision,
                    "Original registered pose seed or frozen initialization lineage changed",
                )
                seed_path = _managed_file(root, seed.managed_path)
                _require(
                    seed_path.stat().st_size > 0 and _digest(seed_path) == seed.sha256,
                    "Original registered pose seed checkpoint is missing or changed",
                )
            expected_weights_prefix = (
                f"{project.storage_root}/training/{training.id}/runs/pose/weights/"
            )
            _require(
                training.result_checkpoint_path
                in {expected_weights_prefix + "best.pt", expected_weights_prefix + "last.pt"},
                "Selected checkpoint belongs to a different training run",
            )
            checkpoint = _managed_file(root, training.result_checkpoint_path)
            checkpoint_sha = _digest(checkpoint)
            _require(
                checkpoint_sha == result.get("result_checkpoint_sha256"),
                "Checkpoint bytes differ from saved workflow provenance",
            )
            # The saved training_result, finalized worker manifest and actual
            # checkpoint are three independent scientific records. A valid
            # workflow artifact checksum alone cannot reconcile drift between
            # them after first completion.
            checkpoint_manifest = training.artifact_manifest_json
            checkpoint_size = checkpoint.stat().st_size
            _require(
                checkpoint_manifest.get("result_checkpoint_path") == training.result_checkpoint_path
                and checkpoint_manifest.get("result_checkpoint_sha256") == checkpoint_sha
                and result.get("result_checkpoint_path") == training.result_checkpoint_path
                and result.get("artifact_manifest") == checkpoint_manifest
                and type(result.get("result_checkpoint_size_bytes")) is int
                and result["result_checkpoint_size_bytes"] == checkpoint_size
                and checkpoint_size > 0,
                "Saved training result or worker manifest differs from checkpoint evidence",
            )

            # Scientific acceptance covers *all* checkpoint files frozen by
            # the worker, not just the selected checkpoint registered as a model.
            # Non-selected best/last weights are independent research artifacts.
            verified_checkpoints: dict[str, dict[str, Any]] = {}
            for path_key, sha_key, filename in (
                ("best_checkpoint_path", "best_checkpoint_sha256", "best.pt"),
                ("last_checkpoint_path", "last_checkpoint_sha256", "last.pt"),
            ):
                advertised_path = checkpoint_manifest.get(path_key)
                advertised_sha = checkpoint_manifest.get(sha_key)
                if advertised_path is None and advertised_sha is None:
                    continue
                _require(
                    isinstance(advertised_path, str)
                    and bool(advertised_path)
                    and isinstance(advertised_sha, str)
                    and len(advertised_sha) == 64
                    and all(char in "0123456789abcdef" for char in advertised_sha),
                    f"{path_key} and {sha_key} must be paired and valid",
                )
                _require(
                    advertised_path == expected_weights_prefix + filename,
                    f"{path_key} belongs to another training run",
                )
                advertised_file = _managed_file(root, advertised_path)
                advertised_size = advertised_file.stat().st_size
                _require(
                    advertised_size > 0 and _digest(advertised_file) == advertised_sha,
                    f"{path_key} is empty or differs from saved training manifest",
                )
                verified_checkpoints[filename] = {
                    "sha256": advertised_sha,
                    "size_bytes": advertised_size,
                }

            model = session.get(ModelRegistration, registered.get("model_id"))
            _require(
                model is not None and model.project_id == run.project_id,
                "Model is not registered",
            )
            _require(
                model.task == "pose" and model.provider_name == training.provider_id,
                "Registered pose model provider differs from completed training",
            )
            # The registration service independently binds the model to a
            # concrete landmark-schema revision. Metadata alone can remain
            # checksum-consistent after that binding is deleted or relinked.
            binding = session.get(PoseModelSchemaBinding, model.id)
            revision = session.scalar(
                select(PoseLandmarkSchemaRevision).where(
                    PoseLandmarkSchemaRevision.schema_id == dataset.pose_schema_id,
                    PoseLandmarkSchemaRevision.revision == dataset.pose_schema_revision,
                )
            )
            _require(
                binding is not None
                and binding.schema_id == dataset.pose_schema_id
                and binding.schema_revision == dataset.pose_schema_revision
                and revision is not None
                and revision.content_hash == dataset.pose_schema_content_hash
                and revision.keypoint_count > 0,
                "Registered pose model binding or frozen landmark revision changed",
            )
            _require(
                model.sha256 == registered.get("model_sha256"),
                "Model registration digest changed",
            )
            _require(
                registered.get("source_training_run_id") == training.id
                and registered.get("source_pose_training_dataset_id") == dataset.id
                and registered.get("source_pose_training_dataset_manifest_sha256")
                == dataset.manifest_sha256,
                "Registered model no longer identifies the frozen training lineage",
            )
            # A model with matching checkpoint bytes can still have its persisted
            # registration relinked to another run. Verify the durable registry
            # metadata, not only the checksum-valid Workflow Builder reference.
            metadata = model.metadata_json
            # Registration freezes the *full* landmark anatomy snapshot.
            # Matching schema IDs and hashes alone cannot detect changes to
            # the separately persisted label order, grouping, or keypoint count.
            schema_snapshot = (
                metadata.get("pose_landmark_schema") if isinstance(metadata, dict) else None
            )
            _require(
                schema_snapshot
                == {
                    "schema_version": revision.schema_version,
                    "schema_id": revision.schema_id,
                    "schema_revision": revision.revision,
                    "groups": revision.groups_json,
                    "expanded_labels": revision.expanded_labels_json,
                    "keypoint_count": revision.keypoint_count,
                    "allows_repeated_labels": revision.allows_repeated_labels,
                    "content_hash": revision.content_hash,
                },
                "Registered model landmark snapshot differs from frozen schema revision",
            )
            _require(
                isinstance(metadata, dict)
                and metadata.get("registered_from") == "training_run"
                and metadata.get("source_training_run_id") == training.id
                and metadata.get("source_pose_training_dataset_id") == dataset.id
                and metadata.get("source_pose_training_dataset_manifest_sha256")
                == dataset.manifest_sha256
                and metadata.get("source_split_manifest_sha256") == training.split_manifest_sha256
                and metadata.get("source_result_checkpoint_path") == training.result_checkpoint_path
                and metadata.get("source_pose_schema_id") == dataset.pose_schema_id
                and metadata.get("source_pose_schema_revision") == dataset.pose_schema_revision
                and metadata.get("source_pose_schema_content_hash")
                == dataset.pose_schema_content_hash
                and metadata.get("source_pose_validation_dataset_id") == validation_id
                and metadata.get("source_pose_validation_dataset_manifest_sha256")
                == (validation_dataset.manifest_sha256 if validation_id is not None else None)
                and metadata.get("source_experiment_id") == experiment.id
                and metadata.get("source_architecture") == training.architecture
                and metadata.get("source_initial_pose_model_id")
                == training.initial_checkpoint_model_id
                and metadata.get("source_initial_pose_model_sha256")
                == training.resolved_model_checksum
                and metadata.get("source_metrics") == training.metrics_json,
                "Registered model database provenance no longer matches completed training",
            )
            model_sha = _digest(_managed_file(root, model.managed_path))
            _require(model_sha == model.sha256, "Registered local model file digest changed")
            # Registration copies the exact finalized training checkpoint. Two
            # independently self-consistent hashes are not enough to prove
            # this local model was produced by the audited training job.
            _require(
                model_sha == checkpoint_sha,
                "Registered local model bytes differ from the trained checkpoint",
            )
            return {
                "status": "PASS",
                "evidence_schema_version": "saved-pose-workflow-audit-0001",
                "project_id": run.project_id,
                "workflow_run_id": run.id,
                "workflow_job_id": parent_job.id,
                "workflow_graph_sha256": run.graph_sha256,
                "workflow_provenance_sha256": canonical_json_sha256(provenance),
                "frozen_dataset_id": dataset.id,
                "verified_items": dataset.item_count,
                "verified_source_video_count": len(video_digests),
                "verified_source_video_bytes": verified_source_bytes,
                "dataset_manifest_sha256": dataset.manifest_sha256,
                "validation_dataset_id": validation_id,
                "validation_dataset_manifest_sha256": (
                    validation_dataset.manifest_sha256 if validation_id is not None else None
                ),
                "validation_items": (
                    validation_dataset.item_count if validation_id is not None else 0
                ),
                "validation_mode": expected_validation_mode,
                "split_manifest_sha256": training.split_manifest_sha256,
                "pose_schema_id": dataset.pose_schema_id,
                "pose_schema_revision": dataset.pose_schema_revision,
                "pose_schema_content_hash": dataset.pose_schema_content_hash,
                "verified_source_video_sha256": video_digests,
                "separate_validation_source_video_overlap_checked": validation_id is not None,
                "separate_validation_frame_overlap_checked": (
                    validation_id is not None and validation_id != dataset.id
                ),
                "training_run_id": training.id,
                "training_job_id": job.id,
                "experiment_id": experiment.id,
                "experiment_package_versions_sha256": snapshot[
                    "experiment_package_versions_sha256"
                ],
                "child_job_request_sha256": snapshot["pose_child_job_request_sha256"],
                "metrics_history_sha256": snapshot["metrics_history_sha256"],
                "provider_id": training.provider_id,
                "architecture": training.architecture,
                "requested_device": training.device,
                "precision": training.precision,
                "random_seed": training.random_seed,
                "seed_model_id": seed_id,
                "seed_model_sha256": training.resolved_model_checksum,
                "checkpoint_sha256": checkpoint_sha,
                "checkpoint_size_bytes": checkpoint_size,
                "verified_checkpoints": verified_checkpoints,
                "registered_model_id": model.id,
                "registered_model_sha256": model_sha,
                "scope": "saved workflow, frozen truth, training and local model bytes only",
            }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, required=True, help="Existing local ReefVision SQLite DB"
    )
    parser.add_argument("--run-id", required=True, help="Completed saved Workflow Builder run ID")
    parser.add_argument(
        "--data-dir", type=Path, required=True, help="Local ReefVision data root"
    )
    args = parser.parse_args()
    try:
        evidence = inspect(args.db, args.run_id, args.data_dir)
    except Exception as exc:
        # A failed scientific integrity check (including domain/SQLAlchemy
        # exceptions) must never be emitted as a passing evidence record.
        print(
            json.dumps({"status": "FAIL", "error_type": type(exc).__name__, "reason": str(exc)}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

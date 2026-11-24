#!/usr/bin/env python3
"""Audit one EXISTING, completed pose Workflow Builder run without writing data.

This is a manual scientific acceptance gate, not a synthetic CI fixture.
A PASS requires a saved run, reviewed frozen truth, finished training, a
checkpoint, and a registered local model whose actual file digests match.
The database must already be at the migration head of this checkout.
It does not certify the Windows installer or GPU hardware independently.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import warnings
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


def _verify_frozen_frame_inventory(
    root: Path, split: str, items: list[dict[str, Any]], advertised_count: object
) -> int:
    """Reconcile materialized frame and instance counts with reviewed truth."""
    counts: dict[str, int] = {}
    for item in items:
        stem = f"frame_{item['frame_index']:08d}"
        counts[stem] = counts.get(stem, 0) + 1

    images = root / "images" / split
    labels = root / "labels" / split
    _require(
        {file.name for file in images.glob("*.png")} == {f"{stem}.png" for stem in counts}
        and {file.name for file in labels.glob("*.txt")} == {f"{stem}.txt" for stem in counts}
        and type(advertised_count) is int
        and advertised_count == len(counts),
        f"Materialized {split} frame inventory differs from frozen reviewed truth",
    )
    for stem, count in counts.items():
        rows = (labels / f"{stem}.txt").read_text(encoding="utf-8").splitlines()
        _require(
            len(rows) == count and all(row.strip() for row in rows),
            f"Materialized {split} instance count differs from frozen truth: {stem}",
        )
    return len(counts)


def _verify_source_frame_pixels(
    source: Path,
    images: Path,
    frame_indices: set[int],
    width: int,
    height: int,
) -> int:
    """Stream original frames and compare lossless materialized pixels."""
    import cv2
    import numpy as np

    _require(bool(frame_indices) and min(frame_indices) >= 0, "Invalid frozen frame indices")
    capture = cv2.VideoCapture(str(source))
    verified = 0
    try:
        _require(capture.isOpened(), "Cannot decode original frozen source video")
        # Match the exporter's sequential, zero-based decoding. Seeking to a
        # compressed frame can select a different frame on some backends.
        for index in range(max(frame_indices) + 1):
            ok, frame = capture.read()
            _require(ok and frame is not None, f"Source video ended before frame {index}")
            if index not in frame_indices:
                continue
            image_path = images / f"frame_{index:08d}.png"
            saved = cv2.imdecode(
                np.frombuffer(image_path.read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED
            )
            _require(
                frame.shape[:2] == (height, width)
                and saved is not None
                and saved.dtype == frame.dtype
                and np.array_equal(saved, frame),
                f"Materialized image pixels differ from frozen source frame: {image_path.name}",
            )
            verified += 1
    finally:
        capture.release()
    return verified


def _verify_database_revision(connection: Any, api_dir: Path) -> tuple[str, int, str]:
    """Require one linear migration chain and record its exact source identity."""
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(Config(str(api_dir / "alembic.ini")))
    # Alembic warns, rather than fails, for duplicate revision IDs.
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message=r"Revision .* is present more than once")
        expected = scripts.get_heads()
        if len(expected) != 1:
            raise ValueError("Acceptance requires one source migration head")
        revisions = list(scripts.walk_revisions())
    lineage = []
    for index, revision in enumerate(revisions):
        parent = revisions[index + 1].revision if index + 1 < len(revisions) else None
        if revision.down_revision != parent or revision.dependencies:
            raise ValueError(f"Nonlinear source migration ancestry at {revision.revision}")
        lineage.append(
            {
                "revision": revision.revision,
                "down_revision": parent,
                "file_sha256": hashlib.sha256(Path(revision.path).read_bytes()).hexdigest(),
            }
        )
    actual = MigrationContext.configure(connection).get_current_heads()
    if tuple(expected) != actual:
        raise ValueError(
            f"Database migration revision {actual} differs from source head {expected}"
        )
    digest = hashlib.sha256(
        json.dumps(lineage, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return actual[0], len(lineage), digest


def inspect(db: Path, run_id: str, data_dir: Path) -> dict[str, Any]:
    # The app imports are delayed so the script works from a source checkout.
    api_dir = Path(__file__).resolve().parents[1] / "apps" / "api"
    sys.path.insert(0, str(api_dir))
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import Session

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
        VideoAsset,
        WorkflowArtifact,
        WorkflowNodeRun,
        WorkflowRun,
    )
    from reefvision.jobs.pose_training import _verify_prelaunch_pose_dataset
    from reefvision.services.pose_training_datasets import PoseTrainingDatasetService
    from reefvision.services.pose_training_exports import PoseTrainingExportService
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
            # Read the migration stamp within the same snapshot as the scientific records.
            # Never stamp or upgrade a database as part of this acceptance check.
            database_revision, migration_count, migration_sha256 = _verify_database_revision(
                session.connection(), api_dir
            )
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
            # Verify the exact extracted image/label/YAML tree consumed by the
            # GPU worker, not just its original videos and database manifests.
            dataset_relative = f"{project.storage_root}/training/{training.id}/pose-dataset"
            dataset_path = Path(dataset_relative)
            materialization = manifest.get("materialization")
            _require(
                not dataset_path.is_absolute()
                and ".." not in dataset_path.parts
                and manifest.get("dataset_output_path") == dataset_relative
                and isinstance(materialization, dict)
                and materialization.get("validation_mode") == expected_validation_mode
                and manifest.get("validation_mode") == expected_validation_mode,
                "Materialized pose inputs do not belong to the audited training run",
            )
            # Reuse the production worker's read-only fingerprint verification,
            # including its path, symlink, junction, and hard-link protections.
            _verify_prelaunch_pose_dataset(root / dataset_path, materialization)
            # The materialization hash only authenticates the recorded tree.
            # Independently count reviewed instances per exported frame so a
            # rehashed incomplete or duplicated split cannot pass acceptance.
            train_frame_count = _verify_frozen_frame_inventory(
                root / dataset_path,
                "train",
                dataset.manifest_json["items"],
                materialization.get("training_image_count"),
            )
            validation_frame_count = _verify_frozen_frame_inventory(
                root / dataset_path,
                "val",
                validation_dataset.manifest_json["items"] if validation_id is not None else [],
                materialization.get("validation_image_count"),
            )
            # Frame counts do not establish that the actual class IDs, boxes,
            # landmark coordinates and visibility match the reviewed poses.
            # Render labels in memory using the production exporter; do not
            # rewrite the saved dataset. Verify source image pixels separately.
            exporter = PoseTrainingExportService(session, Settings(data_dir=root))
            verified_label_count = 0
            verified_image_count = 0
            training_yaml: str | None = None
            materialized_yaml = root / dataset_path / "data.yaml"
            for split, frozen_dataset in (
                ("train", dataset),
                ("val", validation_dataset if validation_id is not None else None),
            ):
                if frozen_dataset is None:
                    continue
                items = exporter._items(frozen_dataset)
                schema = exporter._schema(frozen_dataset)
                video, source, _, _ = exporter._source_video(items)
                verified_image_count += _verify_source_frame_pixels(
                    source,
                    root / dataset_path / "images" / split,
                    {item.frame_index for item in items},
                    video.width_px,
                    video.height_px,
                )
                expected_labels = exporter._ultralytics(
                    items=items,
                    schema=schema,
                    video=video,
                    class_mapping=exporter._class_mapping(items),
                )
                # The worker requires identical export headers before splitting
                # held-out data and changes only the validation directory.
                # Read text to allow the worker's native Windows line endings.
                exported_yaml = expected_labels["data.yaml"].decode("utf-8")
                if split == "train":
                    training_yaml = exported_yaml
                    expected_yaml = (
                        exported_yaml.replace("val: images/train", "val: images/val", 1)
                        if validation_id is not None
                        else exported_yaml
                    )
                    _require(
                        materialized_yaml.read_text(encoding="utf-8") == expected_yaml,
                        "Materialized pose YAML differs from frozen class or landmark schema",
                    )
                else:
                    _require(
                        exported_yaml == training_yaml,
                        "Frozen validation export header differs from training schema",
                    )
                for relative, expected in expected_labels.items():
                    if not relative.startswith("labels/train/"):
                        continue
                    label_file = root / dataset_path / "labels" / split / Path(relative).name
                    _require(
                        label_file.read_bytes() == expected,
                        f"Materialized {split} labels differ from frozen truth: {label_file.name}",
                    )
                    verified_label_count += 1
            _require(
                verified_label_count == train_frame_count + validation_frame_count,
                "Reconstructed pose labels do not cover all reviewed frames",
            )
            _require(
                verified_image_count == train_frame_count + validation_frame_count,
                "Source pixel verification does not cover all reviewed frames",
            )
            # A successful retraining run must still be traceable to its
            # original local registered pose model, not only to the output
            # checkpoint. Preserve and authenticate user-trained seed weights.
            seed_id = training.initial_checkpoint_model_id
            seed_size: int | None = None
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
                # Initialization must preexist this training run. Reject a
                # direct cycle even if all persisted digests agree.
                _require(
                    seed_id != registered.get("model_id")
                    and not (
                        isinstance(seed.metadata_json, dict)
                        and seed.metadata_json.get("source_training_run_id") == training.id
                    ),
                    "Original pose seed is an output of the audited training run",
                )
                seed_path = _managed_file(root, seed.managed_path)
                seed_size = seed_path.stat().st_size
                _require(
                    seed_size > 0
                    and seed_size == seed.file_size_bytes
                    and _digest(seed_path) == seed.sha256,
                    "Original registered pose seed checkpoint differs from registry evidence",
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
                    candidate = checkpoint.parent / filename
                    _require(
                        not candidate.exists() and not candidate.is_symlink(),
                        f"Unrecorded checkpoint in saved training output: {filename}",
                    )
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
                advertised_metadata = advertised_file.stat()
                # Match the training worker's trust boundary: a hard link can
                # alias an earlier run's weights without changing their digest.
                _require(
                    advertised_metadata.st_nlink == 1,
                    f"{path_key} is hard-linked and does not prove independent run lineage",
                )
                advertised_size = advertised_metadata.st_size
                _require(
                    advertised_size > 0 and _digest(advertised_file) == advertised_sha,
                    f"{path_key} is empty or differs from saved training manifest",
                )
                verified_checkpoints[filename] = {
                    "sha256": advertised_sha,
                    "size_bytes": advertised_size,
                }

            # The worker selects best.pt when present, otherwise last.pt.
            # An omitted checkpoint cannot silently disappear from the inventory.
            _require(
                bool(verified_checkpoints)
                and checkpoint.name
                == ("best.pt" if "best.pt" in verified_checkpoints else "last.pt"),
                "Selected checkpoint differs from the verified best/last inventory",
            )

            model = session.get(ModelRegistration, registered.get("model_id"))
            _require(
                model is not None and model.project_id == run.project_id,
                "Model is not registered",
            )
            # The workflow model reference is an independent persisted record.
            # A valid digest must not conceal a changed model purpose or provider.
            _require(
                registered.get("schema_version") == "workflow-model-reference-0001"
                and registered.get("registered_from_workflow") is True
                and registered.get("project_id") == run.project_id
                and registered.get("purpose") == model.purpose == "detector"
                and registered.get("task") == model.task == "pose"
                and registered.get("provider_name") == model.provider_name == training.provider_id
                and registered.get("provider_version") == model.provider_version
                and registered.get("framework") == model.framework,
                "Saved model reference differs from registered pose model identity",
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
                == dataset.manifest_sha256
                and registered.get("source_experiment_id") == experiment.id
                and registered.get("source_dataset_version_id") == training.dataset_version_id
                and registered.get("source_dataset_manifest_sha256")
                == training.dataset_manifest_sha256
                and registered.get("source_split_manifest_sha256") == training.split_manifest_sha256
                and registered.get("source_pose_validation_dataset_id") == validation_id
                and registered.get("source_pose_validation_dataset_manifest_sha256")
                == (validation_dataset.manifest_sha256 if validation_id is not None else None)
                and registered.get("pose_schema_id") == dataset.pose_schema_id
                and type(registered.get("pose_schema_revision")) is int
                and registered.get("pose_schema_revision") == dataset.pose_schema_revision
                and registered.get("pose_schema_content_hash") == dataset.pose_schema_content_hash
                and registered.get("pose_landmark_labels") == revision.expanded_labels_json,
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
                and metadata.get("source_dataset_version_id") == training.dataset_version_id
                and metadata.get("source_dataset_manifest_sha256") == training.dataset_manifest_sha256
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
            # Registration copies finalized weights into the project's model
            # registry. A matching digest at a training-output path is not an
            # independently retained registered model.
            _require(
                model.managed_path == f"{project.storage_root}/models/{model.id}.pt",
                "Registered pose weights are outside their canonical model registry path",
            )
            model_file = _managed_file(root, model.managed_path)
            model_metadata = model_file.stat()
            _require(
                model_metadata.st_nlink == 1,
                "Registered pose weights are hard-linked instead of independently retained",
            )
            model_size = model_metadata.st_size
            _require(
                model_size == model.file_size_bytes == checkpoint_size,
                "Registered local model file size differs from registry or checkpoint",
            )
            model_sha = _digest(model_file)
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
                "verified_database_alembic_revision": database_revision,
                "source_migration_count": migration_count,
                "source_migration_lineage_sha256": migration_sha256,
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
                "materialized_dataset_sha256": materialization["materialized_dataset_sha256"],
                "verified_materialized_label_file_count": verified_label_count,
                "verified_materialized_image_pixel_count": verified_image_count,
                "verified_materialized_yaml_sha256": _digest(materialized_yaml),
                "verified_training_frame_count": train_frame_count,
                "verified_validation_frame_count": validation_frame_count,
                "materialized_dataset_fingerprint_algorithm": materialization.get(
                    "materialized_dataset_fingerprint_algorithm"
                ),
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
                "verified_seed_model_size_bytes": seed_size,
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

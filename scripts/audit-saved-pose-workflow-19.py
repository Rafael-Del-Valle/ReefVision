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
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve(strict=True)
    _require(resolved.is_file(), "Checkpoint is not a regular file")
    _require(resolved.is_relative_to(root), "Checkpoint escapes the selected data directory")
    return resolved


def inspect(db: Path, run_id: str, data_dir: Path) -> dict[str, Any]:
    # The app imports are delayed so the script works from a source checkout.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from reefvision.db.models import (
        Job,
        ModelRegistration,
        PoseTrainingDataset,
        TrainingRun,
        WorkflowArtifact,
        WorkflowNodeRun,
        WorkflowRun,
    )
    from reefvision.services.pose_training_datasets import PoseTrainingDatasetService
    from reefvision.services.workflow_provenance import build_workflow_run_provenance

    _require(db.is_file(), "An existing local SQLite database is required")
    _require(data_dir.is_dir(), "An existing model and checkpoint data directory is required")
    root = data_dir.resolve(strict=True)

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(db.resolve(strict=True).as_uri() + "?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        return connection

    engine = create_engine("sqlite://", creator=connect)
    try:
        with Session(engine) as session:
            run = session.get(WorkflowRun, run_id)
            _require(run is not None and run.status == "succeeded", "Saved run did not succeed")
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
            _require(dataset.project_id == run.project_id, "Frozen dataset belongs to another project")
            _require(
                frozen.get("manifest_sha256") == dataset.manifest_sha256,
                "Workflow dataset manifest fingerprint changed",
            )
            # Performs the app's deep verification of human review, frozen
            # canonical poses, source model/job identities and signed summaries.
            PoseTrainingDatasetService(session).manifest(dataset.id)

            training = session.get(TrainingRun, result.get("training_run_id"))
            _require(training is not None and training.status == "completed", "Training is incomplete")
            _require(training.task == "pose", "Training result is not a pose model")
            _require(training.project_id == run.project_id, "Training belongs to another project")
            _require(result.get("workflow_run_id") == run_id, "Training run provenance changed")
            _require(result.get("pose_training_dataset_id") == dataset.id, "Training used another dataset")
            _require(
                training.artifact_manifest_json.get("pose_training_dataset_manifest_sha256")
                == dataset.manifest_sha256,
                "Training's frozen dataset digest is missing or mismatched",
            )
            job = session.get(Job, training.job_id)
            _require(job is not None and job.status == "succeeded", "Pose training job did not succeed")
            checkpoint = _managed_file(root, training.result_checkpoint_path)
            checkpoint_sha = _digest(checkpoint)
            _require(
                checkpoint_sha == result.get("result_checkpoint_sha256"),
                "Checkpoint bytes differ from saved workflow provenance",
            )

            model = session.get(ModelRegistration, registered.get("model_id"))
            _require(model is not None and model.project_id == run.project_id, "Model is not registered")
            _require(model.task == "pose", "Registered model is not a pose model")
            _require(model.sha256 == registered.get("model_sha256"), "Model registration digest changed")
            _require(
                registered.get("source_training_run_id") == training.id
                and registered.get("source_pose_training_dataset_id") == dataset.id
                and registered.get("source_pose_training_dataset_manifest_sha256")
                == dataset.manifest_sha256,
                "Registered model no longer identifies the frozen training lineage",
            )
            model_sha = _digest(_managed_file(root, model.managed_path))
            _require(model_sha == model.sha256, "Registered local model file digest changed")
            return {
                "status": "PASS",
                "workflow_run_id": run.id,
                "frozen_dataset_id": dataset.id,
                "verified_items": dataset.item_count,
                "dataset_manifest_sha256": dataset.manifest_sha256,
                "training_run_id": training.id,
                "training_job_id": job.id,
                "checkpoint_sha256": checkpoint_sha,
                "registered_model_id": model.id,
                "registered_model_sha256": model_sha,
                "scope": "saved workflow, frozen truth, training and local model bytes only",
            }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Existing local ReefVision SQLite DB")
    parser.add_argument("--run-id", required=True, help="Completed saved Workflow Builder run ID")
    parser.add_argument("--data-dir", type=Path, required=True, help="Local ReefVision data root")
    args = parser.parse_args()
    try:
        evidence = inspect(args.db, args.run_id, args.data_dir)
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

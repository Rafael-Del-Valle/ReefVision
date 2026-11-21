"""Exercise saved pose training admission through its ordinary workflow job."""

import shutil
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.pose_training_exports import PoseTrainingExportService
from reefvision.tests.test_workflow_pose_review_resume_phase10 import _save_and_queue
from reefvision.tests.test_workflow_pose_training_phase10 import (
    _frozen_dataset,
    _synthetic_exact_frames,
)


def test_saved_pose_training_refuses_disk_budget_then_retries_without_duplicate_child(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        PoseTrainingExportService, "_extract_exact_frames", staticmethod(_synthetic_exact_frames)
    )
    project, dataset = _frozen_dataset(client, monkeypatch)
    project_path = f"/api/v1/projects/{project['id']}"
    graph = {
        "graph_id": "pose-disk-admission",
        "name": "Pose disk admission",
        "nodes": [
            {
                "node_id": "dataset",
                "node_type": "pose_training_dataset",
                "parameters": {
                    "dataset_id": dataset["id"],
                    "manifest_sha256": dataset["manifest_sha256"],
                },
            },
            {
                "node_id": "train",
                "node_type": "pose_model_training",
                "parameters": {
                    "provider_id": "reefpose",
                    "architecture": "reefpose-s",
                    "device": "cpu",
                    "resource_limits": {"max_disk_usage_gb": 1},
                    "training_config": {
                        "epochs": 1,
                        "batch": 1,
                        "input_height": 64,
                        "input_width": 64,
                        "base_channels": 4,
                        "fpn_channels": 8,
                        "workers": 0,
                    },
                },
            },
        ],
        "edges": [
            {
                "edge_id": "dataset-train",
                "source_node_id": "dataset",
                "source_port_id": "dataset",
                "target_node_id": "train",
                "target_port_id": "dataset",
            },
        ],
    }
    run_id, job_id = _save_and_queue(client, str(project["id"]), graph)
    run_url = f"/api/v1/workflow-runs/{run_id}"
    job_url = f"/api/v1/jobs/{job_id}"
    factory = cast(FastAPI, client.app).state.session_factory
    capacity = shutil.disk_usage(test_settings.resolved_data_dir)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: capacity._replace(free=0))

    assert not process_workflow_run_job(test_settings, factory, job_id)
    failed = client.get(run_url).json()
    assert failed["run"]["status"] == "failed"
    assert "available disk space" in failed["run"]["error_message"]
    assert client.get(project_path + "/training-runs").json() == []
    assert failed["artifacts"] and all(
        row["data_type"] != "training_result" for row in failed["artifacts"]
    )

    retried = client.post(job_url + "/retry")
    assert retried.status_code == 200 and retried.json()["id"] == job_id
    monkeypatch.setattr(shutil, "disk_usage", lambda _: capacity._replace(free=1024**3))
    assert process_workflow_run_job(test_settings, factory, job_id)
    assert client.get(run_url).json()["run"]["status"] == "succeeded"
    [child] = client.get(project_path + "/training-runs").json()
    assert child["status"] == "completed" and child["artifact_manifest"]["best_checkpoint_sha256"]

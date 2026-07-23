from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import Job
from reefvision.tests.test_training_workspace import (
    _patch_training_foundation,
    _seed_training_dataset,
)


def test_training_run_persists_multi_gpu_resource_requirements(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_training_foundation(monkeypatch)
    project, version = _seed_training_dataset(client)
    draft_response = client.post(
        f"/api/v1/projects/{project['id']}/training-drafts",
        json={
            "name": "Two GPU detector",
            "run_name": "two-gpu-detector",
            "dataset_version_id": version["id"],
            "task": "detect",
            "provider_id": "ultralytics",
            "architecture": "yolo11.yaml",
            "initial_checkpoint_source": "scratch",
            "device": "auto",
            "precision": "amp",
            "training_config": {"epochs": 2, "batch": 4, "imgsz": 64},
            "resource_limits": {
                "gpu_count": 2,
                "minimum_vram_gb_per_gpu": 12,
                "minimum_ram_gb": 24,
                "cpu_threads": 8,
                "exclusive_gpu": True,
                "allowed_devices": ["auto"],
            },
        },
    )
    assert draft_response.status_code == 200, draft_response.text

    run_response = client.post(
        f"/api/v1/projects/{project['id']}/training-runs",
        json={"draft_id": draft_response.json()["id"]},
    )
    assert run_response.status_code == 200, run_response.text
    run = run_response.json()
    assert run["job_id"]

    with client.app.state.session_factory() as session:
        job = session.get(Job, run["job_id"])
        assert job is not None
        requirements = dict(job.resource_requirements_json or {})
        assert requirements["gpu_required"] is True
        assert requirements["gpu_count"] == 2
        assert requirements["minimum_vram_bytes_per_gpu"] == 12 * 1024**3
        assert requirements["minimum_ram_bytes"] == 24 * 1024**3
        assert requirements["cpu_threads"] == 8
        assert requirements["exclusive_gpu"] is True
        assert job.request_json["requested_gpu_count"] == 2


def test_cpu_training_does_not_reserve_a_gpu(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_training_foundation(monkeypatch)
    project, version = _seed_training_dataset(client)
    draft = client.post(
        f"/api/v1/projects/{project['id']}/training-drafts",
        json={
            "name": "CPU detector",
            "dataset_version_id": version["id"],
            "task": "detect",
            "provider_id": "ultralytics",
            "architecture": "yolo11.yaml",
            "initial_checkpoint_source": "scratch",
            "device": "cpu",
            "precision": "fp32",
            "training_config": {"epochs": 1, "batch": 1, "imgsz": 64},
            "resource_limits": {"gpu_count": 0, "cpu_threads": 4},
        },
    )
    assert draft.status_code == 200, draft.text
    run = client.post(
        f"/api/v1/projects/{project['id']}/training-runs",
        json={"draft_id": draft.json()["id"]},
    )
    assert run.status_code == 200, run.text
    with client.app.state.session_factory() as session:
        job = session.get(Job, run.json()["job_id"])
        assert job is not None
        assert job.resource_requirements_json["gpu_required"] is False
        assert job.resource_requirements_json["gpu_count"] == 0
        assert job.resource_requirements_json["device"] == "cpu"

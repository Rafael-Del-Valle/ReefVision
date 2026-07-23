from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import update

from reefvision.db.models import Job, TrainingRun
from reefvision.repositories.jobs import JobRepository
from reefvision.services.resource_scheduler import GPUInventory, ResourceInventory
from reefvision.tests.test_classification_phase5 import _seed_classification_project
from reefvision.tests.test_dataset_versions import create_version

GIB = 1024**3


def test_classification_training_explicit_multi_gpu_device_is_reserved_and_bound(
    client: TestClient,
    monkeypatch,
) -> None:
    project, _image_id, _class_ids = _seed_classification_project(client)
    version = create_version(client, str(project["id"]), name="Multi-GPU classifier")
    response = client.post(
        f"/api/v1/projects/{project['id']}/classification-training-runs",
        json={
            "dataset_version_id": version["id"],
            "mode": "multiclass",
            "minimum_crop_size_px": 10,
            "run_name": "Two-GPU coral classifier",
            "architecture": "yolov8n-cls.yaml",
            "epochs": 1,
            "batch": 2,
            "imgsz": 64,
            "device": "cuda:1,cuda:2",
        },
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    job_id = response.json()["job_id"]

    monkeypatch.setattr(
        "reefvision.services.resource_scheduler.collect_resource_inventory",
        lambda: ResourceInventory(
            cpu_count=16,
            available_ram_bytes=64 * GIB,
            gpus=(
                GPUInventory(0, "cuda:0", "GPU 0", 24 * GIB, 20 * GIB),
                GPUInventory(1, "cuda:1", "GPU 1", 48 * GIB, 44 * GIB),
                GPUInventory(2, "cuda:2", "GPU 2", 48 * GIB, 42 * GIB),
            ),
        ),
    )
    with client.app.state.session_factory() as session:
        session.execute(
            update(Job)
            .where(Job.status == "queued", Job.id != job_id)
            .values(status="succeeded")
        )
        session.commit()
        claimed = JobRepository(session).next_queued("classification-multi-gpu")
        assert claimed is not None
        assert claimed.id == job_id
        assert claimed.resource_requirements_json["gpu_count"] == 2
        assert claimed.resource_requirements_json["gpu_required"] is True
        assert claimed.resource_assignment_json["gpu_indices"] == [1, 2]
        assert claimed.request_json["device"] == "1,2"
        run = session.get(TrainingRun, run_id)
        assert run is not None
        assert run.device == "1,2"
        assert run.resource_limits_json["scheduler_assignment"]["gpu_indices"] == [1, 2]

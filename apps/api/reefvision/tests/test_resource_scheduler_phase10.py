from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.db.models import Job
from reefvision.repositories.jobs import JobRepository
from reefvision.services.resource_scheduler import (
    GPUInventory,
    ResourceInventory,
    ResourceScheduler,
)


def inventory() -> ResourceInventory:
    return ResourceInventory(
        cpu_count=16,
        available_ram_bytes=64 * 1024**3,
        gpus=(
            GPUInventory(
                index=0,
                device_id="cuda:0",
                name="GPU Zero",
                total_bytes=24 * 1024**3,
                free_bytes=20 * 1024**3,
            ),
            GPUInventory(
                index=1,
                device_id="cuda:1",
                name="GPU One",
                total_bytes=48 * 1024**3,
                free_bytes=42 * 1024**3,
            ),
        ),
    )


def test_scheduler_avoids_exclusive_gpu_reservations(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "reefvision.services.resource_scheduler.collect_resource_inventory",
        inventory,
    )
    with client.app.state.session_factory() as session:
        session.add(
            Job(
                job_type="training",
                status="running",
                request_json={"device": "cuda:0"},
                result_json={},
                resource_requirements_json={
                    "gpu_required": True,
                    "minimum_vram_bytes": 8 * 1024**3,
                    "exclusive_gpu": True,
                },
                resource_assignment_json={"device": "cuda:0", "gpu_index": 0},
            )
        )
        candidate = Job(
            job_type="provider_benchmark",
            status="queued",
            request_json={"device_id": "auto"},
            result_json={},
            resource_requirements_json={
                "device": "auto",
                "gpu_required": True,
                "minimum_vram_bytes": 12 * 1024**3,
                "exclusive_gpu": True,
            },
        )
        session.add(candidate)
        session.commit()
        decision = ResourceScheduler(session).evaluate(candidate)
        assert decision.eligible is True
        assert decision.assignment["device"] == "cuda:1"
        assert decision.assignment["gpu_index"] == 1


def test_atomic_claim_resolves_assigned_device_into_request(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "reefvision.services.resource_scheduler.collect_resource_inventory",
        inventory,
    )
    with client.app.state.session_factory() as session:
        job = Job(
            job_type="provider_benchmark",
            status="queued",
            request_json={
                "provider_id": "mock",
                "task": "segment",
                "device_id": "auto",
            },
            result_json={},
            resource_requirements_json={
                "device": "auto",
                "gpu_required": True,
                "minimum_vram_bytes": 2 * 1024**3,
                "exclusive_gpu": False,
            },
        )
        session.add(job)
        session.commit()
        job_id = job.id

    with client.app.state.session_factory() as session:
        claimed = JobRepository(session).next_queued("test-worker")
        assert claimed is not None
        assert claimed.id == job_id
        assert claimed.status == "queued"
        assert claimed.worker_id == "test-worker"
        assert claimed.resource_assignment_json["device"] == "cuda:1"
        assert claimed.request_json["device_id"] == "cuda:1"

    with client.app.state.session_factory() as session:
        second_claim = JobRepository(session).next_queued("another-worker")
        assert second_claim is None

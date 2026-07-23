from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.db.models import Job
from reefvision.repositories.jobs import JobRepository
from reefvision.services.resource_scheduler import (
    GPUInventory,
    ResourceInventory,
    ResourceScheduler,
)

GIB = 1024**3


def inventory() -> ResourceInventory:
    return ResourceInventory(
        cpu_count=32,
        available_ram_bytes=128 * GIB,
        gpus=(
            GPUInventory(0, "cuda:0", "GPU 0", 24 * GIB, 20 * GIB),
            GPUInventory(1, "cuda:1", "GPU 1", 48 * GIB, 44 * GIB),
            GPUInventory(2, "cuda:2", "GPU 2", 48 * GIB, 40 * GIB),
        ),
    )


def test_scheduler_reserves_two_best_compatible_gpus(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "reefvision.services.resource_scheduler.collect_resource_inventory",
        inventory,
    )
    with client.app.state.session_factory() as session:
        candidate = Job(
            job_type="training",
            status="queued",
            request_json={"device": "auto"},
            result_json={},
            resource_requirements_json={
                "gpu_required": True,
                "gpu_count": 2,
                "minimum_vram_bytes_per_gpu": 16 * GIB,
                "exclusive_gpu": True,
            },
        )
        session.add(candidate)
        session.commit()
        decision = ResourceScheduler(session).evaluate(candidate)

    assert decision.eligible is True
    assert decision.assignment["gpu_indices"] == [1, 2]
    assert decision.assignment["gpu_count"] == 2
    assert decision.assignment["device"] == "1,2"
    assert decision.assignment["cuda_visible_devices"] == "1,2"
    assert decision.assignment["scheduler"] == "reefvision-local-v2"


def test_multi_gpu_reservation_respects_active_exclusive_devices(
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
                request_json={"device": "1,2"},
                result_json={},
                resource_requirements_json={
                    "gpu_required": True,
                    "gpu_count": 2,
                    "minimum_vram_bytes_per_gpu": 8 * GIB,
                    "exclusive_gpu": True,
                },
                resource_assignment_json={
                    "device": "1,2",
                    "gpu_index": 1,
                    "gpu_indices": [1, 2],
                },
            )
        )
        candidate = Job(
            job_type="training",
            status="queued",
            request_json={"device": "auto"},
            result_json={},
            resource_requirements_json={
                "gpu_required": True,
                "gpu_count": 2,
                "minimum_vram_bytes_per_gpu": 4 * GIB,
            },
        )
        session.add(candidate)
        session.commit()
        decision = ResourceScheduler(session).evaluate(candidate)

    assert decision.eligible is False
    assert any("Requires 2 compatible GPUs" in blocker for blocker in decision.blockers)


def test_explicit_multi_gpu_list_is_preserved_during_atomic_claim(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "reefvision.services.resource_scheduler.collect_resource_inventory",
        inventory,
    )
    with client.app.state.session_factory() as session:
        job = Job(
            job_type="training",
            status="queued",
            request_json={"device": "auto", "training_run_id": "run-1"},
            result_json={},
            resource_requirements_json={
                "device": "cuda:2,cuda:1",
                "gpu_required": True,
                "gpu_count": 2,
                "minimum_vram_bytes_per_gpu": 2 * GIB,
            },
        )
        session.add(job)
        session.commit()
        job_id = job.id

    with client.app.state.session_factory() as session:
        claimed = JobRepository(session).next_queued("multi-gpu-worker")
        assert claimed is not None
        assert claimed.id == job_id
        assert claimed.resource_assignment_json["gpu_indices"] == [2, 1]
        assert claimed.request_json["device"] == "2,1"
        assert claimed.request_json["assigned_gpu_indices"] == [2, 1]
        assert claimed.request_json["cuda_visible_devices"] == "2,1"


def test_explicit_list_and_gpu_count_must_agree(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "reefvision.services.resource_scheduler.collect_resource_inventory",
        inventory,
    )
    with client.app.state.session_factory() as session:
        candidate = Job(
            job_type="training",
            status="queued",
            request_json={},
            result_json={},
            resource_requirements_json={
                "device": "cuda:0,cuda:1",
                "gpu_required": True,
                "gpu_count": 3,
            },
        )
        session.add(candidate)
        session.commit()
        decision = ResourceScheduler(session).evaluate(candidate)

    assert decision.eligible is False
    assert any("does not match" in blocker for blocker in decision.blockers)

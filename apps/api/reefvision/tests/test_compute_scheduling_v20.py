"""Exercise resource controls through the public queue and a pair of local workers."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models import Job, TrainingRun
from reefvision.jobs.worker import process_next_thumbnail_job
from reefvision.tests.test_annotations import create_project


def queued(client: TestClient, project: str, kind: str, **request: object) -> str:
    with cast(FastAPI, client.app).state.session_factory() as session:
        job = Job(project_id=project, job_type=kind, status="queued", request_json=request)
        session.add(job)
        session.commit()
        return job.id


def test_paused_gpu_lane_skips_to_cpu_and_reopens_its_limits(client: TestClient) -> None:
    project = create_project(client, "Resource queue")["id"]
    other = create_project(client, "Other research")["id"]
    resources = "/api/v1/compute/resources"
    endpoint = f"/api/v1/projects/{project}/compute/jobs"
    app = cast(FastAPI, client.app)
    gpu = queued(client, project, "inference", device="cuda")
    cpu = queued(client, project, "thumbnail")
    foreign = queued(client, other, "inference", device="cuda")
    change = client.put(resources, json={"cpu_slots": 1, "gpu_slots": 0})
    assert change.status_code == 200, change.text
    assert client.get(resources).json()["gpu_slots"] == 0
    assert client.put(resources, json={"cpu_slots": -1, "gpu_slots": 1}).status_code == 422
    entries = client.get(endpoint, params={"limit": 1}).json()
    assert entries["total"] == 2 and entries["items"][0]["job"]["id"] == cpu
    gpu_view = client.get(endpoint, params={"offset": 1}).json()["items"][0]
    assert gpu_view["pool"] == "gpu" and "paused" in gpu_view["reason"].lower()
    assert entries["items"][0]["admission"] == "ready"
    assert foreign not in str(entries) and foreign not in str(gpu_view)
    # The CPU fixture has no image and fails in its normal handler. The GPU job stays queued.
    process_next_thumbnail_job(app.state.settings, app.state.session_factory)
    assert client.get(f"/api/v1/jobs/{cpu}").json()["status"] == "failed"
    assert client.get(f"/api/v1/jobs/{gpu}").json()["status"] == "queued"
    assert client.post(f"/api/v1/jobs/{cpu}/resume").status_code == 409
    assert client.post(f"/api/v1/jobs/{cpu}/retry").json()["id"] == cpu
    assert client.post(f"/api/v1/jobs/{gpu}/cancel").json()["status"] == "cancelled"


def test_concurrent_claims_share_capacity_and_do_not_duplicate_a_job(client: TestClient) -> None:
    from reefvision.services.compute_resources import claim_next, release

    project = create_project(client, "Independent workers")["id"]
    factory = cast(FastAPI, client.app).state.session_factory
    first = queued(client, project, "inference", device="cuda")
    second = queued(client, project, "inference", device="cuda")
    cpu = queued(client, project, "diagnostics")
    with ThreadPoolExecutor(max_workers=5) as pool:
        claims = [c for c in pool.map(lambda _: claim_next(factory), range(5)) if c is not None]
    assert {c.job_id for c in claims} == {first, cpu}
    rows = client.get(f"/api/v1/projects/{project}/compute/jobs").json()["items"]
    waiting = next(row for row in rows if row["job"]["id"] == second)
    assert waiting["admission"] == "waiting" and "slot" in waiting["reason"].lower()
    assert client.get("/api/v1/compute/resources").json()["gpu_in_use"] == 1
    for claim in claims:
        with factory() as session:
            session.get(Job, claim.job_id).status = "succeeded"
            session.commit()
        release(factory, claim)
    next_job = claim_next(factory)
    assert next_job is not None and next_job.job_id == second
    release(factory, next_job)


def test_restart_resumes_pin_after_one_durable_native_epoch(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reefvision.jobs.worker import recover_interrupted_jobs
    from reefvision.ml.reefpose.training import ReefPoseTrainer
    from reefvision.services.pose_training_exports import PoseTrainingExportService
    from reefvision.tests.test_workflow_pose_training_phase10 import (
        _frozen_dataset,
        _queue_native_reefpose_run,
        _synthetic_exact_frames,
    )

    app = cast(FastAPI, client.app)
    factory = app.state.session_factory
    monkeypatch.setattr(
        PoseTrainingExportService, "_extract_exact_frames", staticmethod(_synthetic_exact_frames)
    )
    project, data = _frozen_dataset(client, monkeypatch)
    run_id, job_id = _queue_native_reefpose_run(
        app, test_settings, project=project, dataset=data, epochs=2
    )
    fit = ReefPoseTrainer.fit

    def stop_at_epoch(self: ReefPoseTrainer, *args, **kwargs):
        report = kwargs["epoch_callback"]

        def power_lost(epoch, total, metrics):
            report(epoch, total, metrics)
            raise SystemExit("fixture worker stopped after durable epoch")

        return fit(self, *args, **{**kwargs, "epoch_callback": power_lost})

    with monkeypatch.context() as failure:
        failure.setattr(ReefPoseTrainer, "fit", stop_at_epoch)
        with pytest.raises(SystemExit, match="fixture worker stopped"):
            process_next_thumbnail_job(test_settings, factory)
    assert recover_interrupted_jobs(factory, test_settings) == 1
    endpoint = f"/api/v1/jobs/{job_id}"
    assert client.get(endpoint).json()["status"] == "failed"
    with factory() as session:
        run = session.get(TrainingRun, run_id)
        assert run.progress_epoch == 1
        manifest = run.artifact_manifest_json
        saved = Path(test_settings.resolved_data_dir, manifest["resume_checkpoint_path"])
        assert manifest["resume_checkpoint_sha256"]
    original = saved.read_bytes()
    saved.write_bytes(b"fixture altered checkpoint")
    blocked = client.post(endpoint + "/resume")
    assert blocked.status_code == 409 and "checksum" in blocked.text
    assert client.get(endpoint).json()["status"] == "failed"
    saved.write_bytes(original)
    for _ in range(2):
        response = client.post(endpoint + "/resume")
        assert response.status_code == 200, response.text
        assert response.json()["id"] == job_id and response.json()["progress_current"] == 1
    assert process_next_thumbnail_job(test_settings, factory)
    with factory() as session:
        run = session.get(TrainingRun, run_id)
        assert run.status == "completed" and run.metrics_history_json["epoch"] == [1, 2]
        assert run.job_id == job_id and run.result_checkpoint_path


def test_lost_dispatch_resumes_same_job_and_old_owner_cannot_release_it(
    client: TestClient,
    test_settings: Settings,
) -> None:
    from reefvision.jobs.worker import recover_interrupted_jobs
    from reefvision.services.compute_resources import claim_next, release
    from reefvision.storage.worker_lock import worker_leadership

    project = create_project(client, "Recover held slot")["id"]
    factory = cast(FastAPI, client.app).state.session_factory
    pending = queued(client, project, "inference", device="cuda")
    with worker_leadership(test_settings.resolved_data_dir) as first_leader:
        assert first_leader
        with worker_leadership(test_settings.resolved_data_dir) as second_leader:
            assert not second_leader
        old = claim_next(factory)
        assert old and old.job_id == pending
    with worker_leadership(test_settings.resolved_data_dir) as new_leader:
        assert new_leader
        recover_interrupted_jobs(factory, test_settings)
        retry = claim_next(factory)
        assert retry and retry.job_id == pending and retry.token != old.token
        release(factory, old)
        assert client.get("/api/v1/compute/resources").json()["gpu_in_use"] == 1
        assert claim_next(factory) is None
        release(factory, retry)
    assert client.get("/api/v1/compute/resources").json()["gpu_in_use"] == 0

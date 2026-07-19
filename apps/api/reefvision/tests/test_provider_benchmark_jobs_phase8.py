from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.jobs.provider_benchmarks import process_provider_benchmark_job


def test_mock_provider_benchmark_runs_through_worker(client: TestClient) -> None:
    queued = client.post(
        "/api/v1/provider-benchmarks/runs",
        json={
            "provider_id": "mock",
            "task": "segment",
            "device_id": "cpu",
            "input_width": 64,
            "input_height": 64,
            "batch_size": 1,
            "sample_count": 3,
            "warmup_count": 1,
            "parameters": {"fixture": True},
        },
    )
    assert queued.status_code == 202
    job_id = queued.json()["job"]["id"]

    processed = process_provider_benchmark_job(
        client.app.state.settings,
        client.app.state.session_factory,
        job_id,
    )
    assert processed is True

    job = client.get(f"/api/v1/jobs/{job_id}")
    assert job.status_code == 200
    payload = job.json()
    assert payload["status"] == "succeeded"
    assert payload["progress_current"] == 4
    benchmark = payload["result_json"]["benchmark"]
    assert benchmark["provider_id"] == "mock"
    assert benchmark["sample_count"] == 3
    assert benchmark["throughput_per_second"] > 0

    comparison = client.get(
        "/api/v1/provider-benchmarks/compare",
        params={"provider_id": "mock", "task": "segment"},
    )
    assert comparison.status_code == 200
    records = comparison.json()["records"]
    assert len(records) == 1
    assert records[0]["parameters"]["execution_mode"] == "queued_provider_benchmark"


def test_non_mock_benchmark_requires_image_ids(client: TestClient) -> None:
    response = client.post(
        "/api/v1/provider-benchmarks/runs",
        json={
            "provider_id": "depth_anything_v2",
            "task": "depth",
            "model_id": "depth-anything/Depth-Anything-V2-Small-hf",
            "sample_count": 1,
        },
    )
    assert response.status_code == 422

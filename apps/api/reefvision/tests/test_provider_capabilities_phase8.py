from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_provider_capability_routes_expose_health_and_benchmarks(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/provider-capabilities")
    assert response.status_code == 200
    payload = response.json()
    providers = {item["provider_id"]: item for item in payload["providers"]}

    assert "mock" in providers
    assert providers["mock"]["health"] == "ready"
    assert providers["mock"]["supported_prompt_types"] == [
        "box",
        "positive_point",
        "negative_point",
        "brush",
    ]
    assert any(device["device_id"] == "cpu" for device in providers["mock"]["devices"])

    detail = client.get("/api/v1/provider-capabilities/mock")
    assert detail.status_code == 200
    assert detail.json()["display_name"] == "Mock provider"

    recorded = client.post(
        "/api/v1/provider-benchmarks",
        json={
            "provider_id": "mock",
            "model_id": None,
            "device_id": "cpu",
            "task": "segment",
            "input_width": 640,
            "input_height": 640,
            "batch_size": 1,
            "sample_count": 3,
            "warmup_count": 1,
            "latencies_ms": [10.0, 12.0, 14.0],
            "elapsed_seconds": 0.036,
            "peak_ram_bytes": 1048576,
            "peak_vram_bytes": None,
            "quality_metrics": {"mean_iou": 0.75},
            "parameters": {"fixture": True},
        },
    )
    assert recorded.status_code == 201
    benchmark = recorded.json()
    assert benchmark["mean_latency_ms"] == pytest.approx(12.0)
    assert benchmark["median_latency_ms"] == pytest.approx(12.0)
    assert benchmark["p95_latency_ms"] == pytest.approx(13.8)
    assert benchmark["throughput_per_second"] == pytest.approx(83.33333333333333)

    comparison = client.get(
        "/api/v1/provider-benchmarks/compare",
        params={"provider_id": "mock", "task": "segment"},
    )
    assert comparison.status_code == 200
    comparison_payload = comparison.json()
    assert len(comparison_payload["records"]) == 1
    assert comparison_payload["fastest_record"]["provider_id"] == "mock"
    assert comparison_payload["warnings"] == []


def test_provider_capability_routes_reject_unknown_provider(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/provider-capabilities/not-a-provider")
    assert response.status_code == 404

    benchmark = client.post(
        "/api/v1/provider-benchmarks",
        json={
            "provider_id": "not-a-provider",
            "device_id": "cpu",
            "task": "segment",
            "input_width": 64,
            "input_height": 64,
            "batch_size": 1,
            "sample_count": 1,
            "warmup_count": 0,
            "latencies_ms": [1.0],
            "elapsed_seconds": 0.001,
        },
    )
    assert benchmark.status_code == 400

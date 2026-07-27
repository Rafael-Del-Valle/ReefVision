from __future__ import annotations

from fastapi.testclient import TestClient


def test_sam2_sidecar_reports_unavailable_without_blocking_api_startup(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/sam2-sidecar/health",
        json={
            "endpoint": "http://127.0.0.1:8766",
            "token_env": "REEFVISION_SAM2_SIDECAR_TOKEN",
            "timeout_seconds": 120,
        },
    )

    assert response.status_code == 503
    assert "provider contract is incomplete" in response.json()["detail"]
    assert client.get("/api/v1/health").status_code == 200

from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.services.advanced_provider_execution import (
    PROVIDER_LAB_EXECUTION_IDS,
)


def test_advanced_provider_manifests_distinguish_execution_surfaces(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/advanced-providers/manifests")
    assert response.status_code == 200, response.text

    manifests = {item["provider_id"]: item for item in response.json()}

    assert {
        "grounding_dino",
        "sam2",
        "smolvlm",
        "nnunet",
    } == PROVIDER_LAB_EXECUTION_IDS

    for provider_id in PROVIDER_LAB_EXECUTION_IDS:
        assert manifests[provider_id]["execution_supported"] is True
        assert manifests[provider_id]["execution_surface"] == "provider_lab"

    assert manifests["segment_anything"]["execution_supported"] is True
    assert manifests["segment_anything"]["execution_surface"] == "existing_workflow"

    for provider_id in {
        "owlv2",
        "florence2",
        "mobilesam",
        "fastsam",
        "depth_anything_v2",
    }:
        assert manifests[provider_id]["execution_supported"] is False
        assert manifests[provider_id]["execution_surface"] == "blocked"

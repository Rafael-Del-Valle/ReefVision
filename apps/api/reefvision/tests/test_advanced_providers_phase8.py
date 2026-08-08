from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project


def test_advanced_provider_manifests_are_explicit(client: TestClient) -> None:
    response = client.get("/api/v1/advanced-providers/manifests")
    assert response.status_code == 200, response.text
    manifests = {item["provider_id"]: item for item in response.json()}

    assert manifests["segment_anything"]["execution_supported"] is True
    assert manifests["sam2"]["execution_supported"] is True
    assert manifests["sam2"]["supported_tasks"] == ["assist_segmentation"]
    assert manifests["sam2"]["required_model_extensions"] == [".zip"]
    assert manifests["depth_anything_v2"]["execution_supported"] is True
    assert manifests["depth_anything_v2"]["required_model_extensions"] == [".zip"]
    assert manifests["depth_anything_v2"]["output_contracts_by_task"]["relative_depth"] == [
        "relative_depth_array",
        "depth_preview",
        "value_range",
    ]
    assert any(
        "relative depth" in message.lower()
        for message in manifests["depth_anything_v2"]["known_limitations"]
    )
    assert any(
        "video propagation" in message.lower()
        for message in manifests["sam2"]["known_limitations"]
    )


def test_executable_provider_preflight_still_fails_closed_without_model(
    client: TestClient,
) -> None:
    project = create_project(client, "Provider preflight")
    response = client.post(
        f"/api/v1/projects/{project['id']}/advanced-providers/depth_anything_v2/preflight",
        json={
            "task": "relative_depth",
            "device": "cpu",
            "prompt_fields": {"image_id": "image-1"},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ready"] is False
    assert payload["execution_supported"] is True
    assert payload["output_contract"] == [
        "relative_depth_array",
        "depth_preview",
        "value_range",
    ]
    assert any("model" in blocker.lower() for blocker in payload["blockers"])


def test_provider_preflight_reports_missing_prompts(client: TestClient) -> None:
    project = create_project(client, "Prompt preflight")
    response = client.post(
        f"/api/v1/projects/{project['id']}/advanced-providers/grounding_dino/preflight",
        json={
            "task": "open_vocabulary_detect",
            "device": "auto",
            "prompt_fields": {"image_id": "image-1"},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload["missing_prompt_fields"]) == {"text_prompts", "confidence"}
    assert payload["ready"] is False

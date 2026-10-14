"""1.0.1 regression: detector class identities survive registration and acceptance."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from reefvision.ml.providers import DetectionModelMetadata
from reefvision.services.models import ModelService


class _FixtureDetector:
    provider_name = "patch_101_test"
    provider_version = "test"

    def inspect_model(self, model_path: Any) -> DetectionModelMetadata:
        return DetectionModelMetadata(
            framework="ultralytics",
            task="detect",
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            class_labels=["Swiftia exserta", "Thesea nivea"],
            input_size={"imgsz": 640},
            metadata={},
        )


def test_model_registration_creates_missing_project_classes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ModelService,
        "_provider_for_purpose",
        lambda self, purpose: _FixtureDetector(),
    )
    created = client.post(
        "/api/v1/projects", json={"name": "New labels from model", "template": "blank"}
    )
    assert created.status_code == 201, created.text
    project = cast(dict[str, Any], created.json())
    project_id = project["id"]
    assert project["label_classes"] == []

    response = client.post(
        f"/api/v1/projects/{project_id}/models/register",
        files={"file": ("coral-best.pt", b"test-model", "application/octet-stream")},
        data={"purpose": "detector", "display_name": "Coral model"},
    )
    assert response.status_code == 200, response.text
    registered = response.json()
    mapping = registered["class_map_json"]["mapping"]
    assert mapping["Swiftia exserta"] is not None
    assert mapping["Thesea nivea"] is not None
    assert mapping["Swiftia exserta"] != mapping["Thesea nivea"]

    reread = client.get(f"/api/v1/projects/{project_id}")
    assert reread.status_code == 200, reread.text
    classes = {item["name"]: item for item in reread.json()["label_classes"]}
    assert set(classes) == {"Swiftia exserta", "Thesea nivea"}
    assert classes["Swiftia exserta"]["id"] == mapping["Swiftia exserta"]
    assert classes["Thesea nivea"]["id"] == mapping["Thesea nivea"]

    second = client.post(
        f"/api/v1/projects/{project_id}/models/register",
        files={"file": ("coral-other.pt", b"different-test-model", "application/octet-stream")},
        data={"purpose": "detector", "display_name": "Coral model 2"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["class_map_json"]["mapping"] == mapping
    reread = client.get(f"/api/v1/projects/{project_id}")
    assert len(reread.json()["label_classes"]) == 2

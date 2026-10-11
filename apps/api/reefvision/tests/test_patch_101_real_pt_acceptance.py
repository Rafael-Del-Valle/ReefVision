"""Release regression: inspect an actual locally generated .pt checkpoint.

Unlike lightweight fake-provider tests, this exercises Ultralytics serialization,
real checkpoint loading, automatic project-class identities and an inference job.
The model is untrained and may legitimately return zero detections; it must not
be represented as a scientifically validated detector.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.ml.providers as providers_module
from reefvision.jobs.inference import process_inference_job
from reefvision.tests.test_annotations import import_one


@pytest.mark.integration
def test_actual_ultralytics_pt_metadata_and_inference_job(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ultralytics
    from ultralytics import YOLO

    base_config_path = Path(ultralytics.__file__).resolve().parent / "cfg/models/11/yolo11.yaml"
    assert base_config_path.is_file(), "Installed Ultralytics has no YOLO11 YAML"
    config = yaml.safe_load(base_config_path.read_text(encoding="utf-8"))
    config["nc"] = 2
    config["scale"] = "n"
    local_yaml = tmp_path / "reefvision-two-class.yaml"
    local_yaml.write_text(yaml.safe_dump(config), encoding="utf-8")

    # This builds and serializes random architecture weights locally: no
    # pretrained model, network checkpoint or proprietary dataset is acquired.
    detector = YOLO(str(local_yaml))
    detector.model.names = {0: "Swiftia exserta", 1: "Thesea nivea"}
    # Ultralytics initializes .ckpt to None for models created from YAML.
    # Its save() method expands that mapping, so seed an empty checkpoint
    # rather than downloading pretrained weights solely to serialize a fixture.
    detector.ckpt = {}
    checkpoint = tmp_path / "reefvision-two-class.pt"
    detector.save(str(checkpoint))
    assert checkpoint.is_file() and checkpoint.stat().st_size > 0

    # Only bypass platform-specific preflight intended for pinned Windows builds.
    # The actual Ultralytics model inspection and inference are not mocked.
    monkeypatch.setattr(providers_module, "configure_provider_runtime", lambda: None)
    monkeypatch.setattr(providers_module, "require_provider_ready", lambda _: None)

    created = client.post(
        "/api/v1/projects",
        json={"name": "Real local PT acceptance", "template": "blank"},
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    image_id = import_one(client, project_id, filename="coral-pt.png")["successful"][0]["image_id"]

    registered = client.post(
        f"/api/v1/projects/{project_id}/models/register",
        files={
            "file": (
                checkpoint.name,
                checkpoint.read_bytes(),
                "application/octet-stream",
            )
        },
        data={
            "purpose": "detector",
            "display_name": "Locally generated two-class model",
        },
    )
    assert registered.status_code == 200, registered.text
    model = cast(dict[str, Any], registered.json())
    assert model["provider_name"] == "ultralytics"
    assert model["framework"] == "ultralytics"
    assert model["class_map_json"]["labels"] == ["Swiftia exserta", "Thesea nivea"]
    mapping = model["class_map_json"]["mapping"]
    assert mapping["Swiftia exserta"] and mapping["Thesea nivea"]
    assert mapping["Swiftia exserta"] != mapping["Thesea nivea"]

    project_response = client.get(f"/api/v1/projects/{project_id}")
    assert project_response.status_code == 200, project_response.text
    project_classes = {
        item["name"]: item["id"] for item in project_response.json()["label_classes"]
    }
    assert project_classes == mapping

    job_response = client.post(
        f"/api/v1/projects/{project_id}/inference-jobs",
        json={"model_id": model["id"], "image_ids": [image_id], "device": "cpu"},
    )
    assert job_response.status_code == 200, job_response.text
    job_id = job_response.json()["id"]
    app = cast(FastAPI, client.app)
    assert process_inference_job(app.state.settings, app.state.session_factory, job_id)
    completed = client.get(f"/api/v1/jobs/{job_id}")
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "succeeded", completed.json().get("error_message")

    proposals = client.get(f"/api/v1/images/{image_id}/prediction-proposals")
    assert proposals.status_code == 200, proposals.text
    assert all(
        proposal["review_status"] == "pending"
        and proposal["predicted_label"] in mapping
        and proposal["model_checksum"] == model["sha256"]
        for proposal in proposals.json()["items"]
    )

    # Registration/inference must not silently approve untrained predictions.
    annotated = client.get(f"/api/v1/images/{image_id}/annotations")
    assert annotated.status_code == 200, annotated.text
    assert annotated.json()["annotations"] == []

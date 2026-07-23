from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import reefvision.ml.sam3_sidecar as sam3_module
from reefvision.ml.providers import DetectionSettings
from reefvision.ml.sam3_sidecar import Sam3SidecarSegmentationProvider
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project


def _mask_payload(size: tuple[int, int]) -> str:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle((2, 3, 9, 11), fill=255)
    stream = BytesIO()
    mask.save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def test_sam3_sidecar_registration_creates_verified_descriptor(
    client: TestClient,
) -> None:
    project = create_project(client, "SAM 3 workflow")
    label_class_id = project["label_classes"][0]["id"]
    response = client.post(
        f"/api/v1/projects/{project['id']}/sam3-sidecar-models",
        json={
            "display_name": "SAM 3 Swiftia",
            "endpoint": "http://127.0.0.1:8765",
            "concept_prompt": "Swiftia exserta colony",
            "label_class_id": label_class_id,
            "score_threshold": 0.4,
        },
    )
    assert response.status_code == 201, response.text
    model = response.json()
    assert model["purpose"] == "segmenter"
    assert model["task"] == "segment"
    assert model["provider_name"] == "sam3_sidecar"
    assert model["class_map_json"]["mapping"]["Swiftia exserta colony"] == label_class_id
    path = resolve_managed_project_path(
        client.app.state.settings,
        model["managed_path"],
    )
    descriptor = json.loads(path.read_text(encoding="utf-8"))
    assert descriptor["schema"] == "reefvision-sam3-sidecar-v1"
    assert descriptor["endpoint"] == "http://127.0.0.1:8765"
    assert descriptor["score_threshold"] == 0.4


def test_sam3_sidecar_registration_rejects_non_loopback_endpoint(
    client: TestClient,
) -> None:
    project = create_project(client, "Blocked SAM 3 endpoint")
    response = client.post(
        f"/api/v1/projects/{project['id']}/sam3-sidecar-models",
        json={
            "display_name": "Unsafe SAM 3",
            "endpoint": "https://example.com/sam3",
            "concept_prompt": "coral",
            "label_class_id": project["label_classes"][0]["id"],
        },
    )
    assert response.status_code in {400, 422}
    assert "localhost" in response.text


def test_sam3_sidecar_provider_converts_response_to_raster_prediction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor_path = tmp_path / "sam3.sam3.json"
    descriptor_path.write_text(
        json.dumps(
            {
                "schema": "reefvision-sam3-sidecar-v1",
                "endpoint": "http://127.0.0.1:8765",
                "concept_prompt": "soft coral",
                "output_label": "soft coral",
                "score_threshold": 0.35,
                "timeout_seconds": 30,
                "token_env": "REEFVISION_SAM3_SIDECAR_TOKEN",
                "sam3_version": "sam3.1",
            }
        ),
        encoding="utf-8",
    )
    image_path = tmp_path / "source.png"
    Image.new("RGB", (20, 15), (20, 90, 120)).save(image_path)
    observed: dict[str, Any] = {}

    def fake_post_json(
        url: str,
        *,
        token: str | None,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        observed.update(
            {
                "url": url,
                "token": token,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "model_version": "sam3.1-test",
            "instances": [
                {
                    "score": 0.82,
                    "box": [2, 3, 10, 12],
                    "mask_png_base64": _mask_payload((20, 15)),
                }
            ],
        }

    monkeypatch.setattr(sam3_module, "_post_json", fake_post_json)
    provider = Sam3SidecarSegmentationProvider()
    provider.load_model(descriptor_path, "cuda:0")
    predictions = provider.predict(
        image_path,
        DetectionSettings(
            confidence_threshold=0.5,
            iou_threshold=0.45,
            device="cuda:0",
        ),
    )

    assert len(predictions) == 1
    prediction = predictions[0]
    assert prediction.label == "soft coral"
    assert prediction.confidence == 0.82
    assert prediction.box.x_min == 2
    assert prediction.box.y_max == 12
    assert prediction.mask_png_bytes is not None
    assert prediction.mask_png_bytes.startswith(b"\x89PNG")
    assert observed["url"] == "http://127.0.0.1:8765/segment"
    assert observed["payload"]["prompt"] == "soft coral"
    assert observed["payload"]["score_threshold"] == 0.5
    assert provider.provider_version == "sam3.1-test"

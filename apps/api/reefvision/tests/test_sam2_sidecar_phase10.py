from __future__ import annotations

import json
from io import BytesIO

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import PixelBox
from reefvision.ml.sam2_sidecar import (
    PreparedSam2SidecarImage,
    SAM2SidecarAssistProvider,
    _mask_prediction,
)
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project


def test_register_sam2_sidecar_descriptor(client: TestClient) -> None:
    project = create_project(client, "SAM 2 sidecar")
    response = client.post(
        f"/api/v1/projects/{project['id']}/sam2-sidecar-models",
        json={
            "display_name": "SAM 2 Hiera Large Sidecar",
            "endpoint": "http://127.0.0.1:8766",
            "token_env": "REEFVISION_SAM2_SIDECAR_TOKEN",
            "timeout_seconds": 180,
        },
    )
    assert response.status_code == 201, response.text
    model = response.json()
    assert model["purpose"] == "assist"
    assert model["task"] == "assist_segmentation"
    assert model["provider_name"] == "sam2_sidecar"
    assert model["framework"] == "sam2-sidecar"
    path = resolve_managed_project_path(
        client.app.state.settings,
        model["managed_path"],
    )
    descriptor = json.loads(path.read_text(encoding="utf-8"))
    assert descriptor["schema"] == "reefvision-sam2-sidecar-v1"
    assert descriptor["endpoint"] == "http://127.0.0.1:8766"
    assert "token" not in descriptor


def test_sam2_sidecar_health_endpoint_is_mounted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_get_json(
        url: str,
        *,
        token: str | None,
        timeout_seconds: float,
    ) -> dict[str, object]:
        observed.update(
            {
                "url": url,
                "token": token,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "status": "ok",
            "provider": "sam2_sidecar",
            "model_version": "sam2.1_hiera_large.pt",
            "device": "cuda:1",
        }

    monkeypatch.setenv("REEFVISION_TEST_SAM2_TOKEN", "secret")
    monkeypatch.setattr("reefvision.ml.sam2_sidecar._get_json", fake_get_json)
    response = client.post(
        "/api/v1/sam2-sidecar/health",
        json={
            "endpoint": "http://localhost:8766/",
            "token_env": "REEFVISION_TEST_SAM2_TOKEN",
            "timeout_seconds": 15,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload == {
        "status": "ok",
        "provider": "sam2_sidecar",
        "model_version": "sam2.1_hiera_large.pt",
        "device": "cuda:1",
        "endpoint": "http://localhost:8766",
        "token_configured": True,
    }
    assert observed == {
        "url": "http://localhost:8766/health",
        "token": "secret",
        "timeout_seconds": 15.0,
    }


def test_sam2_sidecar_health_rejects_non_sidecar_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "reefvision.ml.sam2_sidecar._get_json",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "provider": "different-service",
            "device": "cpu",
        },
    )
    response = client.post(
        "/api/v1/sam2-sidecar/health",
        json={"endpoint": "http://127.0.0.1:8766"},
    )
    assert response.status_code == 422
    assert "not a ReefVision SAM 2 sidecar" in response.text


def test_sam2_sidecar_descriptor_must_use_loopback(tmp_path) -> None:
    descriptor = tmp_path / "sam2.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema": "reefvision-sam2-sidecar-v1",
                "endpoint": "https://example.com/sam2",
                "token_env": "REEFVISION_SAM2_SIDECAR_TOKEN",
            }
        ),
        encoding="utf-8",
    )
    provider = SAM2SidecarAssistProvider()
    with pytest.raises(ValidationError, match="localhost"):
        provider.load_model(descriptor, "cuda:0")


def test_sam2_sidecar_mask_response_is_binary_boxed_and_dimension_checked() -> None:
    mask = np.zeros((12, 16), dtype=np.uint8)
    mask[2:8, 4:10] = 255
    stream = BytesIO()
    Image.fromarray(mask, mode="L").save(stream, format="PNG")
    import base64

    prediction = _mask_prediction(
        {
            "mask_png_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
            "score": 0.91,
        },
        width=16,
        height=12,
    )
    assert prediction.score == 0.91
    assert prediction.mask.dtype == np.bool_
    assert int(prediction.mask.sum()) == 36
    assert prediction.box == PixelBox(x_min=4.0, y_min=2.0, x_max=10.0, y_max=8.0)

    with pytest.raises(ValidationError, match="dimensions"):
        _mask_prediction(
            {
                "mask_png_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
                "score": 0.91,
            },
            width=17,
            height=12,
        )


def test_sam2_sidecar_box_validation_happens_before_network(tmp_path) -> None:
    descriptor = tmp_path / "sam2.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema": "reefvision-sam2-sidecar-v1",
                "endpoint": "http://127.0.0.1:8766",
                "token_env": "REEFVISION_SAM2_SIDECAR_TOKEN",
            }
        ),
        encoding="utf-8",
    )
    provider = SAM2SidecarAssistProvider()
    provider.load_model(descriptor, "cuda:0")
    prepared = PreparedSam2SidecarImage(
        image_png_base64="placeholder",
        width=100,
        height=80,
    )
    with pytest.raises(ValidationError, match="outside"):
        provider.predict_from_box(
            prepared,
            PixelBox(x_min=-1, y_min=0, x_max=10, y_max=10),
        )

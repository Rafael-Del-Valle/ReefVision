from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import PixelBox, PixelPoint
from reefvision.ml.sam2_sidecar import (
    PreparedSam2SidecarImage,
    SAM2SidecarAssistProvider,
)
from reefvision.tests.test_annotations import create_project, import_one


def _descriptor(tmp_path: Path) -> Path:
    path = tmp_path / "sam2.json"
    path.write_text(
        json.dumps(
            {
                "schema": "reefvision-sam2-sidecar-v1",
                "endpoint": "http://127.0.0.1:8766",
                "token_env": "REEFVISION_SAM2_SIDECAR_TOKEN",
            }
        ),
        encoding="utf-8",
    )
    return path


def _mask_response(*, width: int, height: int) -> dict[str, object]:
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[10:30, 20:50] = 255
    stream = BytesIO()
    Image.fromarray(mask, mode="L").save(stream, format="PNG")
    return {
        "mask_png_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
        "score": 0.93,
        "model_version": "sam2.1_hiera_large.pt",
    }


def test_sam2_sidecar_point_prompts_are_sent_with_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SAM2SidecarAssistProvider()
    provider.load_model(_descriptor(tmp_path), "cuda:0")
    prepared = PreparedSam2SidecarImage(
        image_png_base64="encoded-image",
        width=100,
        height=80,
    )
    observed: dict[str, object] = {}

    def fake_post_json(
        url: str,
        *,
        token: str | None,
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        observed.update(
            {
                "url": url,
                "token": token,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return _mask_response(width=100, height=80)

    monkeypatch.setattr("reefvision.ml.sam2_sidecar._post_json", fake_post_json)
    prediction = provider.predict_from_points(
        prepared,
        positive_points=[PixelPoint(30, 20), PixelPoint(35, 25)],
        negative_points=[PixelPoint(10, 10)],
        context_box=PixelBox(5, 5, 70, 60),
    )

    assert prediction.score == 0.93
    assert int(prediction.mask.sum()) == 600
    assert provider.provider_version == "sam2.1_hiera_large.pt"
    assert observed == {
        "url": "http://127.0.0.1:8766/segment-points",
        "token": None,
        "payload": {
            "image_png_base64": "encoded-image",
            "positive_points": [[30, 20], [35, 25]],
            "negative_points": [[10, 10]],
            "context_box": [5, 5, 70, 60],
            "device": "cuda:0",
        },
        "timeout_seconds": 120.0,
    }


def test_sam2_sidecar_point_validation_happens_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SAM2SidecarAssistProvider()
    provider.load_model(_descriptor(tmp_path), "cuda:0")
    prepared = PreparedSam2SidecarImage(
        image_png_base64="encoded-image",
        width=100,
        height=80,
    )

    def unexpected_post(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("Network request should not be attempted")

    monkeypatch.setattr("reefvision.ml.sam2_sidecar._post_json", unexpected_post)
    with pytest.raises(ValidationError, match="point prompt is outside"):
        provider.predict_from_points(
            prepared,
            positive_points=[PixelPoint(100, 20)],
            negative_points=[],
        )


def test_sam2_sidecar_requires_positive_point_or_context_box(
    tmp_path: Path,
) -> None:
    provider = SAM2SidecarAssistProvider()
    provider.load_model(_descriptor(tmp_path), "cuda:0")
    prepared = PreparedSam2SidecarImage(
        image_png_base64="encoded-image",
        width=100,
        height=80,
    )

    with pytest.raises(ValidationError, match="positive point or context box"):
        provider.predict_from_points(
            prepared,
            positive_points=[],
            negative_points=[PixelPoint(10, 10)],
        )


def test_registered_sam2_sidecar_runs_interactive_point_session(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "SAM 2 interactive Prompt Assist")
    report = import_one(client, project["id"], size=(100, 80))
    image_id = report["successful"][0]["image_id"]

    registered = client.post(
        f"/api/v1/projects/{project['id']}/sam2-sidecar-models",
        json={
            "display_name": "SAM 2 Sidecar",
            "endpoint": "http://127.0.0.1:8766",
            "token_env": "REEFVISION_SAM2_SIDECAR_TOKEN",
            "timeout_seconds": 120,
        },
    )
    assert registered.status_code == 201, registered.text
    model = registered.json()
    observed: dict[str, object] = {}

    def fake_post_json(
        url: str,
        *,
        token: str | None,
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        observed.update(
            {
                "url": url,
                "token": token,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return _mask_response(width=100, height=80)

    monkeypatch.setattr("reefvision.ml.sam2_sidecar._post_json", fake_post_json)
    created = client.post(
        f"/api/v1/images/{image_id}/assist-sessions",
        json={"model_id": model["id"], "device": "cuda:0"},
    )
    assert created.status_code == 200, created.text
    session = created.json()
    assert session["provider_name"] == "sam2_sidecar"

    prompted = client.post(
        f"/api/v1/assist-sessions/{session['session_id']}/points",
        json={
            "positive_points": [{"x": 30, "y": 20}],
            "negative_points": [{"x": 10, "y": 10}],
            "context_box": {
                "x_min": 5,
                "y_min": 5,
                "x_max": 70,
                "y_max": 60,
            },
        },
    )
    assert prompted.status_code == 200, prompted.text
    result = prompted.json()
    assert result["positive_point_count"] == 1
    assert result["negative_point_count"] == 1
    assert result["prompt_type"] == "point_prompt"
    assert result["candidate_mask_png_base64"]
    assert result["candidate_box"] == {
        "x_min": 20.0,
        "y_min": 10.0,
        "x_max": 50.0,
        "y_max": 30.0,
    }
    request_payload = observed["payload"]
    assert isinstance(request_payload, dict)
    assert request_payload["positive_points"] == [[30.0, 20.0]]
    assert request_payload["negative_points"] == [[10.0, 10.0]]
    assert request_payload["context_box"] == [5.0, 5.0, 70.0, 60.0]

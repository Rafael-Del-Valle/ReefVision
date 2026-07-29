from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import PixelBox, PixelPoint
from reefvision.ml.sam2_sidecar import (
    PreparedSam2SidecarImage,
    SAM2SidecarAssistProvider,
)


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

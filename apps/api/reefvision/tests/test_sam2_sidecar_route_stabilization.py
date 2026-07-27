from __future__ import annotations

import base64
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from reefvision.ml.sam2_sidecar import _mask_prediction


def test_sam2_sidecar_prediction_uses_shared_assist_contract(
    client: TestClient,
) -> None:
    mask = Image.new("L", (4, 3), 0)
    mask.putpixel((1, 1), 255)
    mask.putpixel((2, 1), 255)
    stream = BytesIO()
    mask.save(stream, format="PNG")

    prediction = _mask_prediction(
        {
            "mask_png_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
            "score": 0.75,
        },
        width=4,
        height=3,
    )

    assert prediction.score == 0.75
    assert prediction.box.x_min == 1
    assert prediction.box.y_min == 1
    assert prediction.box.x_max == 3
    assert prediction.box.y_max == 2
    assert client.get("/api/v1/health").status_code == 200

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.config import Settings
from reefvision.jobs.inference import process_inference_job
from reefvision.ml.providers import DetectionPrediction, PixelBox
from reefvision.schemas.image_adjustments_v18 import PhotometricParameters
from reefvision.services.models import ModelService
from reefvision.storage.image_adjustments_v18 import (
    AdjustmentRendition,
    publish_adjusted_rendition,
    render_adjustment,
)
from reefvision.tests.test_images import create_project, import_one
from reefvision.tests.test_model_inference import FakeDetectorRegistrationProvider, register_model

SOURCE_PIXELS = [
    (10, 20, 30),
    (20, 40, 60),
    (60, 80, 90),
    (180, 64, 42),
    (90, 190, 30),
    (250, 220, 110),
]
ADJUSTED_PIXELS = [
    (20, 20, 15),
    (40, 40, 30),
    (120, 80, 45),
    (255, 64, 21),
    (180, 190, 15),
    (255, 220, 55),
]
ADJUSTED_RGB_BYTES = b"".join(bytes(pixel) for pixel in ADJUSTED_PIXELS)
PARAMETERS = {"red_gain_percent": 200, "blue_gain_percent": 50}


def source_fixture(mode: str = "RGB", orientation: int = 6) -> bytes:
    image = Image.new(mode, (3, 2))
    if mode == "RGB":
        image.putdata(SOURCE_PIXELS)
    metadata = Image.Exif()
    metadata[274] = orientation
    stream = BytesIO()
    image.save(stream, format="PNG", exif=metadata)
    return stream.getvalue()


def test_atomic_adjustment_publication_with_standard_long_windows_path(tmp_path: Path) -> None:
    # The full digest name may fit ordinary Win32 paths while repeating it in
    # the same-directory staging filename exceeds the limit.
    parent = tmp_path / ("p" * max(1, 189 - len(str(tmp_path))))
    png = source_fixture()
    digest = sha256(png).hexdigest()
    path = parent / f"{digest}.png"
    publish_adjusted_rendition(path, AdjustmentRendition(png, digest, ""))
    assert path.read_bytes() == png
    assert list(parent.iterdir()) == [path]


def test_canonical_png_decodes_across_stored_deflate_boundaries() -> None:
    width, height = 280, 120
    source = Image.new("RGB", (width, height), (10, 50, 180))
    source.putpixel((width - 1, height - 1), (164, 32, 28))
    stream = BytesIO()
    source.save(stream, format="PNG")
    original = stream.getvalue()
    original_sha = sha256(original).hexdigest()
    params = PhotometricParameters(brightness_offset=2)
    rendition = render_adjustment(original, original_sha, width, height, params)
    assert rendition == render_adjustment(original, original_sha, width, height, params)
    with Image.open(BytesIO(rendition.png)) as decoded:
        assert decoded.getpixel((0, 0)) == (12, 52, 182)
        assert decoded.getpixel((width - 1, height - 1)) == (166, 34, 30)
        assert sha256(decoded.tobytes()).hexdigest() == rendition.rgb_sha256


def make_source(client: TestClient, mode: str = "RGB") -> tuple[dict[str, Any], str, bytes]:
    project = create_project(client)
    original = source_fixture(mode)
    report = import_one(client, project["id"], content=original)
    image_id = report["successful"][0]["image_id"]
    return project, image_id, original


def save_recipe(client: TestClient, image_id: str, source: bytes) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/images/{image_id}/adjustments",
        json={"original_sha256": sha256(source).hexdigest(), "parameters": PARAMETERS},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_known_answer_recipe_preserves_raw_axes_original_and_history(
    client: TestClient, test_settings: Settings
) -> None:
    project, image_id, original = make_source(client)
    expected_source = sha256(original).hexdigest()
    image = f"/api/v1/images/{image_id}"
    endpoint = image + "/adjustments"
    preview = client.post(
        endpoint + "/preview",
        json={"original_sha256": expected_source, "parameters": PARAMETERS},
    )
    assert preview.status_code == 200, preview.text
    with Image.open(BytesIO(preview.content)) as decoded:
        assert decoded.mode == "RGB" and decoded.size == (3, 2)
        assert decoded.getexif().get(274) is None
        assert decoded.tobytes() == ADJUSTED_RGB_BYTES
    assert client.get(endpoint).json()["items"] == []

    saved = save_recipe(client, image_id, original)
    row = saved["receipt"]
    assert row["project_id"] == project["id"] and row["image_id"] == image_id
    assert row["original_sha256"] == expected_source
    assert row["pixel_axes"] == "raw_source"
    assert row["rendition_sha256"] == sha256(preview.content).hexdigest()
    assert (
        row["rgb_sha256"]
        == sha256(bytes(value for pixel in ADJUSTED_PIXELS for value in pixel)).hexdigest()
    )
    record = f"{endpoint}/{saved['id']}"
    assert client.get(record).json() == saved
    assert client.get(endpoint).json()["items"] == [saved]
    assert save_recipe(client, image_id, original) == saved
    assert client.get(record + "/rendition").content == preview.content
    assert "attachment" in client.get(record + "/export").headers["content-disposition"]
    assert client.get(record + "/export").json() == saved

    # A new recipe is a new immutable receipt. A missing cache is regenerated.
    changed = client.post(endpoint, json={"original_sha256": expected_source, "parameters": {}})
    assert changed.status_code == 201
    assert changed.json()["id"] != saved["id"]
    adjusted = list(Path(test_settings.resolved_data_dir).rglob(f"{row['rendition_sha256']}.png"))
    assert len(adjusted) == 1
    adjusted[0].unlink()
    assert client.get(record + "/rendition").content == preview.content
    assert client.get(record).json() == saved
    assert client.get(image + "/content").content == original
    assert client.get(image).json()["annotation_revision"] == 0


def test_adjustment_rejects_invalid_parameters_stale_source_and_unsupported_input(
    client: TestClient, test_settings: Settings
) -> None:
    _, image_id, original = make_source(client)
    image = f"/api/v1/images/{image_id}"
    endpoint = image + "/adjustments"
    source_sha = sha256(original).hexdigest()
    for invalid in ({"red_gain_percent": -1}, {"contrast_percent": 2.5}, {"crop": [0, 1, 2, 3]}):
        response = client.post(
            endpoint, json={"original_sha256": source_sha, "parameters": invalid}
        )
        assert response.status_code == 422
    stale = client.post(endpoint, json={"original_sha256": "0" * 64, "parameters": PARAMETERS})
    assert stale.status_code == 409
    _, gray, gray_bytes = make_source(client, "I;16")
    unsupported = client.post(
        f"/api/v1/images/{gray}/adjustments/preview",
        json={"original_sha256": sha256(gray_bytes).hexdigest(), "parameters": {}},
    )
    assert unsupported.status_code == 400
    assert "single 8-bit RGB" in unsupported.json()["detail"]
    saved = save_recipe(client, image_id, original)
    original_path = test_settings.resolved_data_dir / client.get(image).json()["managed_path"]
    original_path.write_bytes(original + b"changed\n")
    assert client.get(f"{endpoint}/{saved['id']}").status_code == 200
    rejected = client.get(f"{endpoint}/{saved['id']}/rendition")
    assert rejected.status_code == 409
    assert "original" in rejected.json()["detail"].lower()


def test_worker_uses_exact_adjusted_input_with_source_pixel_predictions(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, image_id, original = make_source(client)
    saved = save_recipe(client, image_id, original)
    receipt = saved["receipt"]
    pin = {
        "recipe_id": saved["id"],
        "content_sha256": saved["content_sha256"],
        "original_sha256": receipt["original_sha256"],
        "rendition_sha256": receipt["rendition_sha256"],
    }
    seen_inputs: list[str] = []

    class ImageReadingProvider(FakeDetectorRegistrationProvider):
        def predict(self, image_path: Path, settings: Any) -> list[DetectionPrediction]:
            payload = image_path.read_bytes()
            digest = sha256(payload).hexdigest()
            seen_inputs.append(digest)
            with Image.open(BytesIO(payload)) as image:
                assert image.size == (3, 2)
                if digest == receipt["rendition_sha256"]:
                    assert image.mode == "RGB" and image.tobytes() == ADJUSTED_RGB_BYTES
            return [
                DetectionPrediction(
                    label="soft coral",
                    class_index=0,
                    confidence=0.92,
                    box=PixelBox(x_min=0.5, y_min=0.25, x_max=2.5, y_max=1.75),
                )
            ]

    monkeypatch.setattr(ModelService, "_provider_for_purpose", lambda *_: ImageReadingProvider())
    monkeypatch.setattr(
        "reefvision.jobs.inference.detection_provider_for_name", lambda _: ImageReadingProvider()
    )
    model = register_model(
        client,
        project["id"],
        purpose="detector",
        filename="local.pt",
        display_name="Local detector",
    )
    endpoint = f"/api/v1/projects/{project['id']}/inference-jobs"
    request = {"model_id": model["id"], "image_ids": [image_id], "device": "cpu"}
    stale = client.post(
        endpoint, json={**request, "image_adjustment": {**pin, "rendition_sha256": "0" * 64}}
    )
    assert stale.status_code == 409
    app = cast(FastAPI, client.app)
    ordinary = client.post(endpoint, json=request)
    assert ordinary.status_code == 200
    assert process_inference_job(test_settings, app.state.session_factory, ordinary.json()["id"])
    adjusted = client.post(endpoint, json={**request, "image_adjustment": pin})
    assert adjusted.status_code == 200, adjusted.text
    job_id = adjusted.json()["id"]
    assert process_inference_job(test_settings, app.state.session_factory, job_id)
    assert seen_inputs == [receipt["original_sha256"], receipt["rendition_sha256"]]
    record = client.get(f"/api/v1/jobs/{job_id}").json()
    assert record["request_json"]["checkpoint_sha256"] == model["sha256"]
    assert record["request_json"]["image_adjustment"] == pin
    assert record["result_json"]["model_input"]["rendition_sha256"] == receipt["rendition_sha256"]
    rows = client.get(f"/api/v1/images/{image_id}/prediction-proposals").json()["items"]
    proposed = [row for row in rows if row["inference_job_id"] == job_id]
    assert len(proposed) == 1
    assert [proposed[0][key] for key in ("x_min", "y_min", "x_max", "y_max")] == [
        0.5,
        0.25,
        2.5,
        1.75,
    ]
    assert proposed[0]["review_status"] == "pending"
    assert proposed[0]["provenance_json"]["model_input"]["pixel_axes"] == "raw_source"

    retry = client.post(endpoint, json={**request, "image_adjustment": pin})
    assert retry.status_code == 200
    cache = next(test_settings.resolved_data_dir.rglob(f"{receipt['rendition_sha256']}.png"))
    cache.write_bytes(b"unexpected bytes")
    assert not process_inference_job(test_settings, app.state.session_factory, retry.json()["id"])
    failed = client.get(f"/api/v1/jobs/{retry.json()['id']}").json()
    assert failed["status"] == "failed" and "rendition checksum" in failed["error_message"]
    assert len(seen_inputs) == 2

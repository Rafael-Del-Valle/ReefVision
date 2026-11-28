"""Gallery detector tiling in source-image pixels, from job creation to researcher review."""

from io import BytesIO
from types import SimpleNamespace
from typing import Any, ClassVar, cast
from zipfile import ZipFile

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from reefvision.jobs.export import process_export_job
from reefvision.jobs.inference import process_inference_job
from reefvision.services.models import ModelService
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_dataset_versions import create_version
from reefvision.tests.test_model_inference import FakeDetectorRegistrationProvider, register_model


def test_gallery_tiling_restores_source_boxes_and_merges_overlap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Four overlapping tiles contain the white object. Only the last contains
    # the red object at the bottom-right source boundary.
    size = (3072, 2150)
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    draw.rectangle((1400, 1000, 1419, 1024), fill="white")
    draw.rectangle((3052, 2130, 3071, 2149), fill="red")
    data = BytesIO()
    image.save(data, format="PNG")
    calls = []

    class MarkerDetector:
        names: ClassVar = {0: "soft coral", 1: "second class"}

        def predict(self, crops: list[Image.Image], **options: Any) -> list[Any]:
            calls.append((len(crops), options))
            output = []
            for crop in crops:
                assert crop.size == (1920, 1344)
                rgb = np.asarray(crop)
                boxes, labels = [], []
                for class_index, mask in [
                    (0, rgb[:, :, 1] == 255),
                    (1, rgb[:, :, 1] == 255),
                    (0, (rgb[:, :, 0] == 255) & (rgb[:, :, 1] == 0)),
                ]:
                    rows, cols = np.nonzero(mask)
                    if len(rows):
                        boxes.append([cols.min(), rows.min(), cols.max() + 1, rows.max() + 1])
                        labels.append(class_index)
                output.append(
                    SimpleNamespace(
                        names=self.names,
                        boxes=SimpleNamespace(
                            xyxy=np.array(boxes),
                            conf=np.full(len(boxes), 0.91),
                            cls=np.array(labels),
                        ),
                    )
                )
            return output

    monkeypatch.setattr(
        ModelService, "_provider_for_purpose", lambda *args: FakeDetectorRegistrationProvider()
    )
    monkeypatch.setattr(
        "reefvision.ml.catalog_expansion._ultralytics_detection_model",
        lambda path: MarkerDetector(),
    )
    project = create_project(client)
    base = f"/api/v1/projects/{project['id']}"
    imported = client.post(
        base + "/imports/images", files={"files": ("markers.png", data.getvalue(), "image/png")}
    )
    assert imported.status_code == 200, imported.text
    image_id = imported.json()["successful"][0]["image_id"]
    model = register_model(
        client, project["id"], purpose="detector", filename="markers.pt", display_name="Markers"
    )
    tile = dict(
        width=1920,
        height=1344,
        overlap_x=0.4,
        overlap_y=0.4,
        batch_size=3,
        input_size=640,
        merge_iou=0.45,
    )
    body = {"model_id": model["id"], "image_ids": [image_id], "device": "cpu", "tiling": tile}
    queued = client.post(base + "/inference-jobs", json=body)
    assert queued.status_code == 200, queued.text
    assert queued.json()["request_json"].get("tiling") == tile
    app = cast(FastAPI, client.app)
    job_id = queued.json()["id"]
    assert process_inference_job(app.state.settings, app.state.session_factory, job_id), client.get(
        f"/api/v1/jobs/{job_id}"
    ).text
    assert [length for length, _ in calls] == [3, 1]
    assert all(options["imgsz"] == 640 for _, options in calls)
    proposals = client.get(f"/api/v1/images/{image_id}/prediction-proposals").json()["items"]
    assert sorted(
        (p["predicted_index"], p["x_min"], p["y_min"], p["x_max"], p["y_max"]) for p in proposals
    ) == [(0, 1400, 1000, 1420, 1025), (0, 3052, 2130, 3072, 2150), (1, 1400, 1000, 1420, 1025)]
    assert all(
        p["review_status"] == "pending" and p["inference_settings_json"]["tiling"] == tile
        for p in proposals
    )
    assert client.get(f"/api/v1/images/{image_id}/annotations").json()["annotations"] == []
    edge = next(p for p in proposals if p["x_max"] == size[0])
    accepted = client.post(
        f"/api/v1/prediction-proposals/{edge['id']}/accept",
        json={"label_class_id": project["label_classes"][0]["id"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["annotation"]["x_max"] == size[0]
    reviewed = client.patch(f"/api/v1/images/{image_id}", json={"annotation_status": "reviewed"})
    assert reviewed.status_code == 200, reviewed.text
    version = create_version(client, project["id"], name="Reviewed tile boundary")
    export = client.post(
        f"/api/v1/dataset-versions/{version['id']}/exports", json={"format": "yolo_detection"}
    )
    assert export.status_code == 200, export.text
    assert process_export_job(
        app.state.settings, app.state.session_factory, export.json()["job"]["id"]
    )
    archive = client.get(f"/api/v1/exports/{export.json()['export']['id']}/download")
    assert archive.status_code == 200, archive.text
    with ZipFile(BytesIO(archive.content)) as snapshot:
        labels = [p for p in snapshot.namelist() if "/labels/" in "/" + p and p.endswith(".txt")]
        assert len(labels) == 1
        class_id, *box = snapshot.read(labels[0]).decode().split()
    assert class_id == "0"
    assert list(map(float, box)) == pytest.approx(
        [3062 / size[0], 2140 / size[1], 20 / size[0], 20 / size[1]], abs=0.000001
    )
    for invalid in [{"overlap_y": 1}, {"batch_size": 0}, {"width": -1}]:
        response = client.post(
            base + "/inference-jobs", json={**body, "tiling": {**tile, **invalid}}
        )
        assert response.status_code == 422, response.text

from __future__ import annotations

from io import BytesIO
from typing import cast

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.storage.depth_maps import validate_depth_array
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project


def _image_png(size: tuple[int, int] = (10, 10)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, (90, 120, 150)).save(stream, format="PNG")
    return stream.getvalue()


def _setup_mask(client: TestClient) -> tuple[dict, str, str]:
    project = create_project(client, "Depth measurement study")
    imported = client.post(
        f"/api/v1/projects/{project['id']}/imports/images",
        files=[("files", ("depth-source.png", _image_png(), "image/png"))],
        data={"relative_paths": "depth/depth-source.png"},
    )
    assert imported.status_code == 200, imported.text
    image_id = imported.json()["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_response = client.post(
        f"/api/v1/images/{image_id}/raster-mask-edits",
        json={
            "base_revision": 0,
            "mask_annotation_id": None,
            "label_class_id": class_id,
            "mode": "paint",
            "brush_radius": 2,
            "strokes": [{"points": [{"x": 4, "y": 5}, {"x": 6, "y": 5}]}],
        },
    )
    assert mask_response.status_code == 200, mask_response.text
    return project, image_id, mask_response.json()["mask_annotation"]["id"]


def test_metric_depth_and_intrinsics_produce_pinhole_size_estimates(
    client: TestClient,
) -> None:
    _project, image_id, mask_id = _setup_mask(client)
    values = [[2.0 for _x in range(10)] for _y in range(10)]
    imported = client.put(
        f"/api/v1/images/{image_id}/depth-map-values",
        json={
            "values": values,
            "depth_kind": "metric",
            "unit": "m",
            "provider_id": "imported",
            "model_id": "synthetic-metric-depth",
            "camera_intrinsics": {
                "fx_px": 100,
                "fy_px": 100,
                "cx_px": 5,
                "cy_px": 5,
            },
        },
    )
    assert imported.status_code == 200, imported.text
    depth_map_id = imported.json()["id"]

    preview = client.get(f"/api/v1/depth-maps/{depth_map_id}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")
    assert preview.headers["content-disposition"].startswith("inline")
    assert preview.headers["cache-control"] == "private, no-cache"
    assert preview.headers["etag"]
    missing = client.get("/api/v1/depth-maps/missing-depth-map/preview")
    assert missing.status_code == 404

    app = cast(FastAPI, client.app)
    preview_path = resolve_managed_project_path(app.state.settings, imported.json()["preview_path"])
    preview_path.unlink()
    missing_artifact = client.get(f"/api/v1/depth-maps/{depth_map_id}/preview")
    assert missing_artifact.status_code == 410
    assert "preview artifact is missing" in missing_artifact.json()["detail"]

    measurement = client.get(
        f"/api/v1/mask-annotations/{mask_id}/depth-measurement",
        params={"depth_map_id": depth_map_id},
    )

    assert measurement.status_code == 200, measurement.text
    payload = measurement.json()
    assert payload["depth_kind"] == "metric"
    assert payload["depth"]["median"] == pytest.approx(2.0)
    assert payload["metric_area"] == pytest.approx(
        payload["depth"]["valid_pixel_count"] * 4 / 10_000
    )
    assert payload["metric_width"] > 0
    assert payload["metric_height"] > 0
    assert payload["centroid_z"] == pytest.approx(2.0)


def test_relative_depth_refuses_to_claim_absolute_size(client: TestClient) -> None:
    _project, image_id, mask_id = _setup_mask(client)
    values = [[(x + y) / 18 for x in range(10)] for y in range(10)]
    imported = client.put(
        f"/api/v1/images/{image_id}/depth-map-values",
        json={
            "values": values,
            "depth_kind": "relative",
            "provider_id": "imported",
            "model_id": "synthetic-relative-depth",
        },
    )
    assert imported.status_code == 200, imported.text

    measurement = client.get(
        f"/api/v1/mask-annotations/{mask_id}/depth-measurement",
        params={"depth_map_id": imported.json()["id"]},
    )

    assert measurement.status_code == 200, measurement.text
    payload = measurement.json()
    assert payload["metric_area"] is None
    assert payload["metric_width"] is None
    assert payload["depth_weighted_area_index"] is not None
    assert any("cannot produce absolute" in warning for warning in payload["warnings"])


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
def test_depth_storage_rejects_nonfinite_model_output(invalid: float) -> None:
    values = np.ones((3, 4), dtype=np.float32)
    values[1, 2] = invalid

    with pytest.raises(ValueError, match="NaN or infinite"):
        validate_depth_array(
            values,
            expected_width=4,
            expected_height=3,
            depth_kind="relative",
        )

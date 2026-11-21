from hashlib import sha256
from io import BytesIO
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.tests.test_images import create_project, import_one


def spectral_fixture(
    client: TestClient, project: str | None = None
) -> tuple[str, dict[str, Any], list[bytes]]:
    project = project or create_project(client)["id"]
    root = f"/api/v1/projects/{project}/multispectral"
    bands = []
    files = []
    for name, nm, values, dx in (
        ("red", 660, [[20, 20, 20, 0], [20, 0, 20, 20]], 0),
        ("nir", 850, [[60, 255, 0, 20], [0, 60, 60, 40]], 1),
    ):
        stream = BytesIO()
        Image.fromarray(np.array(values, dtype=np.uint16)).save(stream, format="TIFF")
        original = stream.getvalue()
        files.append(original)
        image = import_one(client, project, content=original, filename=name + ".tif")["successful"][
            0
        ]
        bands.append(
            {
                "name": name,
                "wavelength_nm": nm,
                "image_id": image["image_id"],
                "original_sha256": sha256(original).hexdigest(),
                "offset_x": dx,
                "nodata": 255,
                "calibration": {
                    "dark_dn": 0,
                    "white_dn": 100,
                    "white_reflectance": 1,
                    "reference": "generated panel, known response",
                },
            }
        )
    body = {
        "label": "Generated red and NIR",
        "sensor": "fixture sensor",
        "alignment": {
            "grid": "reference band pixels",
            "reviewer": "fixture reviewer",
            "evidence": "known one pixel translation",
            "maximum_residual_px": 0,
        },
        "bands": bands,
    }
    return root, body, files


def test_registered_shift_composite_and_calibrated_index(client: TestClient) -> None:
    root, body, files = spectral_fixture(client)
    created = client.post(root + "/acquisitions", json=body)
    assert created.status_code == 201, created.text
    original = created.json()
    assert client.post(root + "/acquisitions", json=body).json()["id"] == original["id"]
    endpoint = root + "/acquisitions/" + original["id"]
    assert client.get(endpoint).json() == original
    for band, content in zip(body["bands"], files, strict=True):
        assert client.get(f"/api/v1/images/{band['image_id']}/content").content == content
    rendered = client.get(endpoint + "/composite", params={"red": 1, "green": 0, "blue": 0})
    assert rendered.status_code == 200, rendered.text if not rendered.is_success else ""
    with Image.open(BytesIO(rendered.content)) as composite:
        assert composite.mode == "RGBA" and composite.size == (4, 2)
        assert composite.getpixel((0, 0))[3] == 0
        assert composite.getpixel((1, 0)) == (153, 51, 51, 255)
        assert composite.getpixel((2, 0))[3] == 0
    selection = {"acquisition_sha256": original["content_sha256"], "positive": 1, "negative": 0}
    result = client.post(endpoint + "/indices", json=selection)
    assert result.status_code == 201, result.text
    record = result.json()
    stats = record["snapshot"]["result"]
    assert stats["status"] == "available"
    assert stats["valid_pixels"] == 3 and stats["reference_pixels"] == 8
    assert stats["mean"] == stats["minimum"] == stats["maximum"] == 0.5
    assert stats["excluded"] == {"outside_grid": 2, "invalid_band_sample": 1, "zero_denominator": 2}
    assert client.post(endpoint + "/indices", json=selection).json()["id"] == record["id"]
    report = root + "/indices/" + record["id"]
    assert client.get(report + "/export").json() == record
    raster = client.get(report + "/raster")
    assert raster.status_code == 200, raster.text if not raster.is_success else ""
    with Image.open(BytesIO(raster.content)) as pixels:
        values = np.asarray(pixels)
        assert values.shape == (2, 4)
        assert np.isfinite(values).sum() == 3 and values[1, 3] == 0.5
        assert np.isnan(values[0, 0]) and np.isnan(values[0, 3])
    assert (
        client.post(
            endpoint + "/indices", json={**selection, "acquisition_sha256": "c" * 64}
        ).status_code
        == 409
    )


def test_unreviewed_grid_or_missing_calibration_withholds_quantitation(client: TestClient) -> None:
    root, body, _ = spectral_fixture(client)
    body["alignment"] = None
    body["bands"][1]["calibration"] = None
    acquisition = client.post(root + "/acquisitions", json=body)
    assert acquisition.status_code == 201, acquisition.text
    saved = acquisition.json()
    endpoint = root + "/acquisitions/" + saved["id"]
    unavailable = client.get(endpoint + "/composite")
    assert unavailable.status_code == 400 and "reviewed common pixel grid" in unavailable.text
    record = client.post(
        endpoint + "/indices",
        json={"acquisition_sha256": saved["content_sha256"], "positive": 1, "negative": 0},
    )
    assert record.status_code == 201, record.text
    result = record.json()["snapshot"]["result"]
    assert result["status"] == "withheld" and result["mean"] is None
    assert len(result["reasons"]) == 2 and result["valid_pixels"] == 0
    unavailable = client.get(root + "/indices/" + record.json()["id"] + "/raster")
    assert unavailable.status_code == 400 and "withheld" in unavailable.text
    duplicate = {**body, "bands": [body["bands"][0], body["bands"][0]]}
    assert client.post(root + "/acquisitions", json=duplicate).status_code == 422

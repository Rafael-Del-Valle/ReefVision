"""GLB preview API and schema parity regression."""

import pytest
from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_glb_v14 import make_glb


def test_glb_preview_api(client: TestClient) -> None:
    project_id = create_project(client, "GLB preview")["id"]
    payload = {
        "glb_base64": make_glb(),
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Pending verification",
    }
    url = f"/api/v1/projects/{project_id}/spatial/mesh-preview"
    response = client.post(url, json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["surface_area_m2"] == pytest.approx(0.0003)
    assert result["provenance"]["source_format"] == "glb_2_0"
    assert result["provenance"]["calibration_verified"] is False
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert client.post(url, json={**payload, "obj_text": "v 0 0 0"}).status_code == 422

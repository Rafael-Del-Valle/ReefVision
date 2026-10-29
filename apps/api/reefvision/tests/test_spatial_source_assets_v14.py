"""Project-scoped immutable source import and retrieval acceptance."""

from __future__ import annotations

from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project

OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


@pytest.mark.parametrize(
    "filename,payload,kind",
    [
        ("coral.obj", OBJ, "mesh"),
        ("survey.ply", b"ply\nformat ascii 1.0\nend_header\n", "mesh_or_point_cloud"),
        ("model.glb", b"glTF" + bytes(16), "mesh"),
    ],
)
def test_import_deduplicates_and_isolates_original_bytes(
    client: TestClient, filename: str, payload: bytes, kind: str
) -> None:
    project = str(create_project(client, "Spatial source")["id"])
    other = str(create_project(client, "Other spatial source")["id"])
    url = f"/api/v1/projects/{project}/spatial/assets"
    response = client.post(url, files={"file": (filename, payload)})
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["sha256"] == sha256(payload).hexdigest()
    assert asset["size_bytes"] == len(payload)
    assert asset["source_kind"] == kind
    assert asset["measurement_status"] == "source_unreviewed"
    assert asset["calibration_verified"] is False
    assert asset["specimen_identity_verified"] is False
    assert "managed_path" not in asset
    duplicate = client.post(url, files={"file": (filename, payload)})
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == asset["id"]
    assert len(client.get(url).json()) == 1
    assert client.get(f"{url}/{asset['id']}/content").content == payload
    assert client.get(f"/api/v1/projects/{other}/spatial/assets").json() == []
    assert client.get(f"/api/v1/projects/{other}/spatial/assets/{asset['id']}").status_code == 404
    assert (
        client.get(f"/api/v1/projects/{other}/spatial/assets/{asset['id']}/content").status_code
        == 404
    )


@pytest.mark.parametrize(
    "filename,payload",
    [
        ("../escape.obj", OBJ),
        ("folder\\escape.ply", OBJ),
        ("coral.exe", OBJ),
        ("empty.obj", b""),
        ("too-large.obj", b"x" * (8 * 1024 * 1024 + 1)),
    ],
)
def test_invalid_source_is_rejected(client: TestClient, filename: str, payload: bytes) -> None:
    project = str(create_project(client, "Reject spatial source")["id"])
    url = f"/api/v1/projects/{project}/spatial/assets"
    response = client.post(url, files={"file": (filename, payload)})
    assert response.status_code == 400, response.text
    assert client.get(url).json() == []

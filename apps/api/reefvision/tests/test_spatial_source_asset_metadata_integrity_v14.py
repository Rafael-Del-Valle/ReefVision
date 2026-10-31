"""Imported 3D source metadata must remain format/kind consistent on replay.

Byte integrity alone cannot authorize corrupted scientific source metadata.
"""

from __future__ import annotations

import base64
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import SpatialSourceAsset
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_glb_v14 import make_glb
from reefvision.tests.test_spatial_point_cloud_assets_v14 import PLY as CLOUD_PLY

OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


@pytest.mark.parametrize(
    ("filename", "original", "endpoint", "node_type", "artifact_type", "wrong_kind"),
    [
        (
            "coral.obj",
            OBJ,
            "mesh-preview",
            "mesh_surface_preview",
            "mesh_measurement_preview",
            "mesh_or_point_cloud",
        ),
        (
            "survey.ply",
            CLOUD_PLY,
            "point-cloud-preview",
            "point_cloud_preview",
            "point_cloud_measurement_preview",
            "mesh",
        ),
        (
            "coral.glb",
            base64.b64decode(make_glb()),
            "mesh-preview",
            "mesh_surface_preview",
            "mesh_measurement_preview",
            "mesh_or_point_cloud",
        ),
    ],
    ids=["obj", "ply-point-cloud", "glb"],
)
@pytest.mark.parametrize(
    "corrupt_field",
    [
        "source_kind",
        "source_format",
        "original_filename_extension",
        "original_filename_path",
        "original_filename_empty",
    ],
)
def test_corrupt_imported_source_metadata_fails_standalone_and_saved_workflow(
    client: TestClient,
    filename: str,
    original: bytes,
    endpoint: str,
    node_type: str,
    artifact_type: str,
    wrong_kind: str,
    corrupt_field: str,
) -> None:
    project_id = str(create_project(client, "Spatial metadata replay integrity")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(f"{base}/spatial/assets", files={"file": (filename, original)})
    assert imported.status_code == 201, imported.text
    asset = imported.json()
    params = {
        "asset_id": asset["id"],
        "expected_source_payload_sha256": asset["sha256"],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified survey ruler",
        "relative_scale_uncertainty": 0.05,
    }
    baseline = client.post(f"{base}/spatial/{endpoint}", json=params)
    assert baseline.status_code == 200, baseline.text
    graph = {
        "graph_id": f"source-metadata-{node_type}-{corrupt_field}",
        "name": "Reject corrupted imported source metadata",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "measure", "node_type": node_type, "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-measure",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "measure",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        record = session.get(SpatialSourceAsset, asset["id"])
        assert record is not None
        if corrupt_field == "source_kind":
            record.source_kind = wrong_kind
        elif corrupt_field == "source_format":
            record.source_format = "unknown"
        elif corrupt_field == "original_filename_extension":
            record.original_filename = "relabelled.txt"
        elif corrupt_field == "original_filename_path":
            record.original_filename = f"../{filename}"
        else:
            record.original_filename = ""
        session.commit()

    # The file itself has not changed; the recorded source classification has.
    content = client.get(f"{base}/spatial/assets/{asset['id']}/content")
    assert content.status_code == 400, content.text
    if corrupt_field in {"source_kind", "source_format"}:
        assert "format and kind" in content.text.lower()
    else:
        assert "original filename" in content.text.lower()
    standalone = client.post(f"{base}/spatial/{endpoint}", json=params)
    assert standalone.status_code == 400, standalone.text

    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(item["data_type"] == artifact_type for item in detail.json()["artifacts"])

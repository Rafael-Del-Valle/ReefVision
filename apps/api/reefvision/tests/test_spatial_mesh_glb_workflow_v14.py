"""GLB saved graph execution smoke test."""

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_glb_v14 import make_glb


@pytest.mark.parametrize(
    (
        "nonindexed,explicit_targets,unsigned_byte_indices,position_offset,"
        "position_bounds,position_stride,index_bounds"
    ),
    [
        (False, False, False, 0, False, None, False),
        (False, True, False, 0, False, None, False),
        (True, False, False, 0, False, None, False),
        (False, False, True, 0, False, None, False),
        (False, True, True, 0, False, None, False),
        (False, False, False, 4, False, None, False),
        (False, False, False, 0, True, None, False),
        (False, False, False, 0, True, 16, False),
        (False, False, False, 0, False, 20, False),
        (False, False, False, 0, False, None, True),
    ],
)
def test_saved_glb(
    client: TestClient,
    nonindexed: bool,
    explicit_targets: bool,
    unsigned_byte_indices: bool,
    position_offset: int,
    position_bounds: bool,
    position_stride: int | None,
    index_bounds: bool,
) -> None:
    pid = create_project(client, "GLB saved")["id"]
    params = {
        "glb_base64": make_glb(
            nonindexed_vertices=3 if nonindexed else None,
            explicit_targets=explicit_targets,
            unsigned_byte_indices=unsigned_byte_indices,
            position_offset=position_offset,
            position_bounds=position_bounds,
            position_stride=position_stride,
            index_bounds=index_bounds,
        ),
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Pending review",
    }
    graph = {
        "graph_id": "glb-v14",
        "name": "GLB",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "e",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "m",
                "target_port_id": "project",
            }
        ],
    }
    base = f"/api/v1/projects/{pid}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = detail.json()["artifacts"]
    measurement = next(
        artifact["payload_json"]
        for artifact in artifacts
        if artifact["data_type"] == "mesh_measurement_preview"
    )
    assert measurement["provenance"]["source_format"] == "glb_2_0"
    assert measurement["surface_area_m2"] == standalone.json()["surface_area_m2"]
    assert (
        measurement["provenance"]["geometry_sha256"]
        == standalone.json()["provenance"]["geometry_sha256"]
    )


@pytest.mark.parametrize(
    "invalid_selector",
    [
        "mode_float",
        "json_nan",
        "nonzero_bin_padding",
        "nonindexed_partial",
        "position_target_index",
        "index_target_vertex",
        "target_float",
        "target_boolean",
        "byte_index_oob",
        "misaligned_position_view",
        "index_stride",
        "bounds_short",
        "bounds_boolean",
        "bounds_nan",
        "bounds_mismatch",
        "stride_too_small",
        "stride_unaligned",
        "stride_oversize",
        "stride_boolean",
        "stride_truncated",
        "stride_overlap",
        "index_bounds_short",
        "index_bounds_boolean",
        "index_bounds_mismatch",
        "index_bounds_negative",
        "index_bounds_nan",
        "index_bounds_huge",
        "index_bounds_float",
        "asset_min_version_future",
        "asset_min_version_numeric",
        "asset_min_version_boolean",
    ],
)
def test_invalid_glb_metadata_fails_standalone_and_saved_graph(
    client: TestClient, invalid_selector: str
) -> None:
    """Reject malformed glTF metadata before publishing any scientific artifact."""
    pid = create_project(client, f"GLB metadata rejection {invalid_selector}")["id"]
    params = {
        "glb_base64": make_glb(
            invalid_selector=invalid_selector,
            nonindexed_vertices=4 if invalid_selector == "nonindexed_partial" else None,
            unsigned_byte_indices=invalid_selector == "byte_index_oob",
        ),
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Pending verification",
    }
    base = f"/api/v1/projects/{pid}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 400, standalone.text
    graph = {
        "graph_id": f"glb-invalid-{invalid_selector}-v14",
        "name": "Reject noninteger glTF mode",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "e",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "m",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == "mesh_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )

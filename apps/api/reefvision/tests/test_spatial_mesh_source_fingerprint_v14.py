"""Imported mesh source bytes remain distinguishable from parsed geometry identity."""

from __future__ import annotations

import base64
import hashlib
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_cross_format_v14 import COMMON, OBJ, PLY
from reefvision.tests.test_spatial_mesh_glb_v14 import make_glb


@pytest.mark.parametrize(
    ("source_key", "source_value"),
    [
        ("obj_text", OBJ),
        ("ply_text", PLY),
        ("glb_base64", make_glb()),
    ],
    ids=["obj", "ply", "glb"],
)
def test_source_byte_fingerprint_survives_standalone_and_saved_workflow(
    client: TestClient, source_key: str, source_value: str
) -> None:
    project_id = str(create_project(client, "Source content provenance")["id"])
    base = f"/api/v1/projects/{project_id}"
    params: dict[str, Any] = {**COMMON, source_key: source_value}
    expected_bytes = (
        base64.b64decode(source_value, validate=True)
        if source_key == "glb_base64"
        else source_value.encode("utf-8")
    )
    expected_sha = hashlib.sha256(expected_bytes).hexdigest()

    direct = preview_from_request(MeshPreviewRequest.model_validate(params))
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    assert direct["provenance"]["source_payload_sha256"] == expected_sha
    assert direct["provenance"]["source_payload_size_bytes"] == len(expected_bytes)
    assert standalone.json()["provenance"] == direct["provenance"]
    assert direct["provenance"]["calibration_verified"] is False
    assert direct["measurement_status"] == "caller_supplied_unverified"

    graph = {
        "graph_id": f"mesh-source-fingerprint-{source_key}",
        "name": "Auditable imported mesh source identity",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["provenance"] == direct["provenance"]
    assert artifact["surface_area_m2"] == direct["surface_area_m2"]
    assert artifact["project_id"] == project_id
    assert artifact["measurement_status"] == "caller_supplied_unverified"


def test_source_bytes_and_parsed_geometry_have_separate_fingerprints() -> None:
    obj = preview_from_request(MeshPreviewRequest(**COMMON, obj_text=OBJ))
    ply = preview_from_request(MeshPreviewRequest(**COMMON, ply_text=PLY))
    obj_whitespace = preview_from_request(
        MeshPreviewRequest(**COMMON, obj_text=OBJ.replace("v 2 0 0\n", "v 2 0 0  \n"))
    )
    obj_provenance = obj["provenance"]
    ply_provenance = ply["provenance"]
    whitespace_provenance = obj_whitespace["provenance"]
    assert obj_provenance["geometry_sha256"] == ply_provenance["geometry_sha256"]
    assert obj_provenance["geometry_sha256"] == whitespace_provenance["geometry_sha256"]
    assert obj_provenance["source_payload_sha256"] != ply_provenance["source_payload_sha256"]
    whitespace_sha = whitespace_provenance["source_payload_sha256"]
    assert obj_provenance["source_payload_sha256"] != whitespace_sha


def test_indexed_triangles_do_not_claim_an_imported_source_file() -> None:
    result = preview_from_request(
        MeshPreviewRequest(
            **COMMON,
            vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            faces=[[0, 1, 2]],
        )
    )
    assert result["provenance"]["source_format"] == "indexed_triangles"
    assert result["provenance"]["source_payload_sha256"] is None
    assert result["provenance"]["source_payload_size_bytes"] is None
    assert len(result["provenance"]["geometry_sha256"]) == 64


@pytest.mark.parametrize(
    ("source_key", "source_value"),
    [
        ("obj_text", OBJ),
        ("ply_text", PLY),
        ("glb_base64", make_glb()),
    ],
    ids=["obj", "ply", "glb"],
)
def test_unchecked_zero_byte_import_provenance_fails_but_missing_legacy_count_survives(
    source_key: str, source_value: str
) -> None:
    """A claimed imported original cannot be empty, even without a hash check."""
    common = {**COMMON, source_key: source_value, "specimen_id": "colony:16"}
    before = preview_from_request(
        MeshPreviewRequest.model_validate(
            {
                **common,
                "observation_id": "survey-1",
                "observed_at_utc": "2026-10-01T12:00:00Z",
            }
        )
    )
    after = preview_from_request(
        MeshPreviewRequest.model_validate(
            {
                **common,
                "observation_id": "survey-2",
                "observed_at_utc": "2026-10-02T12:00:00Z",
            }
        )
    )
    for observation in (before, after):
        observation["project_id"] = "local-project"
    assert before["provenance"]["source_payload_integrity_checked"] is False
    baseline = compare_mesh_observations(before, after)
    assert baseline["provenance"]["longitudinal_change_withheld_due_to_reused_source_payload"]

    before["provenance"]["source_payload_size_bytes"] = 0
    with pytest.raises(ValueError, match="Imported mesh source byte count must be positive"):
        compare_mesh_observations(before, after)

    # Older preview artifacts can omit the count entirely. Missing is not
    # equivalent to an impossible explicitly claimed zero-byte original.
    before["provenance"].pop("source_payload_size_bytes")
    legacy = compare_mesh_observations(before, after)
    assert legacy["provenance"]["longitudinal_change_withheld_due_to_reused_source_payload"]


@pytest.mark.parametrize(
    ("source_key", "source_value"),
    [("obj_text", OBJ), ("ply_text", PLY), ("glb_base64", make_glb())],
    ids=["obj", "ply", "glb"],
)
def test_imported_source_digest_check_qc_matches_saved_comparison(
    client: TestClient, source_key: str, source_value: str
) -> None:
    """A computed digest is not proof that the expected original was checked."""
    source_bytes = (
        base64.b64decode(source_value, validate=True)
        if source_key == "glb_base64"
        else source_value.encode("utf-8")
    )
    digest = hashlib.sha256(source_bytes).hexdigest()
    project_id = str(create_project(client, "Source integrity review replay")["id"])
    base = f"/api/v1/projects/{project_id}"
    shared = {**COMMON, source_key: source_value, "specimen_id": "colony:16"}
    before = {
        **shared,
        "observation_id": "survey-1",
        "observed_at_utc": "2026-10-01T12:00:00Z",
        "expected_source_payload_sha256": digest,
    }
    after = {
        **shared,
        "observation_id": "survey-2",
        "observed_at_utc": "2026-10-02T12:00:00Z",
    }
    response = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 200, response.text
    expected = response.json()
    warnings = expected["qc_warnings"]
    assert "before_imported_source_expected_digest_not_checked" not in warnings
    assert "after_imported_source_expected_digest_not_checked" in warnings
    assert "identical_imported_source_payload_reused_across_observations" in warnings
    assert expected["delta_surface_area_m2"] is None
    assert expected["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": "mesh-integrity-check-qc-v14",
        "name": "Per-timepoint imported original integrity QC",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "early", "node_type": "mesh_surface_preview", "parameters": before},
            {"node_id": "late", "node_type": "mesh_surface_preview", "parameters": after},
            {"node_id": "compare", "node_type": "mesh_longitudinal_comparison"},
        ],
        "edges": [
            {
                "edge_id": f"project-{node}",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": node,
                "target_port_id": "project",
            }
            for node in ("early", "late")
        ]
        + [
            {
                "edge_id": f"{node}-compare",
                "source_node_id": node,
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": port,
            }
            for node, port in (("early", "before"), ("late", "after"))
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact == expected


def test_rescaled_cross_format_reexport_withholds_false_growth_in_saved_workflow(
    client: TestClient,
) -> None:
    """Different source bytes cannot make rescaled identical triangles biological growth."""
    project_id = str(create_project(client, "Rescaled reexport QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    before = {
        **COMMON,
        "obj_text": OBJ,
        "specimen_id": "colony:16",
        "observation_id": "survey-1",
        "observed_at_utc": "2026-10-01T12:00:00Z",
    }
    after = {
        **COMMON,
        "ply_text": PLY,
        "meters_per_unit": COMMON["meters_per_unit"] * 2,
        "specimen_id": "colony:16",
        "observation_id": "survey-2",
        "observed_at_utc": "2026-10-02T12:00:00Z",
    }
    response = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["after_surface_area_m2"] == pytest.approx(
        4 * expected["before_surface_area_m2"]
    )
    assert "identical_geometry_different_imported_source_payload" in expected["qc_warnings"]
    assert "longitudinal_change_withheld_rescaled_reexported_geometry" in expected["qc_warnings"]
    assert (
        "identical_imported_source_payload_reused_across_observations"
        not in expected["qc_warnings"]
    )
    assert (
        expected["provenance"]["longitudinal_change_withheld_due_to_rescaled_reexported_geometry"]
        is True
    )
    for field in (
        "delta_surface_area_m2",
        "relative_surface_area_change_percent",
        "average_surface_area_change_m2_per_day",
        "delta_surface_area_scale_interval_m2",
        "delta_axis_aligned_bounding_box_diagonal_m",
    ):
        assert expected[field] is None
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["specimen_identity_verified"] is False

    # A same-scale re-export is still marked as repeated geometry but does not
    # trigger the narrowly scoped recalibration withholding rule.
    same_scale = {**after, "meters_per_unit": COMMON["meters_per_unit"]}
    control = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": same_scale},
    )
    assert control.status_code == 200, control.text
    assert control.json()["delta_surface_area_m2"] == pytest.approx(0)
    assert (
        control.json()["provenance"][
            "longitudinal_change_withheld_due_to_rescaled_reexported_geometry"
        ]
        is False
    )

    graph = {
        "graph_id": "rescaled-cross-format-reexport-v14",
        "name": "Rescaled imported geometry is not growth",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "early", "node_type": "mesh_surface_preview", "parameters": before},
            {"node_id": "late", "node_type": "mesh_surface_preview", "parameters": after},
            {"node_id": "compare", "node_type": "mesh_longitudinal_comparison"},
        ],
        "edges": [
            {
                "edge_id": f"project-{node}",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": node,
                "target_port_id": "project",
            }
            for node in ("early", "late")
        ]
        + [
            {
                "edge_id": f"{node}-compare",
                "source_node_id": node,
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": port,
            }
            for node, port in (("early", "before"), ("late", "after"))
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact == expected

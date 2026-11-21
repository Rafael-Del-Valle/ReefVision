"""Signed-coordinate mesh centroid regression across API and persisted workflows."""

from __future__ import annotations

from math import fsum
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project


def test_signed_vertex_cancellation_preserves_centroid_in_saved_workflow(
    client: TestClient,
) -> None:
    """A source-coordinate value below another vertex's ULP must survive."""
    # Ordinary left-to-right sum(1e9, 1e-8, -1e9) loses the 1e-8
    # contribution. Its exact floating-point input is still representable
    # and changes the reconstructed triangle's surface centroid.
    params = {
        "vertices": [[1e9, 0.0, 0.0], [1e-8, 1.0, 0.0], [-1e9, 0.0, 1.0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic coordinates; scale not independently verified",
        "relative_scale_uncertainty": 0.05,
    }
    expected_x_m = fsum([1e9, 1e-8, -1e9]) / 3 * 0.01
    assert expected_x_m > 0
    direct = measure_mesh_preview(**params)
    assert direct["area_weighted_surface_centroid_m"][0] == pytest.approx(
        expected_x_m, rel=1e-12, abs=1e-17
    )
    assert direct["edge_connected_patch_area_weighted_surface_centroids_m"] == [
        direct["area_weighted_surface_centroid_m"]
    ]
    assert direct["measurement_status"] == "caller_supplied_unverified"
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Signed centroid vertex cancellation")["id"])
    base = f"/api/v1/projects/{project_id}"
    # Source labels are caller-supplied metadata, not verified biological identity.
    api_params = {
        **params,
        "specimen_id": "synthetic-coral-1",
        "observation_id": "scan-A",
        "observed_at_utc": "2026-11-17T17:00:00Z",
        "coordinate_frame_id": "camera-frame-A",
    }
    response = client.post(f"{base}/spatial/mesh-preview", json=api_params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    for field in (
        "area_weighted_surface_centroid_m",
        "edge_connected_patch_area_weighted_surface_centroids_m",
        "area_weighted_centroid_scale_uncertainty_m",
        "edge_connected_patch_centroid_scale_uncertainties_m",
        "surface_area_m2",
        "qc_warnings",
    ):
        assert standalone[field] == direct[field]
    provenance = standalone["provenance"]
    assert provenance["calibration_verified"] is False
    assert provenance["specimen_id"] == api_params["specimen_id"]
    assert provenance["observation_id"] == api_params["observation_id"]
    assert provenance["observed_at_utc"] == api_params["observed_at_utc"]
    assert provenance["coordinate_frame_id"] == api_params["coordinate_frame_id"]
    assert provenance["specimen_identity_verified"] is False
    assert provenance["observation_metadata_verified"] is False
    assert provenance["coordinate_registration_verified"] is False

    graph = {
        "graph_id": "signed-mesh-centroid-v14",
        "name": "Signed mesh surface centroid",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": api_params},
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    artifact_hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifact = next(
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        )
        for field in (
            "area_weighted_surface_centroid_m",
            "edge_connected_patch_area_weighted_surface_centroids_m",
            "area_weighted_centroid_scale_uncertainty_m",
            "edge_connected_patch_centroid_scale_uncertainties_m",
            "surface_area_m2",
            "qc_warnings",
            "provenance",
        ):
            assert artifact["payload_json"][field] == standalone[field]
        artifact_hashes.append(artifact["payload_sha256"])
    assert len(set(artifact_hashes)) == 1


def test_signed_mesh_centroid_winding_does_not_prove_source_identity() -> None:
    """Face winding cannot alter geometry, but it changes its source fingerprint."""
    vertices = [[1e9, 0.0, 0.0], [1e-8, 1.0, 0.0], [-1e9, 0.0, 1.0]]
    options = {
        "vertices": vertices,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic reconstruction without external scale review",
    }
    original = measure_mesh_preview(faces=[[0, 1, 2]], **options)
    reversed_winding = measure_mesh_preview(faces=[[0, 2, 1]], **options)
    assert original["area_weighted_surface_centroid_m"] == pytest.approx(
        reversed_winding["area_weighted_surface_centroid_m"]
    )
    assert original["surface_area_m2"] == pytest.approx(reversed_winding["surface_area_m2"])
    assert (
        original["edge_connected_patch_geometry_sha256"]
        == (reversed_winding["edge_connected_patch_geometry_sha256"])
    )
    # Source-order integrity and geometry-equivalence are distinct contracts;
    # neither certifies specimen identity, registration, or human review.
    assert (
        original["provenance"]["geometry_sha256"]
        != (reversed_winding["provenance"]["geometry_sha256"])
    )
    assert original["provenance"]["calibration_verified"] is False
    assert reversed_winding["provenance"]["calibration_verified"] is False


def test_face_winding_source_hash_contract_survives_saved_workflows(
    client: TestClient,
) -> None:
    """Equivalent surfaces need not share source-file hashes or verified biological identities."""
    project_id = str(create_project(client, "Winding-provenance control")["id"])
    base = f"/api/v1/projects/{project_id}"
    app = cast(FastAPI, client.app)
    direct_by_winding: dict[str, dict] = {}
    standalone_by_winding: dict[str, dict] = {}
    hashes_by_winding: dict[str, list[str]] = {}
    for winding, face in (("original", [0, 1, 2]), ("reversed", [0, 2, 1])):
        source = {
            "vertices": [[1e9, 0.0, 0.0], [1e-8, 1.0, 0.0], [-1e9, 0.0, 1.0]],
            "faces": [face],
            "meters_per_unit": 0.01,
            "calibration_method": "ruler",
            "calibration_evidence": "Synthetic; independent verification absent",
            "relative_scale_uncertainty": 0.05,
        }
        direct = measure_mesh_preview(**source)
        direct_by_winding[winding] = direct
        payload = {
            **source,
            "specimen_id": "synthetic-coral-1",
            "observation_id": "scan-A",
            "coordinate_frame_id": "unregistered-camera-frame",
        }
        response = client.post(f"{base}/spatial/mesh-preview", json=payload)
        assert response.status_code == 200, response.text
        standalone = response.json()
        standalone_by_winding[winding] = standalone
        for field in (
            "area_weighted_surface_centroid_m",
            "surface_area_m2",
            "edge_connected_patch_geometry_sha256",
            "qc_warnings",
        ):
            assert standalone[field] == direct[field]
        provenance = standalone["provenance"]
        assert provenance["specimen_id"] == "synthetic-coral-1"
        assert provenance["specimen_identity_verified"] is False
        assert provenance["coordinate_registration_verified"] is False
        assert provenance["calibration_verified"] is False

        graph = {
            "graph_id": f"winding-source-hash-{winding}-v14",
            "name": f"Winding provenance {winding}",
            "nodes": [
                {"node_id": "p", "node_type": "project_source"},
                {"node_id": "m", "node_type": "mesh_surface_preview", "parameters": payload},
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
        plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
        assert plan.status_code == 200, plan.text
        assert plan.json()["executable"] is True
        saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
        assert saved.status_code == 201, saved.text
        hashes: list[str] = []
        for _ in range(2):
            run = client.post(
                f"{base}/workflow-runs",
                json={"graph_record_id": saved.json()["id"]},
            )
            assert run.status_code == 202, run.text
            assert process_workflow_run_job(
                app.state.settings, app.state.session_factory, str(run.json()["job_id"])
            )
            detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["run"]["status"] == "succeeded"
            artifact = next(
                item
                for item in detail.json()["artifacts"]
                if item["data_type"] == "mesh_measurement_preview"
            )
            for field in (
                "area_weighted_surface_centroid_m",
                "surface_area_m2",
                "edge_connected_patch_geometry_sha256",
                "qc_warnings",
                "provenance",
            ):
                assert artifact["payload_json"][field] == standalone[field]
            hashes.append(artifact["payload_sha256"])
        assert hashes[0] == hashes[1]
        hashes_by_winding[winding] = hashes

    original = standalone_by_winding["original"]
    reversed_winding = standalone_by_winding["reversed"]
    patch_hash = "edge_connected_patch_geometry_sha256"
    source_hash = "geometry_sha256"
    centroid = "area_weighted_surface_centroid_m"
    assert original[patch_hash] == reversed_winding[patch_hash]
    assert original["surface_area_m2"] == reversed_winding["surface_area_m2"]
    assert original[centroid] == reversed_winding[centroid]
    assert original["provenance"][source_hash] != reversed_winding["provenance"][source_hash]
    assert hashes_by_winding["original"][0] != hashes_by_winding["reversed"][0]
    assert direct_by_winding["original"]["measurement_status"] == "caller_supplied_unverified"
    assert direct_by_winding["reversed"]["measurement_status"] == "caller_supplied_unverified"

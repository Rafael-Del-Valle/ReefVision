"""Provisional mesh timepoint comparison: API, QC and persisted typed graph parity."""

from __future__ import annotations

from math import sqrt
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import (
    MeshRegistrationEvidence,
    MeshReidentificationEvidence,
)
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.workflow_mesh_v14 import execute_mesh_longitudinal_comparison
from reefvision.tests.test_annotations import create_project


def _mesh(observation: str, date: str, height: float) -> dict:
    return {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, height, 0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 1,
        "calibration_method": "ruler",
        "calibration_evidence": "Field ruler not yet reviewed",
        "relative_scale_uncertainty": 0.1,
        "specimen_id": "colony:16",
        "observation_id": observation,
        "observed_at_utc": date,
    }


def _rigid_transform() -> list[list[float]]:
    """A provisional 10 cm translation, with no implied verified alignment."""
    return [
        [1.0, 0.0, 0.0, 0.1],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def test_mesh_comparison_standalone_and_persisted_workflow(client: TestClient) -> None:
    project_id = str(create_project(client, "Mesh timepoints")["id"])
    base = f"/api/v1/projects/{project_id}"
    before = _mesh("survey-1", "2026-10-01T12:00:00Z", 1)
    after = _mesh("survey-2", "2026-10-02T07:00:00-05:00", 2)
    before["coordinate_frame_id"] = "survey-local"
    after["coordinate_frame_id"] = "survey-local"
    registration_evidence = {
        "source_frame_id": "survey-local",
        "target_frame_id": "survey-local",
        "method": "landmark",
        "rms_residual_m": 0.02,
        "correspondence_count": 6,
        "evidence_note": "Provisional landmark alignment; independent review pending",
        "source_to_target_transform_m": _rigid_transform(),
    }
    reidentification_evidence = {
        "project_id": project_id,
        "specimen_id": "colony:16",
        "before_observation_id": "survey-1",
        "after_observation_id": "survey-2",
        "method": "photo_match",
        "observer_id": "lab-annotator-1",
        "evidence_note": "Provisional photo match; independent review pending",
        "independent_reviewer_id": "lab-reviewer-2",
        "independent_review_decision": "supports_match",
        "independent_review_note": "Separate visual check; no certified identity determination",
        "independent_reviewed_at_utc": "2026-10-03T12:00:00Z",
        "before_observed_at_utc": "2026-10-01T12:00:00Z",
        "after_observed_at_utc": "2026-10-02T07:00:00-05:00",
    }
    # Bind matching notes to the actual imported geometry, not only labels.
    preliminary = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert preliminary.status_code == 200, preliminary.text
    reidentification_evidence["before_geometry_sha256"] = preliminary.json()["provenance"][
        "before_geometry_sha256"
    ]
    reidentification_evidence["after_geometry_sha256"] = preliminary.json()["provenance"][
        "after_geometry_sha256"
    ]
    standalone = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={
            "before": before,
            "after": after,
            "registration_evidence": registration_evidence,
            "reidentification_evidence": reidentification_evidence,
        },
    )
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["delta_surface_area_m2"] == pytest.approx(0.5)
    assert expected["delta_surface_area_scale_interval_m2"] == pytest.approx([0.205, 0.805])
    assert expected["relative_surface_area_change_percent"] == pytest.approx(100)
    assert expected["scale_normalized_surface_area_ratio_after_to_before"] == (pytest.approx(2))
    assert expected["scale_normalized_bounding_box_diagonal_ratio_after_to_before"] == (
        pytest.approx(sqrt(5) / sqrt(2))
    )
    assert (
        "scale_normalized_area_ratio_requires_common_units_and_registration"
        in expected["qc_warnings"]
    )
    assert expected["elapsed_days"] == pytest.approx(1)
    assert expected["before_observed_at_utc_normalized"] == "2026-10-01T12:00:00Z"
    assert expected["after_observed_at_utc_normalized"] == "2026-10-02T12:00:00Z"
    assert expected["average_surface_area_change_m2_per_day"] == pytest.approx(0.5)
    assert expected["before_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(sqrt(2))
    assert expected["after_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(sqrt(5))
    assert expected["delta_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(
        sqrt(5) - sqrt(2)
    )
    assert expected["relative_axis_aligned_bounding_box_diagonal_change_percent"] == (
        pytest.approx(100 * (sqrt(5) / sqrt(2) - 1))
    )
    relative_extent_bounds = expected[
        "relative_axis_aligned_bounding_box_diagonal_scale_interval_percent"
    ]
    assert relative_extent_bounds == pytest.approx(
        [
            100 * (0.9 * sqrt(5) / (1.1 * sqrt(2)) - 1),
            100 * (1.1 * sqrt(5) / (0.9 * sqrt(2)) - 1),
        ]
    )
    assert expected["delta_axis_aligned_bounding_box_diagonal_scale_interval_m"] == pytest.approx(
        [0.9 * sqrt(5) - 1.1 * sqrt(2), 1.1 * sqrt(5) - 0.9 * sqrt(2)]
    )
    assert expected["average_axis_aligned_bounding_box_diagonal_change_m_per_day"] == pytest.approx(
        sqrt(5) - sqrt(2)
    )
    assert "axis_aligned_extent_change_is_not_verified_branch_growth" in expected["qc_warnings"]
    rate_bounds = expected["average_surface_area_change_scale_interval_m2_per_day"]
    assert rate_bounds == pytest.approx([0.205, 0.805])
    warnings = expected["qc_warnings"]
    assert "average_change_per_day_is_not_a_biological_growth_rate" in warnings
    assert expected["measurement_status"] == "provisional_unverified_longitudinal_comparison"
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert expected["provenance"]["before_coordinate_frame_id"] == "survey-local"
    assert expected["provenance"]["after_coordinate_frame_id"] == "survey-local"
    assert expected["provenance"]["coordinate_registration_verified"] is False
    assert expected["provenance"]["registration_evidence"] == registration_evidence
    assert expected["provenance"]["reidentification_evidence"] == reidentification_evidence
    assert expected["provenance"]["reidentification_evidence_review_status"] == (
        "caller_supplied_unverified"
    )
    assert "reidentification_independent_review_recorded_not_identity_verification" in warnings
    assert "reidentification_evidence_requires_independent_review" not in warnings
    assert "reidentification_specimen_binding_unavailable" not in warnings
    assert "reidentification_project_binding_unavailable" not in warnings
    assert "reidentification_geometry_binding_unavailable" not in warnings
    assert "reidentification_timepoint_binding_unavailable" not in warnings
    assert "reidentification_independent_review_timestamp_unavailable" not in warnings
    assert expected["provenance"]["registration_evidence_review_status"] == (
        "caller_supplied_unverified"
    )
    assert "registration_residual_requires_independent_review" in expected["qc_warnings"]
    assert "registration_transform_requires_independent_review" in expected["qc_warnings"]
    assert "registration_transform_unavailable" not in expected["qc_warnings"]
    assert expected["registration_residual_to_smaller_extent_ratio"] == pytest.approx(
        0.02 / sqrt(2)
    )
    assert expected["registration_translation_magnitude_m"] == pytest.approx(0.1)
    assert expected["registration_rotation_angle_degrees"] == pytest.approx(0.0)
    assert expected["registered_surface_centroid_offset_target_frame_m"] == pytest.approx(
        [-0.1, 1 / 3, 0.0]
    )
    assert expected["registered_surface_centroid_separation_m"] == pytest.approx(
        sqrt(0.1**2 + (1 / 3) ** 2)
    )
    assert "registered_centroid_offset_not_verified_biological_movement" in expected["qc_warnings"]
    assert "registered_centroid_position_uncertainty_not_estimated" in expected["qc_warnings"]
    assert expected["registered_centroid_separation_to_registration_rms_ratio"] == (
        pytest.approx(sqrt(0.1**2 + (1 / 3) ** 2) / 0.02)
    )
    assert (
        "registered_centroid_rms_ratio_not_a_movement_significance_test"
        in expected["qc_warnings"]
    )
    assert "registration_residual_at_least_smaller_mesh_extent" not in expected["qc_warnings"]
    assert "matching_coordinate_frame_id_not_registration_proof" in expected["qc_warnings"]
    assert "surface_area_change_is_not_verified_biological_growth" in expected["qc_warnings"]
    assert "open_mesh_surface_not_enclosed" in expected["before_mesh_qc_warnings"]
    assert "open_mesh_surface_not_enclosed" in expected["after_mesh_qc_warnings"]
    assert "source_mesh_qc_requires_review" in expected["qc_warnings"]
    assert expected["before_reconstruction_topology_counts"]["face_count"] == 1
    assert expected["after_reconstruction_topology_counts"]["face_count"] == 1
    assert expected["reconstruction_topology_changed_fields"] == []
    assert "reconstruction_topology_changed_requires_review" not in expected["qc_warnings"]
    assert "identical_geometry_topology_metadata_inconsistent" not in expected["qc_warnings"]

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    mesh_node = next(
        item for item in registry.json() if item["node_type"] == "mesh_surface_preview"
    )
    assert "coordinate_frame_id" in mesh_node["optional_parameters"]
    assert mesh_node["optional_parameters"]["coordinate_frame_id"] is None
    node = next(
        item for item in registry.json() if item["node_type"] == "mesh_longitudinal_comparison"
    )
    assert node["executable"] is True
    assert "registration_evidence" in node["optional_parameters"]
    assert "reidentification_evidence" in node["optional_parameters"]
    assert [port["accepted_types"] for port in node["input_ports"]] == [
        ["mesh_measurement_preview"],
        ["mesh_measurement_preview"],
    ]
    graph = {
        "graph_id": "mesh-longitudinal-v14",
        "name": "Provisional coral timepoint comparison",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "early", "node_type": "mesh_surface_preview", "parameters": before},
            {"node_id": "late", "node_type": "mesh_surface_preview", "parameters": after},
            {
                "node_id": "compare",
                "node_type": "mesh_longitudinal_comparison",
                "parameters": {
                    "registration_evidence": registration_evidence,
                    "reidentification_evidence": reidentification_evidence,
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-early",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "early",
                "target_port_id": "project",
            },
            {
                "edge_id": "project-late",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "late",
                "target_port_id": "project",
            },
            {
                "edge_id": "early-compare",
                "source_node_id": "early",
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": "before",
            },
            {
                "edge_id": "late-compare",
                "source_node_id": "late",
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": "after",
            },
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    compare_step = next(
        step for step in plan.json()["steps"] if step["node_type"] == "mesh_longitudinal_comparison"
    )
    assert "unverified 3D mesh observations" in compare_step["action"]
    assert compare_step["output_types"]["comparison"] == ["mesh_longitudinal_comparison"]
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    completed = process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    assert completed, client.get(f"/api/v1/workflow-runs/{run.json()['id']}").json()
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact["payload_json"] == expected
    assert len(artifact["payload_sha256"]) == 64


@pytest.mark.parametrize(
    ("rms", "extent", "expected_ratio", "warning"),
    [
        (0.02, 1.0, 0.02, None),
        (2.0, 1.0, 2.0, "registration_residual_at_least_smaller_mesh_extent"),
        (2.0, None, None, "registration_residual_extent_ratio_unavailable"),
        (0.0, 1_000_000.0, 0.0, None),
        (
            1e-320,
            1_000_000.0,
            None,
            "registration_residual_extent_ratio_out_of_numeric_range",
        ),
        (
            1_000_000.0,
            1e-320,
            None,
            "registration_residual_extent_ratio_out_of_numeric_range",
        ),
    ],
)
def test_registration_residual_size_qc_is_provisional_and_finite(
    rms: float, extent: float | None, expected_ratio: float | None, warning: str | None
) -> None:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "axis_aligned_bounding_box_diagonal_m": extent,
        "project_id": "study-1",
        "provenance": {
            "specimen_id": "colony-1",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "coordinate_frame_id": "frame-a",
        },
    }
    after = {
        **before,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "coordinate_frame_id": "frame-b",
        },
    }
    evidence = {
        "source_frame_id": "frame-a",
        "target_frame_id": "frame-b",
        "method": "landmark",
        "rms_residual_m": rms,
        "correspondence_count": 5,
        "evidence_note": "Unverified field registration",
    }
    result = compare_mesh_observations(before, after, evidence)
    if expected_ratio is None:
        assert result["registration_residual_to_smaller_extent_ratio"] is None
    else:
        assert result["registration_residual_to_smaller_extent_ratio"] == pytest.approx(
            expected_ratio
        )
    if warning is not None:
        assert warning in result["qc_warnings"]
    assert result["provenance"]["registration_evidence"] == evidence
    assert result["provenance"]["coordinate_registration_verified"] is False
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"


def test_positive_registration_residual_underflow_matches_saved_workflow(
    client: TestClient,
) -> None:
    """Do not serialize an underflowed positive RMS ratio as perfect alignment."""
    project_id = str(create_project(client, "Registration underflow QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    before = _mesh("scan-1", "2026-10-01T12:00:00Z", 1)
    after = _mesh("scan-2", "2026-10-02T12:00:00Z", 1)
    for record, frame in ((before, "frame-a"), (after, "frame-b")):
        record["meters_per_unit"] = 1_000_000
        record["coordinate_frame_id"] = frame
    evidence = {
        "source_frame_id": "frame-a",
        "target_frame_id": "frame-b",
        "method": "landmark",
        "rms_residual_m": 1e-320,
        "correspondence_count": 5,
        "evidence_note": "Unverified near-zero positive RMS; not exact alignment",
    }
    standalone = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after, "registration_evidence": evidence},
    )
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["registration_residual_to_smaller_extent_ratio"] is None
    assert "registration_residual_extent_ratio_out_of_numeric_range" in expected["qc_warnings"]
    assert expected["provenance"]["coordinate_registration_verified"] is False
    assert expected["provenance"]["registration_evidence"]["rms_residual_m"] > 0

    graph = {
        "graph_id": "registration-underflow-v14",
        "name": "Provisional positive registration residual underflow",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "early", "node_type": "mesh_surface_preview", "parameters": before},
            {"node_id": "late", "node_type": "mesh_surface_preview", "parameters": after},
            {
                "node_id": "compare",
                "node_type": "mesh_longitudinal_comparison",
                "parameters": {"registration_evidence": evidence},
            },
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
    artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact["payload_json"] == expected
    assert len(artifact["payload_sha256"]) == 64


@pytest.mark.parametrize(
    "override",
    [
        {"rms_residual_m": -1},
        {"rms_residual_m": "NaN"},
        {"correspondence_count": 2},
        {"correspondence_count": True},
        {"verified": True},
        {"source_frame_id": "unrelated-survey"},
        {"source_to_target_transform_m": [[1.0]]},
    ],
)
def test_pairwise_registration_evidence_is_validated(client: TestClient, override: dict) -> None:
    project_id = str(create_project(client, "Reject invalid registration evidence")["id"])
    before = _mesh("scan-1", "2026-10-01T12:00:00Z", 1)
    after = _mesh("scan-2", "2026-10-02T12:00:00Z", 1)
    before["coordinate_frame_id"] = "frame-a"
    after["coordinate_frame_id"] = "frame-b"
    evidence = {
        "source_frame_id": "frame-a",
        "target_frame_id": "frame-b",
        "method": "icp",
        "rms_residual_m": 0.03,
        "correspondence_count": 12,
        "evidence_note": "Unverified alignment",
        **override,
    }
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after, "registration_evidence": evidence},
    )
    assert response.status_code in (400, 422), response.text


def test_identical_mesh_rescaling_warns_without_claiming_growth(
    client: TestClient,
) -> None:
    """An unchanged scan with a revised calibration is not a growing colony."""
    project_id = str(create_project(client, "Rescaled mesh timepoints")["id"])
    before = _mesh("survey-1", "2026-10-01T12:00:00Z", 1)
    after = _mesh("survey-2", "2026-10-02T12:00:00Z", 1)
    before["coordinate_frame_id"] = "survey-a"
    after["coordinate_frame_id"] = "survey-b"
    after["meters_per_unit"] = 2
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["before_surface_area_m2"] == pytest.approx(0.5)
    assert result["after_surface_area_m2"] == pytest.approx(2)
    assert result["delta_surface_area_m2"] == pytest.approx(1.5)
    assert result["before_meters_per_mesh_unit"] == 1
    assert result["after_meters_per_mesh_unit"] == 2
    assert result["calibration_scale_ratio_after_to_before"] == pytest.approx(2)
    assert result["scale_normalized_surface_area_ratio_after_to_before"] == (pytest.approx(1))
    assert result["scale_normalized_bounding_box_diagonal_ratio_after_to_before"] == (
        pytest.approx(1)
    )
    assert (
        result["provenance"]["before_geometry_sha256"]
        == (result["provenance"]["after_geometry_sha256"])
    )
    assert "identical_geometry_fingerprint" in result["qc_warnings"]
    assert "calibration_scale_changed_between_observations" in result["qc_warnings"]
    assert "identical_geometry_rescaled_not_biological_growth" in result["qc_warnings"]
    assert "coordinate_frames_differ_registration_required" in result["qc_warnings"]
    assert result["provenance"]["before_coordinate_frame_id"] == "survey-a"
    assert result["provenance"]["after_coordinate_frame_id"] == "survey-b"
    assert result["provenance"]["coordinate_registration_verified"] is False
    assert result["provenance"]["registration_evidence"] is None
    assert "registration_evidence_unavailable" in result["qc_warnings"]
    assert (
        "identical_geometry_area_inconsistent_with_calibration_scale" not in result["qc_warnings"]
    )
    assert result["provenance"]["calibration_verified"] is False
    assert (
        "identical_geometry_extent_inconsistent_with_calibration_scale" not in result["qc_warnings"]
    )

    # The same warning and calibration ratio must survive a persisted typed
    # Workflow Builder execution, not only the standalone API request.
    base = f"/api/v1/projects/{project_id}"
    graph = {
        "graph_id": "mesh-rescaling-v14",
        "name": "Rescaling is not coral growth",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "early", "node_type": "mesh_surface_preview", "parameters": before},
            {"node_id": "late", "node_type": "mesh_surface_preview", "parameters": after},
            {"node_id": "compare", "node_type": "mesh_longitudinal_comparison"},
        ],
        "edges": [
            {
                "edge_id": "project-early",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "early",
                "target_port_id": "project",
            },
            {
                "edge_id": "project-late",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "late",
                "target_port_id": "project",
            },
            {
                "edge_id": "early-compare",
                "source_node_id": "early",
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": "before",
            },
            {
                "edge_id": "late-compare",
                "source_node_id": "late",
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": "after",
            },
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    completed = process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    assert completed, client.get(f"/api/v1/workflow-runs/{run.json()['id']}").json()
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact["payload_json"] == result
    assert len(artifact["payload_sha256"]) == 64


def test_mesh_comparison_retains_source_qc_and_calibration_differences(
    client: TestClient,
) -> None:
    """Do not erase reconstruction defects when scan formats or methods differ."""
    project_id = str(create_project(client, "Cross-format mesh QC")["id"])
    before = _mesh("scan-1", "2026-10-01T12:00:00Z", 1)
    after = _mesh("scan-2", "2026-10-02T12:00:00Z", 2)
    after.pop("vertices")
    after.pop("faces")
    after["obj_text"] = "v 0 0 0\nv 1 0 0\nv 0 2 0\nf 1 2 3"
    after["calibration_method"] = "instrument"
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert "open_mesh_surface_not_enclosed" in result["before_mesh_qc_warnings"]
    assert "open_mesh_surface_not_enclosed" in result["after_mesh_qc_warnings"]
    assert "source_mesh_qc_requires_review" in result["qc_warnings"]
    assert "mesh_source_formats_differ_between_observations" in result["qc_warnings"]
    assert "calibration_methods_differ_between_observations" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False


def test_mesh_comparison_runtime_context_is_not_a_user_parameter(
    client: TestClient,
) -> None:
    """Saved workflows inject execution IDs, not scientific node parameters."""
    app = cast(FastAPI, client.app)
    runtime_context = {
        "__workflow_run_id": "run-1",
        "__workflow_node_run_id": "node-1",
    }
    with app.state.session_factory() as session:
        # With no artifacts, the adapter must proceed past parameter validation.
        with pytest.raises(ValidationError, match="Each longitudinal input"):
            execute_mesh_longitudinal_comparison(
                session, app.state.settings, "project-1", runtime_context, {}
            )
        # Genuine user-supplied parameters remain disallowed.
        with pytest.raises(ValidationError, match="accepts only registration_evidence"):
            execute_mesh_longitudinal_comparison(
                session,
                app.state.settings,
                "project-1",
                {**runtime_context, "unrecognized": "value"},
                {},
            )


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"specimen_id": "another-colony"}, "specimen_id"),
        ({"observation_id": "survey-1"}, "distinct observation_id"),
        ({"observed_at_utc": "2026-09-30T12:00:00Z"}, "increasing timestamps"),
    ],
)
def test_mesh_comparison_rejects_invalid_pairing(
    client: TestClient, change: dict, error: str
) -> None:
    project_id = str(create_project(client, "Reject unreviewed pairing")["id"])
    before = _mesh("survey-1", "2026-10-01T12:00:00Z", 1)
    after = {**_mesh("survey-2", "2026-10-02T12:00:00Z", 2), **change}
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 400
    assert error in response.text


@pytest.mark.parametrize(
    ("first_project", "second_project"),
    [(None, None), ("", ""), ("project-1", "project-2"), (7, 7)],
)
def test_mesh_comparison_rejects_unscoped_or_cross_project_artifacts(
    first_project: object, second_project: object
) -> None:
    """Direct and persisted comparison engines must not accept unscoped artifacts."""
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "project_id": first_project,
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
        },
    }
    after = {
        **before,
        "project_id": second_project,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
        },
    }
    with pytest.raises(ValueError, match="same nonempty project_id"):
        compare_mesh_observations(before, after)


@pytest.mark.parametrize("invalid_provenance", [None, [], "unreviewed"])
def test_mesh_comparison_rejects_malformed_provenance(
    invalid_provenance: object,
) -> None:
    """Malformed metadata must fail as a validation error, not an AttributeError."""
    record = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
        },
    }
    later = {
        **record,
        "provenance": {
            **record["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
        },
    }
    with pytest.raises(ValueError, match="provenance dictionaries"):
        compare_mesh_observations({**record, "provenance": invalid_provenance}, later)


def test_mesh_comparison_does_not_invent_scale_uncertainty() -> None:
    base = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "surface_area_scale_interval_m2": None,
        "project_id": "p1",
        "provenance": {
            "specimen_id": "colony-1",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "geometry_sha256": "a",
        },
    }
    later = {
        **base,
        "surface_area_m2": 2.0,
        "provenance": {
            **base["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "geometry_sha256": "b",
        },
    }
    result = compare_mesh_observations(base, later)
    assert result["delta_surface_area_m2"] == 1
    assert result["delta_surface_area_scale_interval_m2"] is None
    assert result["delta_axis_aligned_bounding_box_diagonal_m"] is None
    assert result["relative_axis_aligned_bounding_box_diagonal_change_percent"] is None
    assert result["relative_axis_aligned_bounding_box_diagonal_scale_interval_percent"] is None
    assert "axis_aligned_extent_comparison_unavailable" in result["qc_warnings"]
    assert result["average_surface_area_change_m2_per_day"] == pytest.approx(1)
    assert result["average_surface_area_change_scale_interval_m2_per_day"] is None
    assert result["relative_surface_area_scale_interval_percent"] is None
    assert result["scale_normalized_surface_area_ratio_after_to_before"] is None
    assert "scale_normalized_area_ratio_unavailable" in result["qc_warnings"]
    assert "scale_uncertainty_interval_unavailable" in result["qc_warnings"]
    with pytest.raises(ValueError, match="QC warnings"):
        compare_mesh_observations({**base, "qc_warnings": ["open_mesh", None]}, later)
    missing_hash_before = {
        **base,
        "provenance": {**base["provenance"], "geometry_sha256": None},
    }
    missing_hash_after = {
        **later,
        "provenance": {**later["provenance"], "geometry_sha256": None},
    }
    missing_hash_result = compare_mesh_observations(missing_hash_before, missing_hash_after)
    assert "identical_geometry_fingerprint" not in missing_hash_result["qc_warnings"]
    early_extent = {
        **base,
        "axis_aligned_bounding_box_diagonal_m": 1.0,
        "axis_aligned_bounding_box_diagonal_scale_interval_m": [0.9, 1.1],
    }
    late_extent = {
        **later,
        "axis_aligned_bounding_box_diagonal_m": 2.0,
        "axis_aligned_bounding_box_diagonal_scale_interval_m": None,
    }
    extent_result = compare_mesh_observations(early_extent, late_extent)
    assert extent_result["delta_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(1)
    assert extent_result["relative_axis_aligned_bounding_box_diagonal_change_percent"] == (
        pytest.approx(100)
    )
    relative_bounds = extent_result[
        "relative_axis_aligned_bounding_box_diagonal_scale_interval_percent"
    ]
    assert relative_bounds is None
    assert extent_result["delta_axis_aligned_bounding_box_diagonal_scale_interval_m"] is None
    assert "extent_scale_uncertainty_interval_unavailable" in extent_result["qc_warnings"]
    malformed = {
        **late_extent,
        "axis_aligned_bounding_box_diagonal_scale_interval_m": [2.1, 2.2],
    }
    malformed_result = compare_mesh_observations(early_extent, malformed)
    assert malformed_result["delta_axis_aligned_bounding_box_diagonal_scale_interval_m"] is None
    with pytest.raises(ValueError, match="verification state"):
        compare_mesh_observations(
            {**base, "provenance": {**base["provenance"], "calibration_verified": True}},
            later,
        )


@pytest.mark.parametrize(
    ("invalid_timepoint", "invalid_interval"),
    [
        ("before", [1.1, 1.2]),
        ("before", [0.8, 0.9]),
        ("after", [2.1, 2.2]),
        ("after", [1.8, 1.9]),
    ],
)
def test_mesh_comparison_withholds_scale_bounds_excluding_nominal_area(
    invalid_timepoint: str, invalid_interval: list[float]
) -> None:
    """Unreviewed scale intervals must enclose their reported nominal areas."""
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "surface_area_scale_interval_m2": [0.8, 1.2],
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
        },
    }
    after = {
        **before,
        "surface_area_m2": 2.0,
        "surface_area_scale_interval_m2": [1.8, 2.2],
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
        },
    }
    record = before if invalid_timepoint == "before" else after
    record["surface_area_scale_interval_m2"] = invalid_interval
    result = compare_mesh_observations(before, after)
    assert result["delta_surface_area_m2"] == pytest.approx(1.0)
    assert result["delta_surface_area_scale_interval_m2"] is None
    assert result["relative_surface_area_scale_interval_percent"] is None
    assert result["average_surface_area_change_scale_interval_m2_per_day"] is None
    assert "scale_uncertainty_interval_unavailable" in result["qc_warnings"]


def test_mesh_comparison_average_rate_preserves_negative_change(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Mesh declining area")["id"])
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison",
        json={
            "before": _mesh("early", "2026-10-01T12:00:00Z", 2),
            "after": _mesh("late", "2026-10-03T12:00:00Z", 1),
        },
    )
    assert response.status_code == 200, response.text
    comparison = response.json()
    assert comparison["elapsed_days"] == pytest.approx(2)
    assert comparison["delta_surface_area_m2"] == pytest.approx(-0.5)
    assert comparison["delta_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(
        sqrt(2) - sqrt(5)
    )
    daily_extent_change = comparison["average_axis_aligned_bounding_box_diagonal_change_m_per_day"]
    assert daily_extent_change == pytest.approx((sqrt(2) - sqrt(5)) / 2)
    assert comparison["relative_axis_aligned_bounding_box_diagonal_change_percent"] == (
        pytest.approx(100 * (sqrt(2) / sqrt(5) - 1))
    )
    assert comparison["average_surface_area_change_m2_per_day"] == pytest.approx(-0.25)
    rate_bounds = comparison["average_surface_area_change_scale_interval_m2_per_day"]
    assert rate_bounds == pytest.approx([-0.4025, -0.1025])
    assert comparison["provenance"]["coordinate_registration_verified"] is False


@pytest.mark.parametrize(
    "invalid_area",
    [None, True, False, "1.0", -0.01, float("nan"), float("inf")],
)
@pytest.mark.parametrize("invalid_timepoint", ["before", "after"])
def test_mesh_comparison_rejects_non_numeric_area(
    invalid_area: object, invalid_timepoint: str
) -> None:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "surface_area_scale_interval_m2": [0.8, 1.2],
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "survey-1",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
        },
    }
    after = {
        **before,
        "provenance": {
            **before["provenance"],
            "observation_id": "survey-2",
            "observed_at_utc": "2026-10-02T12:00:00Z",
        },
    }
    target = before if invalid_timepoint == "before" else after
    target["surface_area_m2"] = invalid_area
    with pytest.raises(ValueError, match="finite and nonnegative"):
        compare_mesh_observations(before, after)


def test_mesh_comparison_zero_baseline_extent_withholds_relative_change() -> None:
    """Zero baseline cannot define percent change, even with known scale intervals."""
    base = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 0.0,
        "surface_area_scale_interval_m2": [0.0, 0.0],
        "axis_aligned_bounding_box_diagonal_m": 0.0,
        "axis_aligned_bounding_box_diagonal_scale_interval_m": [0.0, 0.0],
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "geometry_sha256": "first-geometry",
        },
    }
    later = {
        **base,
        "surface_area_m2": 1.0,
        "surface_area_scale_interval_m2": [0.81, 1.21],
        "axis_aligned_bounding_box_diagonal_m": 2.0,
        "axis_aligned_bounding_box_diagonal_scale_interval_m": [1.8, 2.2],
        "provenance": {
            **base["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "geometry_sha256": "second-geometry",
        },
    }
    comparison = compare_mesh_observations(base, later)
    assert comparison["relative_surface_area_change_percent"] is None
    assert comparison["relative_surface_area_scale_interval_percent"] is None
    assert comparison["scale_normalized_surface_area_ratio_after_to_before"] is None
    assert "relative_surface_area_change_unavailable_zero_baseline" in comparison["qc_warnings"]
    assert comparison["delta_axis_aligned_bounding_box_diagonal_m"] == pytest.approx(2)
    assert comparison["relative_axis_aligned_bounding_box_diagonal_change_percent"] is None
    relative_bounds = comparison[
        "relative_axis_aligned_bounding_box_diagonal_scale_interval_percent"
    ]
    assert relative_bounds is None
    assert "relative_axis_aligned_extent_change_unavailable" in comparison["qc_warnings"]
    assert comparison["provenance"]["coordinate_registration_verified"] is False


@pytest.mark.parametrize(
    "later_timestamp",
    ["2026-10-01T07:00:00-05:00", "2026-10-01T13:00:00+01:00"],
)
def test_mesh_comparison_rejects_same_instant_in_different_timezones(
    later_timestamp: str,
) -> None:
    """Different offset representations cannot create a false elapsed interval."""
    first = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
        },
    }
    later = {
        **first,
        "provenance": {
            **first["provenance"],
            "observation_id": "second",
            "observed_at_utc": later_timestamp,
        },
    }
    with pytest.raises(ValueError, match="increasing timestamps"):
        compare_mesh_observations(first, later)


@pytest.mark.parametrize("invalid_scale", [True, 0, -1, "1", float("nan"), float("inf")])
def test_mesh_comparison_rejects_invalid_calibration_metadata(invalid_scale: object) -> None:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "meters_per_mesh_unit": invalid_scale,
        },
    }
    after = {
        **before,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "meters_per_mesh_unit": 1.0,
        },
    }
    with pytest.raises(ValueError, match="Calibration scale metadata"):
        compare_mesh_observations(before, after)


@pytest.mark.parametrize(
    ("first_area", "second_area", "inconsistent"),
    [
        (1.0, 4.0, False),
        (1.0, 5.0, True),
        (0.0, 1.0, True),
        (0.0, 0.0, False),
        (1e-250, 4e-250, False),
        (1e-250, 5e-250, True),
    ],
)
def test_identical_geometry_requires_area_consistent_with_scale(
    first_area: float, second_area: float, inconsistent: bool
) -> None:
    """An identical source hash cannot explain a non-quadratic area change."""
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": first_area,
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "geometry_sha256": "a" * 64,
            "meters_per_mesh_unit": 1.0,
        },
    }
    after = {
        **before,
        "surface_area_m2": second_area,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "meters_per_mesh_unit": 2.0,
        },
    }
    result = compare_mesh_observations(before, after)
    warning = "identical_geometry_area_inconsistent_with_calibration_scale"
    assert (warning in result["qc_warnings"]) is inconsistent
    normalized = result["scale_normalized_surface_area_ratio_after_to_before"]
    if first_area > 0:
        assert normalized == pytest.approx(second_area / (4 * first_area))
    else:
        assert normalized is None
    assert result["provenance"]["specimen_identity_verified"] is False


@pytest.mark.parametrize(
    ("first_hash", "second_hash"),
    [
        ("placeholder", "placeholder"),
        ("A" * 64, "A" * 64),
        ("g" * 64, "g" * 64),
        ("", ""),
        (None, None),
        ("a" * 64, None),
    ],
)
def test_malformed_or_missing_geometry_hash_cannot_assert_identical_source(
    first_hash: object, second_hash: object
) -> None:
    """A matching label is not a valid SHA-256 source fingerprint."""
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "geometry_sha256": first_hash,
            "meters_per_mesh_unit": 1.0,
        },
    }
    after = {
        **before,
        "surface_area_m2": 5.0,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "geometry_sha256": second_hash,
            "meters_per_mesh_unit": 2.0,
        },
    }
    result = compare_mesh_observations(before, after)
    assert "geometry_fingerprint_missing_or_invalid" in result["qc_warnings"]
    assert "identical_geometry_fingerprint" not in result["qc_warnings"]
    assert (
        "identical_geometry_area_inconsistent_with_calibration_scale" not in result["qc_warnings"]
    )
    assert result["provenance"]["specimen_identity_verified"] is False


@pytest.mark.parametrize(
    ("first_extent", "second_extent", "first_scale", "second_scale", "expected"),
    [
        (1.0, 2.0, 1.0, 2.0, 1.0),
        (1.0, 3.0, 1.0, 2.0, 1.5),
        (1.0, 0.0, 1.0, 2.0, 0.0),
        (0.0, 2.0, 1.0, 2.0, None),
        (1.0, 2.0, None, 2.0, None),
        (None, 2.0, 1.0, 2.0, None),
    ],
)
def test_scale_normalized_extent_is_provisional_and_never_invents_missing_data(
    first_extent: float | None,
    second_extent: float,
    first_scale: float | None,
    second_scale: float,
    expected: float | None,
) -> None:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "axis_aligned_bounding_box_diagonal_m": first_extent,
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "meters_per_mesh_unit": first_scale,
        },
    }
    after = {
        **before,
        "axis_aligned_bounding_box_diagonal_m": second_extent,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "meters_per_mesh_unit": second_scale,
        },
    }
    result = compare_mesh_observations(before, after)
    value = result["scale_normalized_bounding_box_diagonal_ratio_after_to_before"]
    if expected is None:
        assert value is None
        assert "scale_normalized_extent_ratio_unavailable" in result["qc_warnings"]
    else:
        assert value == pytest.approx(expected)
        assert (
            "scale_normalized_extent_ratio_requires_common_units_and_registration"
            in result["qc_warnings"]
        )
    assert result["provenance"]["coordinate_registration_verified"] is False
    assert result["provenance"]["specimen_identity_verified"] is False


@pytest.mark.parametrize(
    ("first_extent", "second_extent"),
    [(1e-300, 1e300), (1e300, 1e-300)],
)
def test_scale_normalized_extent_rejects_overflow_and_positive_underflow(
    first_extent: float, second_extent: float
) -> None:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "axis_aligned_bounding_box_diagonal_m": first_extent,
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "meters_per_mesh_unit": 1.0,
        },
    }
    after = {
        **before,
        "axis_aligned_bounding_box_diagonal_m": second_extent,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
        },
    }
    result = compare_mesh_observations(before, after)
    assert result["scale_normalized_bounding_box_diagonal_ratio_after_to_before"] is None
    assert "scale_normalized_extent_ratio_out_of_numeric_range" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False


def test_exact_zero_followup_is_preserved_in_saved_workflow(client: TestClient) -> None:
    """Zero-area/extent reconstruction is provisional, not numeric underflow."""
    project_id = str(create_project(client, "Zero followup mesh QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    before = _mesh("first", "2026-10-01T12:00:00Z", 1)
    after = _mesh("second", "2026-10-02T12:00:00Z", 1)
    after["vertices"] = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    response = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["after_surface_area_m2"] == 0
    assert expected["after_axis_aligned_bounding_box_diagonal_m"] == 0
    assert expected["scale_normalized_surface_area_ratio_after_to_before"] == 0
    assert expected["scale_normalized_bounding_box_diagonal_ratio_after_to_before"] == 0
    warnings = expected["qc_warnings"]
    assert "zero_followup_surface_area_requires_reconstruction_review" in warnings
    assert "zero_followup_extent_requires_reconstruction_review" in warnings
    assert "source_mesh_qc_requires_review" in warnings
    assert "scale_normalized_area_ratio_out_of_numeric_range" not in warnings
    assert "scale_normalized_extent_ratio_out_of_numeric_range" not in warnings
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert expected["provenance"]["coordinate_registration_verified"] is False

    graph = {
        "graph_id": "zero-followup-v14",
        "name": "Provisional zero followup reconstruction",
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
    completed = process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    assert completed, client.get(f"/api/v1/workflow-runs/{run.json()['id']}").json()
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact["payload_json"] == expected
    assert len(artifact["payload_sha256"]) == 64


def test_positive_underflow_is_not_reported_as_true_zero_area() -> None:
    """Tiny positive geometry ratios must be withheld rather than rounded to zero."""
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1e300,
        "axis_aligned_bounding_box_diagonal_m": 1e300,
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "meters_per_mesh_unit": 1.0,
        },
    }
    after = {
        **before,
        "surface_area_m2": 1e-300,
        "axis_aligned_bounding_box_diagonal_m": 1e-300,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
        },
    }
    result = compare_mesh_observations(before, after)
    assert result["scale_normalized_surface_area_ratio_after_to_before"] is None
    assert result["scale_normalized_bounding_box_diagonal_ratio_after_to_before"] is None
    assert "scale_normalized_area_ratio_out_of_numeric_range" in result["qc_warnings"]
    assert "scale_normalized_extent_ratio_out_of_numeric_range" in result["qc_warnings"]
    assert "zero_followup_surface_area_requires_reconstruction_review" not in result["qc_warnings"]
    assert "zero_followup_extent_requires_reconstruction_review" not in result["qc_warnings"]


@pytest.mark.parametrize(
    ("early_extent", "late_extent", "inconsistent"),
    [
        (1.0, 2.0, False),
        (1.0, 3.0, True),
        (0.0, 0.0, False),
        (0.0, 2.0, True),
        (1.0, 0.0, True),
        (None, 2.0, False),
    ],
)
def test_identical_mesh_extent_requires_calibration_consistency(
    early_extent: float | None, late_extent: float, inconsistent: bool
) -> None:
    """Identical geometry cannot acquire a different raw extent after rescaling."""
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "axis_aligned_bounding_box_diagonal_m": early_extent,
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "geometry_sha256": "a" * 64,
            "meters_per_mesh_unit": 1.0,
        },
    }
    after = {
        **before,
        "surface_area_m2": 4.0,
        "axis_aligned_bounding_box_diagonal_m": late_extent,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "meters_per_mesh_unit": 2.0,
        },
    }
    result = compare_mesh_observations(before, after)
    warning = "identical_geometry_extent_inconsistent_with_calibration_scale"
    assert (warning in result["qc_warnings"]) is inconsistent
    assert (
        "identical_geometry_area_inconsistent_with_calibration_scale" not in result["qc_warnings"]
    )
    assert result["provenance"]["specimen_identity_verified"] is False
    assert result["provenance"]["coordinate_registration_verified"] is False


@pytest.mark.parametrize(
    ("before_frame", "after_frame", "expected_warning"),
    [
        (None, None, "coordinate_frame_metadata_unavailable"),
        ("survey-a", None, "coordinate_frame_metadata_unavailable"),
        ("survey-a", "survey-b", "coordinate_frames_differ_registration_required"),
        ("survey-a", "survey-a", "matching_coordinate_frame_id_not_registration_proof"),
    ],
)
def test_mesh_comparison_coordinate_frame_evidence_is_provisional(
    before_frame: str | None, after_frame: str | None, expected_warning: str
) -> None:
    """A shared label is not proof of a common registered coordinate system."""
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "coordinate_frame_id": before_frame,
        },
    }
    after = {
        **before,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "coordinate_frame_id": after_frame,
        },
    }
    result = compare_mesh_observations(before, after)
    assert expected_warning in result["qc_warnings"]
    assert result["provenance"]["before_coordinate_frame_id"] == before_frame
    assert result["provenance"]["after_coordinate_frame_id"] == after_frame
    assert result["provenance"]["coordinate_registration_verified"] is False


@pytest.mark.parametrize("invalid_frame", ["", "two words", "bad/frame", "x" * 129, 1, True])
def test_mesh_comparison_rejects_invalid_coordinate_frame_metadata(
    invalid_frame: object,
) -> None:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "project_id": "project-1",
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "coordinate_frame_id": invalid_frame,
        },
    }
    after = {
        **before,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "coordinate_frame_id": "valid",
        },
    }
    with pytest.raises(ValueError, match="Coordinate frame IDs"):
        compare_mesh_observations(before, after)


def test_mesh_comparison_flags_changed_reconstruction_topology(
    client: TestClient,
) -> None:
    """New reconstructed faces are not automatically new biological tissue."""
    project_id = str(create_project(client, "Topology change QC")["id"])
    before = _mesh("first", "2026-10-01T12:00:00Z", 1)
    after = _mesh("second", "2026-10-02T12:00:00Z", 1)
    after["vertices"] = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]]
    after["faces"] = [[0, 1, 2], [1, 3, 2]]
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["before_reconstruction_topology_counts"]["face_count"] == 1
    assert result["after_reconstruction_topology_counts"]["face_count"] == 2
    assert result["before_reconstruction_topology_counts"]["boundary_edge_count"] == 3
    assert result["after_reconstruction_topology_counts"]["boundary_edge_count"] == 4
    assert result["reconstruction_topology_changed_fields"] == [
        "face_count",
        "boundary_edge_count",
    ]
    assert "reconstruction_topology_changed_requires_review" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False
    assert result["provenance"]["coordinate_registration_verified"] is False


def _minimal_topology_pair() -> tuple[dict, dict]:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "surface_area_m2": 1.0,
        "project_id": "project-1",
        "face_count": 1,
        "provenance": {
            "specimen_id": "colony-16",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
        },
    }
    after = {
        **before,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
        },
    }
    return before, after


def test_mesh_comparison_keeps_legacy_missing_topology_unknown() -> None:
    before, after = _minimal_topology_pair()
    result = compare_mesh_observations(before, after)
    assert result["reconstruction_topology_changed_fields"] == []
    assert result["before_reconstruction_topology_counts"]["boundary_edge_count"] is None
    assert "reconstruction_topology_comparison_incomplete" in result["qc_warnings"]
    assert "reconstruction_topology_changed_requires_review" not in result["qc_warnings"]


@pytest.mark.parametrize("invalid_count", [True, -1, 1.25, "2"])
def test_mesh_comparison_rejects_malformed_topology_counts(
    invalid_count: object,
) -> None:
    before, after = _minimal_topology_pair()
    after["face_count"] = invalid_count
    with pytest.raises(ValueError, match="face_count must be a nonnegative integer"):
        compare_mesh_observations(before, after)


@pytest.mark.parametrize(
    ("first_hash", "second_hash", "topology_changed", "inconsistent"),
    [
        ("a" * 64, "a" * 64, True, True),
        ("a" * 64, "b" * 64, True, False),
        ("placeholder", "placeholder", True, False),
        ("a" * 64, "a" * 64, False, False),
    ],
)
def test_matching_geometry_fingerprint_requires_consistent_topology_metadata(
    first_hash: str, second_hash: str, topology_changed: bool, inconsistent: bool
) -> None:
    """An identical source geometry cannot change its reconstructed face count."""
    before, after = _minimal_topology_pair()
    before["provenance"]["geometry_sha256"] = first_hash
    after["provenance"]["geometry_sha256"] = second_hash
    if topology_changed:
        after["face_count"] = 2
    result = compare_mesh_observations(before, after)
    assert (
        "identical_geometry_topology_metadata_inconsistent" in result["qc_warnings"]
    ) is inconsistent
    assert (
        "reconstruction_topology_changed_requires_review" in result["qc_warnings"]
    ) is topology_changed
    assert result["provenance"]["specimen_identity_verified"] is False
    assert result["provenance"]["coordinate_registration_verified"] is False


@pytest.mark.parametrize(
    ("field_values", "error"),
    [
        ({"face_count": 1, "edge_connected_patch_count": 2}, "patch count"),
        ({"face_count": 1, "edge_connected_patch_count": 0}, "patch count"),
        ({"face_count": 1, "degenerate_face_count": 2}, "degenerate count"),
        ({"face_count": 1, "boundary_edge_count": 4}, "boundary_edge_count"),
        ({"face_count": 1, "nonmanifold_edge_count": 4}, "nonmanifold_edge_count"),
        ({"face_count": 0, "boundary_edge_count": 1}, "boundary_edge_count"),
    ],
)
@pytest.mark.parametrize("timepoint", ["before", "after"])
def test_mesh_comparison_rejects_impossible_topology_relationships(
    field_values: dict[str, int], error: str, timepoint: str
) -> None:
    """Corrupt persisted reconstruction counts must not enter scientific comparisons."""
    before, after = _minimal_topology_pair()
    target = before if timepoint == "before" else after
    target.update(field_values)
    with pytest.raises(ValueError, match=error):
        compare_mesh_observations(before, after)


def test_mesh_comparison_preserves_partial_legacy_topology_without_face_count() -> None:
    """Do not fabricate a face count to validate an older partial artifact."""
    before, after = _minimal_topology_pair()
    before.pop("face_count")
    before["boundary_edge_count"] = 3
    result = compare_mesh_observations(before, after)
    assert result["before_reconstruction_topology_counts"]["face_count"] is None
    assert "reconstruction_topology_comparison_incomplete" in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False


@pytest.mark.parametrize(
    ("early_scale", "late_scale"),
    [(1e-320, 1e6), (1e6, 1e-320)],
)
def test_extreme_positive_calibration_ratio_is_withheld_in_saved_workflow(
    client: TestClient, early_scale: float, late_scale: float
) -> None:
    """Positive calibration ratios cannot be silently rounded to zero or infinity."""
    project_id = str(create_project(client, "Extreme calibration ratio QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    before = _mesh("first", "2026-10-01T12:00:00Z", 1)
    after = _mesh("second", "2026-10-02T12:00:00Z", 1)
    for record, scale in ((before, early_scale), (after, late_scale)):
        record["vertices"] = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        record["meters_per_unit"] = scale
    response = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["calibration_scale_ratio_after_to_before"] is None
    assert "calibration_scale_ratio_out_of_numeric_range" in expected["qc_warnings"]
    assert expected["before_surface_area_m2"] == 0
    assert expected["after_surface_area_m2"] == 0
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["coordinate_registration_verified"] is False

    graph = {
        "graph_id": "extreme-scale-ratio-v14",
        "name": "Withhold unrepresentable positive calibration ratio",
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
    artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact["payload_json"] == expected
    assert len(artifact["payload_sha256"]) == 64


@pytest.mark.parametrize(
    ("before_area", "after_area", "expected_percent"),
    [(1e307, 2e307, 100.0), (2e307, 1e307, -50.0)],
)
def test_longitudinal_area_percent_remains_finite_for_large_finite_values(
    before_area: float, after_area: float, expected_percent: float
) -> None:
    """A finite percent must not be lost to overflow in 100 * area delta."""
    before, after = _minimal_topology_pair()
    before["surface_area_m2"] = before_area
    after["surface_area_m2"] = after_area

    result = compare_mesh_observations(before, after)

    assert result["relative_surface_area_change_percent"] == pytest.approx(expected_percent)
    assert result["delta_surface_area_m2"] == pytest.approx(after_area - before_area)
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"
    assert result["provenance"]["specimen_identity_verified"] is False
    assert result["provenance"]["coordinate_registration_verified"] is False


@pytest.mark.parametrize(
    ("row", "column", "invalid"),
    [
        (0, 0, 2.0),  # scale is not rigid
        (0, 1, 0.1),  # shear is not rigid
        (2, 2, -1.0),  # reflection reverses handedness
        (3, 3, 0.0),  # non-affine homogeneous row
        (0, 3, float("inf")),  # nonfinite translation
        (0, 3, 1_000_001.0),  # unbounded translation
    ],
)
def test_registration_transform_rejects_nonrigid_or_nonfinite_values(
    row: int, column: int, invalid: float
) -> None:
    transform = _rigid_transform()
    transform[row][column] = invalid
    with pytest.raises(ValueError):
        MeshRegistrationEvidence.model_validate(
            {
                "source_frame_id": "frame-a",
                "target_frame_id": "frame-b",
                "method": "landmark",
                "rms_residual_m": 0.01,
                "correspondence_count": 6,
                "evidence_note": "Provisional registration awaiting review",
                "source_to_target_transform_m": transform,
            }
        )


def test_registration_transform_rejects_invalid_matrix_shape() -> None:
    transform = _rigid_transform()[:3]
    with pytest.raises(ValueError, match="4x4"):
        MeshRegistrationEvidence.model_validate(
            {
                "source_frame_id": "frame-a",
                "target_frame_id": "frame-b",
                "method": "landmark",
                "rms_residual_m": 0.01,
                "correspondence_count": 6,
                "evidence_note": "Provisional registration awaiting review",
                "source_to_target_transform_m": transform,
            }
        )


def test_registration_transform_accepts_proper_rotation_without_verification() -> None:
    transform = [
        [0.0, -1.0, 0.0, 0.1],
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    evidence = MeshRegistrationEvidence.model_validate(
        {
            "source_frame_id": "frame-a",
            "target_frame_id": "frame-b",
            "method": "landmark",
            "rms_residual_m": 0.01,
            "correspondence_count": 6,
            "evidence_note": "Provisional registration awaiting review",
            "source_to_target_transform_m": transform,
        }
    )
    assert evidence.source_to_target_transform_m == transform
    assert "verified" not in evidence.model_dump(mode="json")


@pytest.mark.parametrize(
    ("rotation", "translation", "expected_angle", "expected_distance"),
    [
        (
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            (0.0, 0.0, 0.0),
            0.0,
            0.0,
        ),
        (
            [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
            (0.3, 0.4, 0.0),
            90.0,
            0.5,
        ),
        (
            [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]],
            (0.0, 0.0, -0.2),
            180.0,
            0.2,
        ),
    ],
)
def test_registration_transform_diagnostics_remain_unverified(
    rotation: list[list[float]],
    translation: tuple[float, float, float],
    expected_angle: float,
    expected_distance: float,
) -> None:
    """Summarize a rigid transform without applying it to coral geometry."""
    before, after = _minimal_topology_pair()
    before["provenance"]["coordinate_frame_id"] = "survey-a"
    after["provenance"]["coordinate_frame_id"] = "survey-b"
    transform = [[*row, offset] for row, offset in zip(rotation, translation, strict=True)] + [
        [0.0, 0.0, 0.0, 1.0]
    ]
    evidence = {
        "source_frame_id": "survey-a",
        "target_frame_id": "survey-b",
        "method": "landmark",
        "rms_residual_m": 0.01,
        "correspondence_count": 6,
        "evidence_note": "Caller-supplied alignment; no independent verification",
        "source_to_target_transform_m": transform,
    }
    result = compare_mesh_observations(before, after, evidence)
    assert result["registration_translation_magnitude_m"] == pytest.approx(expected_distance)
    assert result["registration_rotation_angle_degrees"] == pytest.approx(expected_angle)
    preserved_transform = result["provenance"]["registration_evidence"][
        "source_to_target_transform_m"
    ]
    assert preserved_transform == transform
    assert result["provenance"]["coordinate_registration_verified"] is False
    assert result["provenance"]["specimen_identity_verified"] is False
    assert "registration_transform_requires_independent_review" in result["qc_warnings"]


def test_registration_transform_diagnostics_missing_matrix_stay_unknown() -> None:
    before, after = _minimal_topology_pair()
    before["provenance"]["coordinate_frame_id"] = "survey-a"
    after["provenance"]["coordinate_frame_id"] = "survey-b"
    evidence = {
        "source_frame_id": "survey-a",
        "target_frame_id": "survey-b",
        "method": "landmark",
        "rms_residual_m": 0.01,
        "correspondence_count": 6,
        "evidence_note": "Registration residual available; transform unavailable",
    }
    result = compare_mesh_observations(before, after, evidence)
    assert result["registration_translation_magnitude_m"] is None
    assert result["registration_rotation_angle_degrees"] is None
    assert "registration_transform_unavailable" in result["qc_warnings"]
    assert result["provenance"]["coordinate_registration_verified"] is False


@pytest.mark.parametrize(
    ("source_centroid", "target_centroid", "expected_offset"),
    [
        ([1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 1.0, 0.0]),
        (None, [0.0, 2.0, 0.0], None),
    ],
)
def test_registered_centroid_uses_provisional_source_to_target_transform(
    source_centroid: list[float] | None,
    target_centroid: list[float],
    expected_offset: list[float] | None,
) -> None:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "project_id": "study-1",
        "surface_area_m2": 1.0,
        "area_weighted_surface_centroid_m": source_centroid,
        "provenance": {
            "specimen_id": "colony-1",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "coordinate_frame_id": "frame-a",
        },
    }
    after = {
        **before,
        "area_weighted_surface_centroid_m": target_centroid,
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "coordinate_frame_id": "frame-b",
        },
    }
    evidence = {
        "source_frame_id": "frame-a",
        "target_frame_id": "frame-b",
        "method": "landmark",
        "rms_residual_m": 0.01,
        "correspondence_count": 5,
        "evidence_note": "Unreviewed landmark registration",
        "source_to_target_transform_m": [
            [0.0, -1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
    }
    result = compare_mesh_observations(before, after, evidence)
    assert result["registered_surface_centroid_offset_target_frame_m"] == expected_offset
    if expected_offset is None:
        assert result["registered_surface_centroid_separation_m"] is None
        assert "registered_surface_centroid_comparison_unavailable" in result["qc_warnings"]
    else:
        assert result["registered_surface_centroid_separation_m"] == pytest.approx(1.0)
        assert (
            "registered_centroid_offset_not_verified_biological_movement" in (result["qc_warnings"])
        )
        assert result["provenance"]["coordinate_registration_verified"] is False
        assert result["provenance"]["specimen_identity_verified"] is False
    evidence.pop("source_to_target_transform_m")
    missing_transform = compare_mesh_observations(before, after, evidence)
    assert missing_transform["registered_surface_centroid_separation_m"] is None


@pytest.mark.parametrize(
    "invalid_centroid",
    [[1.0, float("nan"), 0.0], [True, 0.0, 0.0], [0.0, 1.0]],
)
def test_registered_centroid_rejects_invalid_coordinates(
    invalid_centroid: list[float],
) -> None:
    before = {
        "schema_version": "mesh-preview-0001",
        "measurement_status": "caller_supplied_unverified",
        "project_id": "study-1",
        "surface_area_m2": 1.0,
        "area_weighted_surface_centroid_m": invalid_centroid,
        "provenance": {
            "specimen_id": "colony-1",
            "observation_id": "first",
            "observed_at_utc": "2026-10-01T12:00:00Z",
            "calibration_verified": False,
            "coordinate_frame_id": "frame-a",
        },
    }
    after = {
        **before,
        "area_weighted_surface_centroid_m": [0.0, 0.0, 0.0],
        "provenance": {
            **before["provenance"],
            "observation_id": "second",
            "observed_at_utc": "2026-10-02T12:00:00Z",
            "coordinate_frame_id": "frame-b",
        },
    }
    evidence = {
        "source_frame_id": "frame-a",
        "target_frame_id": "frame-b",
        "method": "landmark",
        "rms_residual_m": 0.01,
        "correspondence_count": 5,
        "evidence_note": "Unreviewed alignment",
        "source_to_target_transform_m": _rigid_transform(),
    }
    with pytest.raises(ValueError, match="Surface centroid must be three finite"):
        compare_mesh_observations(before, after, evidence)


@pytest.mark.parametrize(
    "override",
    [
        {"before_observation_id": "different-scan"},
        {"after_observation_id": "different-scan"},
        {"verified": True},
        {"method": "automatic_certified"},
        {"observer_id": ""},
        {"specimen_id": "different-colony"},
        {"specimen_id": True},
    ],
)
def test_provisional_reidentification_rejects_mismatched_or_verified_claims(
    client: TestClient, override: dict
) -> None:
    project_id = str(create_project(client, "Provisional identity review")["id"])
    evidence = {
        "before_observation_id": "scan-1",
        "after_observation_id": "scan-2",
        "method": "visual_morphology",
        "observer_id": "observer-1",
        "evidence_note": "Unreviewed visual match",
        **override,
    }
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison",
        json={
            "before": _mesh("scan-1", "2026-10-01T12:00:00Z", 1),
            "after": _mesh("scan-2", "2026-10-02T12:00:00Z", 1),
            "reidentification_evidence": evidence,
        },
    )
    assert response.status_code in (400, 422), response.text


def test_reidentification_missing_does_not_imply_verified_identity() -> None:
    before, after = _minimal_topology_pair()
    result = compare_mesh_observations(before, after)
    assert result["provenance"]["reidentification_evidence"] is None
    assert result["provenance"]["reidentification_evidence_review_status"] == "unavailable"
    assert result["provenance"]["specimen_identity_verified"] is False
    assert "reidentification_evidence_unavailable" in result["qc_warnings"]


def test_reidentification_specimen_binding_is_provisional_and_legacy_safe() -> None:
    before, after = _minimal_topology_pair()
    evidence = {
        "before_observation_id": "first",
        "after_observation_id": "second",
        "method": "photo_match",
        "observer_id": "reviewer-1",
        "evidence_note": "Unverified visual correspondence",
    }
    legacy = compare_mesh_observations(before, after, evidence)
    assert legacy["provenance"]["reidentification_evidence"] == evidence
    assert "reidentification_specimen_binding_unavailable" in legacy["qc_warnings"]
    bound = {**evidence, "specimen_id": "colony-16"}
    result = compare_mesh_observations(before, after, bound)
    assert result["provenance"]["reidentification_evidence"] == bound
    assert "reidentification_specimen_binding_unavailable" not in result["qc_warnings"]
    assert result["provenance"]["specimen_identity_verified"] is False
    assert "reidentification_evidence_requires_independent_review" in result["qc_warnings"]
    with pytest.raises(ValueError, match="provisional specimen ID"):
        compare_mesh_observations(before, after, {**bound, "specimen_id": "other-colony"})


def test_mutated_reidentification_specimen_binding_is_revalidated() -> None:
    before, after = _minimal_topology_pair()
    evidence = MeshReidentificationEvidence(
        specimen_id="colony-16",
        before_observation_id="first",
        after_observation_id="second",
        method="photo_match",
        observer_id="reviewer-1",
        evidence_note="Unverified visual correspondence",
    )
    evidence.specimen_id = "other-colony"
    with pytest.raises(ValueError, match="provisional specimen ID"):
        compare_mesh_observations(before, after, reidentification_evidence=evidence)

@pytest.mark.parametrize(
    ("rms", "centroid_separation", "expected_ratio", "warning"),
    [
        (
            0.25,
            0.5,
            2.0,
            "registered_centroid_rms_ratio_not_a_movement_significance_test",
        ),
        (
            0.25,
            0.0,
            0.0,
            "registered_centroid_rms_ratio_not_a_movement_significance_test",
        ),
        (0.0, 0.5, None, "registered_centroid_rms_ratio_unavailable_zero_residual"),
        (1e-320, 0.5, None, "registered_centroid_rms_ratio_out_of_numeric_range"),
    ],
)
def test_registered_centroid_rms_ratio_is_only_a_provisional_diagnostic(
    rms: float,
    centroid_separation: float,
    expected_ratio: float | None,
    warning: str,
) -> None:
    before, after = _minimal_topology_pair()
    before["provenance"]["coordinate_frame_id"] = "frame-a"
    after["provenance"]["coordinate_frame_id"] = "frame-b"
    before["area_weighted_surface_centroid_m"] = [0.0, 0.0, 0.0]
    after["area_weighted_surface_centroid_m"] = [centroid_separation, 0.0, 0.0]
    evidence = {
        "source_frame_id": "frame-a",
        "target_frame_id": "frame-b",
        "method": "landmark",
        "rms_residual_m": rms,
        "correspondence_count": 6,
        "evidence_note": "Unreviewed caller-supplied registration",
        "source_to_target_transform_m": [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
    }
    result = compare_mesh_observations(before, after, evidence)
    assert result["registered_centroid_separation_to_registration_rms_ratio"] == (
        pytest.approx(expected_ratio) if expected_ratio is not None else None
    )
    assert warning in result["qc_warnings"]
    assert result["provenance"]["coordinate_registration_verified"] is False
    assert result["provenance"]["specimen_identity_verified"] is False
    assert result["measurement_status"] == (
        "provisional_unverified_longitudinal_comparison"
    )


def test_registered_centroid_rms_ratio_is_unknown_without_centroids() -> None:
    before, after = _minimal_topology_pair()
    before["provenance"]["coordinate_frame_id"] = "frame-a"
    after["provenance"]["coordinate_frame_id"] = "frame-b"
    result = compare_mesh_observations(
        before,
        after,
        {
            "source_frame_id": "frame-a",
            "target_frame_id": "frame-b",
            "method": "landmark",
            "rms_residual_m": 0.2,
            "correspondence_count": 6,
            "evidence_note": "Unreviewed alignment",
            "source_to_target_transform_m": [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
        },
    )
    assert result["registered_centroid_separation_to_registration_rms_ratio"] is None
    assert "registered_surface_centroid_comparison_unavailable" in result["qc_warnings"]

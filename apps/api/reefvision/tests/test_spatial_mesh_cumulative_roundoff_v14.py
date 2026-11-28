"""Selected mesh-edge cumulative roundoff stays explicit in saved science artifacts."""

from __future__ import annotations

from fractions import Fraction
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_paths_v14 import mesh_edge_paths
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

# All coordinates satisfy the public 1e9 source-coordinate bound.
# The path 0 -> 1 -> 3 has positive lengths 1e9 and 1e-8; the latter
# cannot advance a cumulative binary64 distance of 1e9.
GEOMETRY = {
    "vertices": [
        [0.0, 0.0, 0.0],
        [1_000_000_000.0, 0.0, 0.0],
        [1_000_000_000.0, 0.0, 1e-8],
        [1_000_000_000.0, 1e-8, 0.0],
    ],
    "faces": [[0, 1, 2], [1, 2, 3]],
    "meters_per_unit": 1.0,
    "calibration_method": "ruler",
    "calibration_evidence": "Synthetic unverified route precision reference",
    "relative_scale_uncertainty": 0.01,
    "surface_path_vertex_pairs": [[0, 3], [0, 1]],
}


def test_selected_route_cumulative_roundoff_is_exposed_and_replayed(
    client: TestClient,
) -> None:
    direct_paths = mesh_edge_paths(
        points=[tuple(vertex) for vertex in GEOMETRY["vertices"]],
        faces=GEOMETRY["faces"],
        pairs=GEOMETRY["surface_path_vertex_pairs"],
        scale=1.0,
        scale_uncertainty=0.01,
    )
    assert direct_paths is not None
    affected, unaffected = direct_paths
    assert affected["status"] == "connected"
    assert affected["path_vertex_indices"] == [0, 1, 3]
    assert affected["path_edge_lengths_m"] == [1_000_000_000.0, 1e-8]
    assert affected["path_cumulative_lengths_m"] == [
        0.0,
        1_000_000_000.0,
        1_000_000_000.0,
    ]
    assert affected["path_cumulative_lost_positive_segment_indices"] == [1]
    assert affected["path_calibrated_underflow_segment_indices"] == []
    exact_total = Fraction(1_000_000_000.0) + Fraction(1e-8)
    assert affected["path_calibrated_edge_sum_exact_fraction_m"] == str(exact_total)
    assert affected["path_cumulative_total_exact_match"] is False
    assert affected["path_cumulative_roundoff_exact_fraction_m"] == str(-Fraction(1e-8))
    assert affected["path_nominal_total_vs_edge_sum_exact_fraction_m"] == str(-Fraction(1e-8))
    assert affected["path_nominal_total_exact_match"] is False
    expected_edge_chord_excess = str(Fraction(1e-8))
    assert affected["path_source_edge_sum_minus_chord_exact_fraction"] == expected_edge_chord_excess
    # The exact stored binary64 source-edge sum exceeds the rounded chord,
    # although Dijkstra's displayed route total equals that chord. A nominal
    # detour ratio of 1 or exact zero excess would conceal a positive segment.
    assert affected["length_m"] == affected["endpoint_chord_length_m"]
    assert affected["geometric_detour_ratio"] is None
    assert affected["geometric_excess_length_m"] is None
    assert affected["geometric_excess_scale_interval_m"] is None
    assert (
        "selected_mesh_route_roundoff_hides_stored_edge_chord_excess"
        in affected["path_qc_warnings"]
    )
    assert (
        "selected_mesh_route_nominal_total_disagrees_with_exact_edge_sum"
        in affected["path_qc_warnings"]
    )
    assert (
        "positive_selected_mesh_segment_lost_in_cumulative_distance" in affected["path_qc_warnings"]
    )
    assert (
        "selected_mesh_route_cumulative_roundoff_disagrees_with_exact_edge_sum"
        in affected["path_qc_warnings"]
    )
    assert affected["path_edge_length_scale_intervals_m"][1] == [
        1e-8 * 0.99,
        1e-8 * 1.01,
    ]
    assert unaffected["path_cumulative_lost_positive_segment_indices"] == []
    assert unaffected["path_calibrated_underflow_segment_indices"] == []
    assert unaffected["path_calibrated_edge_sum_exact_fraction_m"] == "1000000000"
    assert unaffected["path_cumulative_total_exact_match"] is True
    assert unaffected["path_cumulative_roundoff_exact_fraction_m"] == "0"
    assert unaffected["path_nominal_total_vs_edge_sum_exact_fraction_m"] == "0"
    assert unaffected["path_nominal_total_exact_match"] is True
    assert unaffected["path_source_edge_sum_minus_chord_exact_fraction"] == "0"
    assert unaffected["geometric_detour_ratio"] == 1.0
    assert unaffected["geometric_excess_length_m"] == 0.0
    assert unaffected["geometric_excess_scale_interval_m"] == [0.0, 0.0]
    assert (
        "selected_mesh_route_roundoff_hides_stored_edge_chord_excess"
        not in unaffected["path_qc_warnings"]
    )
    assert (
        "selected_mesh_route_nominal_total_disagrees_with_exact_edge_sum"
        not in unaffected["path_qc_warnings"]
    )
    assert (
        "selected_mesh_route_cumulative_roundoff_disagrees_with_exact_edge_sum"
        not in unaffected["path_qc_warnings"]
    )
    assert (
        "positive_selected_mesh_segment_lost_in_cumulative_distance"
        not in unaffected["path_qc_warnings"]
    )

    direct = measure_mesh_preview(**GEOMETRY)
    assert direct["surface_edge_paths"] == direct_paths
    assert direct["measurement_status"] == "caller_supplied_unverified"
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Mesh path cumulative numeric integrity")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=GEOMETRY)
    assert standalone.status_code == 200, standalone.text
    measured = standalone.json()
    assert measured["surface_edge_paths"] == direct_paths
    assert measured["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "mesh-cumulative-roundoff-v14",
        "name": "Mesh route cumulative-distance precision QC",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": GEOMETRY},
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    digests: list[str] = []
    app = cast(FastAPI, client.app)
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
        assert artifact["payload_json"] == measured
        digests.append(artifact["payload_sha256"])
    assert len(set(digests)) == 1
    assert len(digests[0]) == 64


def test_unreferenced_route_has_no_nominal_exact_audit() -> None:
    """Absent mesh path evidence must not be represented as an exact match."""
    results = mesh_edge_paths(
        points=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (9.0, 9.0, 9.0)],
        faces=[[0, 1, 2]],
        pairs=[[0, 3]],
        scale=1.0,
        scale_uncertainty=0.01,
    )
    assert results is not None
    missing = results[0]
    assert missing["status"] == "unreferenced_endpoint"
    assert missing["path_nominal_total_exact_match"] is None
    assert missing["path_nominal_total_vs_edge_sum_exact_fraction_m"] is None
    assert missing["path_source_edge_sum_minus_chord_exact_fraction"] is None
    assert missing["path_calibrated_underflow_segment_indices"] is None
    assert missing["path_qc_warnings"] is None


# These exact binary64 source vertices give a three-edge route whose
# floating-point sum falls two ULPs below the direct endpoint chord.
# That is numerical roundoff, not a physically shorter-than-straight path.
CHORD_ROUNDOFF_GEOMETRY = {
    "vertices": [
        [0.0, 0.0, 0.0],
        [-112925.81117548913, -114908.5675512248, 36814.58032601017],
        [-863352.0625934367, -878510.8362058882, 281458.6278116675],
        [-5388552.085899986, -5483164.521206725, 1756704.5261155765],
        [8_000_000.0, 0.0, 0.0],
    ],
    "faces": [[0, 1, 4], [1, 2, 4], [2, 3, 4]],
    "meters_per_unit": 1.0,
    "calibration_method": "ruler",
    "calibration_evidence": "Synthetic numeric chord invariant, not verified coral geometry",
    "relative_scale_uncertainty": 0.02,
    "surface_path_vertex_pairs": [[0, 3], [0, 1]],
}


def test_impossible_subunit_detour_ratio_is_withheld_in_saved_workflows(
    client: TestClient,
) -> None:
    """A numerically shorter route must not masquerade as biological geometry."""
    direct_paths = mesh_edge_paths(
        points=[tuple(vertex) for vertex in CHORD_ROUNDOFF_GEOMETRY["vertices"]],
        faces=CHORD_ROUNDOFF_GEOMETRY["faces"],
        pairs=CHORD_ROUNDOFF_GEOMETRY["surface_path_vertex_pairs"],
        scale=1.0,
        scale_uncertainty=0.02,
    )
    assert direct_paths is not None
    affected, control = direct_paths
    assert affected["status"] == "connected"
    assert affected["path_vertex_indices"] == [0, 1, 2, 3]
    assert affected["length_m"] < affected["endpoint_chord_length_m"]
    assert Fraction(affected["path_source_edge_sum_minus_chord_exact_fraction"]) < 0
    assert "selected_mesh_route_stored_edge_sum_below_rounded_chord" in affected["path_qc_warnings"]
    assert affected["geometric_detour_ratio"] is None
    # A physically impossible negative result must not become a falsely exact
    # zero-excess measurement or zero-width calibration uncertainty interval.
    assert affected["geometric_excess_length_m"] is None
    assert affected["geometric_excess_scale_interval_m"] is None
    assert "endpoint_chord_exceeds_rounded_selected_route" in affected["path_qc_warnings"]
    assert control["path_vertex_indices"] == [0, 1]
    assert control["path_source_edge_sum_minus_chord_exact_fraction"] == "0"
    assert control["geometric_detour_ratio"] == 1.0
    assert control["geometric_excess_length_m"] == 0.0
    assert control["geometric_excess_scale_interval_m"] == [0.0, 0.0]
    assert "endpoint_chord_exceeds_rounded_selected_route" not in control["path_qc_warnings"]

    direct = measure_mesh_preview(**CHORD_ROUNDOFF_GEOMETRY)
    assert direct["surface_edge_paths"] == direct_paths
    assert direct["provenance"]["calibration_verified"] is False

    project_id = str(create_project(client, "Chord triangle inequality scientific QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/mesh-preview", json=CHORD_ROUNDOFF_GEOMETRY)
    assert standalone.status_code == 200, standalone.text
    measured = standalone.json()
    assert measured["surface_edge_paths"] == direct_paths

    graph = {
        "graph_id": "chord-roundoff-typed-v14",
        "name": "Provisional mesh path chord roundoff QC",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": CHORD_ROUNDOFF_GEOMETRY,
            },
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    digests: list[str] = []
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
        assert artifact["payload_json"] == measured
        digests.append(artifact["payload_sha256"])
    assert len(set(digests)) == 1
    assert len(digests[0]) == 64


# The exact sum of these *stored* binary64 edges is 1/33554432 source
# units smaller than the independently rounded endpoint chord, although
# Dijkstra's displayed cumulative total exactly equals that chord.
# It is a numerical ambiguity, not evidence for physically negative detour.
STORED_CHORD_DEFICIT_GEOMETRY = {
    "vertices": [
        [0.0, 0.0, 0.0],
        [188063144.80011293, 79404438.93980448, 43881400.37769399],
        [900000000.0, 380000000.0, 210000000.0],
        [0.0, 100000000.0, 300000000.0],
    ],
    "faces": [[0, 1, 3], [1, 2, 3]],
    "meters_per_unit": 1.0,
    "calibration_method": "ruler",
    "calibration_evidence": "Synthetic stored-edge/chord precision case, unverified",
    "relative_scale_uncertainty": 0.02,
    "surface_path_vertex_pairs": [[0, 2], [0, 1]],
}


def test_rounded_equal_route_with_impossible_exact_stored_chord_is_withheld(
    client: TestClient,
) -> None:
    """A rounded Dijkstra/chord equality must not conceal a stored-edge deficit."""
    geometry = STORED_CHORD_DEFICIT_GEOMETRY
    paths = mesh_edge_paths(
        points=[tuple(vertex) for vertex in geometry["vertices"]],
        faces=geometry["faces"],
        pairs=geometry["surface_path_vertex_pairs"],
        scale=1.0,
        scale_uncertainty=0.02,
    )
    assert paths is not None
    affected, control = paths
    assert affected["status"] == "connected"
    assert affected["path_vertex_indices"] == [0, 1, 2]
    assert affected["length_m"] == affected["endpoint_chord_length_m"]
    assert affected["path_source_edge_sum_minus_chord_exact_fraction"] == "-1/33554432"
    stored_chord_warning = "selected_mesh_route_stored_edge_sum_below_rounded_chord"
    assert stored_chord_warning in affected["path_qc_warnings"]
    assert affected["geometric_detour_ratio"] is None
    assert affected["geometric_excess_length_m"] is None
    assert affected["geometric_excess_scale_interval_m"] is None
    assert control["path_vertex_indices"] == [0, 1]
    assert control["path_source_edge_sum_minus_chord_exact_fraction"] == "0"
    assert control["geometric_detour_ratio"] == 1.0
    assert stored_chord_warning not in control["path_qc_warnings"]

    direct = measure_mesh_preview(**geometry)
    assert direct["surface_edge_paths"] == paths
    assert direct["provenance"]["calibration_verified"] is False
    project_id = str(create_project(client, "Stored chord precision audit")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=geometry)
    assert response.status_code == 200, response.text
    measured = response.json()
    assert measured["surface_edge_paths"] == paths
    assert measured["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "mesh-source-chord-exact-audit-v14",
        "name": "Source edge/chord exact-fraction scientific integrity",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "mesh",
                "node_type": "mesh_surface_preview",
                "parameters": geometry,
            },
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    hashes: list[str] = []
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
        assert artifact["payload_json"] == measured
        hashes.append(artifact["payload_sha256"])
    assert len(set(hashes)) == 1
    assert len(hashes[0]) == 64


# A positive 1e-170 source edge collapses to binary64 zero at 1e-155
# meters per unit. A larger adjacent triangle keeps total calibrated area
# representable for the complete mesh-preview and persisted workflow.
TINY_CALIBRATED_EDGE_GEOMETRY = {
    "vertices": [
        [0.0, 0.0, 0.0],
        [1e-170, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [1.0, 0.0, 0.0],
    ],
    "faces": [[0, 1, 2], [0, 2, 3]],
    "meters_per_unit": 1e-155,
    "calibration_method": "ruler",
    "calibration_evidence": "Synthetic underflow, not a measured coral scale",
    "relative_scale_uncertainty": 0.05,
    "surface_path_vertex_pairs": [[0, 1], [0, 2]],
}


def test_positive_source_edge_underflow_withholds_false_zero_intervals(
    client: TestClient,
) -> None:
    """Calibrated zero from underflow is not a verified zero-length segment."""
    geometry = TINY_CALIBRATED_EDGE_GEOMETRY
    paths = mesh_edge_paths(
        points=[tuple(vertex) for vertex in geometry["vertices"]],
        faces=geometry["faces"],
        pairs=geometry["surface_path_vertex_pairs"],
        scale=1e-155,
        scale_uncertainty=0.05,
    )
    assert paths is not None
    underflowed, control = paths
    assert underflowed["status"] == "connected"
    assert underflowed["path_vertex_indices"] == [0, 1]
    assert underflowed["length_m"] == 0.0
    assert underflowed["endpoint_chord_length_m"] == 0.0
    assert underflowed["path_edge_lengths_m"] == [0.0]
    assert underflowed["path_calibrated_underflow_segment_indices"] == [0]
    # Loss on conversion to calibrated meters is not the same as a positive
    # calibrated segment lost during accumulation of a large preceding total.
    assert underflowed["path_cumulative_lost_positive_segment_indices"] == []
    assert underflowed["length_scale_interval_m"] is None
    assert underflowed["endpoint_chord_scale_interval_m"] is None
    assert underflowed["path_edge_length_scale_intervals_m"] == [None]
    assert underflowed["path_cumulative_length_scale_intervals_m"] == [[0.0, 0.0], None]
    assert underflowed["scale_uncertainty_m"] is None
    assert underflowed["endpoint_chord_scale_uncertainty_m"] is None
    assert "calibrated_path_length_underflow" in underflowed["path_qc_warnings"]
    assert "calibrated_path_segment_underflow" in underflowed["path_qc_warnings"]
    assert "path_scale_interval_below_numeric_resolution" in underflowed["path_qc_warnings"]
    assert control["status"] == "connected"
    assert control["path_vertex_indices"] == [0, 2]
    assert control["path_calibrated_underflow_segment_indices"] == []
    assert control["length_m"] == 1e-155
    assert control["length_scale_interval_m"] == [1e-155 * 0.95, 1e-155 * 1.05]
    assert control["path_edge_length_scale_intervals_m"] == [[1e-155 * 0.95, 1e-155 * 1.05]]
    assert "calibrated_path_length_underflow" not in control["path_qc_warnings"]

    without_uncertainty = mesh_edge_paths(
        points=[tuple(vertex) for vertex in geometry["vertices"]],
        faces=geometry["faces"],
        pairs=geometry["surface_path_vertex_pairs"],
        scale=1e-155,
        scale_uncertainty=None,
    )
    assert without_uncertainty is not None
    assert without_uncertainty[0]["path_calibrated_underflow_segment_indices"] == [0]
    assert without_uncertainty[0]["path_edge_length_scale_intervals_m"] is None
    assert "calibrated_path_segment_underflow" in without_uncertainty[0]["path_qc_warnings"]
    assert without_uncertainty[1]["path_calibrated_underflow_segment_indices"] == []

    direct = measure_mesh_preview(**geometry)
    assert direct["surface_edge_paths"] == paths
    assert direct["provenance"]["calibration_verified"] is False
    project_id = str(create_project(client, "Calibrated edge underflow evidence")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=geometry)
    assert response.status_code == 200, response.text
    measured = response.json()
    assert measured["surface_edge_paths"] == paths

    graph = {
        "graph_id": "mesh-underflow-scale-interval-v14",
        "name": "Withhold false zero intervals from provisional calibrated paths",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": geometry},
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
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    digests: list[str] = []
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
        assert artifact["payload_json"] == measured
        digests.append(artifact["payload_sha256"])
    assert len(set(digests)) == 1
    assert len(digests[0]) == 64


def test_genuine_zero_source_edge_does_not_report_calibration_underflow() -> None:
    """Exact source-frame zero must not be mistaken for a numerically lost edge."""
    result = mesh_edge_paths(
        points=[(0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[[0, 1, 2]],
        pairs=[[0, 1]],
        scale=1e-155,
        scale_uncertainty=0.05,
    )
    assert result is not None
    route = result[0]
    assert route["status"] == "connected"
    assert route["path_edge_lengths_m"] == [0.0]
    assert route["path_calibrated_underflow_segment_indices"] == []
    assert route["path_edge_length_scale_intervals_m"] == [[0.0, 0.0]]
    assert "zero_length_edge_on_path" in route["path_qc_warnings"]
    assert "calibrated_path_segment_underflow" not in route["path_qc_warnings"]

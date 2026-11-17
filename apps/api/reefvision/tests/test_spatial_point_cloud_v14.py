"""Standalone and saved Workflow Builder regression for 1.4 point-cloud preview."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_point_cloud_v14 import PointCloudPreviewRequest
from reefvision.services.spatial_point_cloud_v14 import (
    measure_point_cloud_preview,
    parse_ascii_ply_points,
)
from reefvision.tests.test_annotations import create_project

PLY = (
    "ply\nformat ascii 1.0\nelement vertex 3\n"
    "property float z\nproperty float x\nproperty float y\nend_header\n"
    "0 0 0\n0 2 0\n0 0 3\n"
)
PARAMS = {
    "ply_text": PLY,
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unreviewed ruler",
    "relative_scale_uncertainty": 0.1,
    "specimen_id": "coral-16",
    "observation_id": "survey:2026-10-24",
    "observed_at_utc": "2026-10-24T10:30:00-05:00",
    "coordinate_frame_id": "transect-7",
}


def test_ply_parser_and_geometry_uncertainty() -> None:
    points = parse_ascii_ply_points(PLY)
    assert points == [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]
    result = measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unreviewed ruler",
        relative_scale_uncertainty=0.1,
    )
    assert result["axis_aligned_dimensions_m"] == pytest.approx([0.02, 0.03, 0])
    assert result["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx([0.002, 0.003, 0])
    assert result["surface_area_m2"] is None
    assert result["branch_length_m"] is None
    assert result["provenance"]["calibration_verified"] is False
    assert result["preview_point_indices"] == [0, 1, 2]
    assert result["preview_points_in_source_frame_m"][1] == pytest.approx([0.02, 0.0, 0.0])


@pytest.mark.parametrize(
    "bad",
    [
        PLY.replace("ascii", "binary_little_endian"),
        PLY.replace("element vertex 3", "element vertex 3000"),
        PLY.replace("end_header", "element face 0\nend_header"),
        PLY.replace("0 2 0", "nan 2 0"),
        PLY.replace("0 2 0", "0 2 1e12"),
        PLY.replace("property float y", "property float x"),
    ],
)
def test_bad_ply_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        measure_point_cloud_preview(
            points=parse_ascii_ply_points(bad),
            meters_per_unit=0.01,
            calibration_method="ruler",
            calibration_evidence="Unreviewed ruler",
        )


@pytest.mark.parametrize("blank", [" ", " \t\n "])
def test_blank_point_cloud_calibration_evidence_rejected_across_entrypoints(
    client: TestClient, blank: str
) -> None:
    invalid = {**PARAMS, "calibration_evidence": blank}
    with pytest.raises(PydanticValidationError, match="cannot be blank"):
        PointCloudPreviewRequest.model_validate(invalid)
    with pytest.raises(ValueError, match="Calibration evidence is required"):
        measure_point_cloud_preview(
            points=[[0.0, 0.0, 0.0]],
            meters_per_unit=0.01,
            calibration_method="ruler",
            calibration_evidence=blank,
        )

    project_id = str(create_project(client, "Point cloud calibration audit")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=invalid)
    assert standalone.status_code == 422, standalone.text

    graph = {
        "graph_id": "point-cloud-blank-calibration-v14",
        "name": "Reject unreviewable point-cloud calibration",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": invalid},
        ],
        "edges": [
            {
                "edge_id": "project-cloud",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "cloud",
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
        artifact["data_type"] == "point_cloud_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )


def test_standalone_and_saved_workflow_parity(client: TestClient) -> None:
    project_id = str(create_project(client, "Point cloud")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=PARAMS)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["provenance"]["source_format"] == "ply_ascii_point_cloud"
    assert expected["provenance"]["specimen_id"] == "coral-16"
    assert expected["provenance"]["observation_id"] == "survey:2026-10-24"
    assert expected["provenance"]["observed_at_utc"] == "2026-10-24T15:30:00Z"
    assert expected["provenance"]["coordinate_frame_id"] == "transect-7"
    assert expected["provenance"]["coordinate_registration_verified"] is False
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert expected["provenance"]["observation_metadata_verified"] is False
    assert (
        client.post(
            f"{base}/spatial/point-cloud-preview",
            json={**PARAMS, "points": [[0, 0, 0]]},
        ).status_code
        == 422
    )
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    node = next(n for n in registry.json() if n["node_type"] == "point_cloud_preview")
    assert node["executable"] is True
    assert node["output_ports"][0]["accepted_types"] == ["point_cloud_measurement_preview"]
    assert node["optional_parameters"]["specimen_id"] is None
    assert node["optional_parameters"]["observation_id"] is None
    assert node["optional_parameters"]["observed_at_utc"] is None
    assert node["optional_parameters"]["coordinate_frame_id"] is None
    graph = {
        "graph_id": "point-cloud-v14",
        "name": "Point cloud extents",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": PARAMS},
        ],
        "edges": [
            {
                "edge_id": "project-cloud",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "cloud",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    assert saved.json()["graph_json"]["nodes"][1]["parameters"]["ply_text"] == PLY
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
        a for a in detail.json()["artifacts"] if a["data_type"] == "point_cloud_measurement_preview"
    )
    assert (
        artifact["payload_json"]["axis_aligned_dimensions_m"]
        == expected["axis_aligned_dimensions_m"]
    )
    for key in ("axis_aligned_min_in_source_frame_m", "axis_aligned_max_in_source_frame_m"):
        assert artifact["payload_json"][key] == expected[key]
    for key in (
        "axis_aligned_min_in_source_frame_scale_interval_m",
        "axis_aligned_max_in_source_frame_scale_interval_m",
        "arithmetic_centroid_in_source_frame_scale_interval_m",
    ):
        assert artifact["payload_json"][key] == expected[key]
    assert artifact["payload_json"]["provenance"] == expected["provenance"]
    for key in (
        "preview_point_indices",
        "preview_points_in_source_frame_m",
        "preview_omitted_axis_extrema",
        "preview_axis_extrema_covered",
        "qc_warnings",
    ):
        assert artifact["payload_json"][key] == expected[key]
    assert artifact["payload_json"]["surface_area_m2"] is None
    assert artifact["payload_json"]["project_id"] == project_id
    assert len(artifact["payload_sha256"]) == 64


@pytest.mark.parametrize(
    "invalid_frame",
    ["", "transect with spaces", "survey/1", "x" * 129],
)
def test_point_cloud_rejects_invalid_coordinate_frame_id(
    client: TestClient, invalid_frame: str
) -> None:
    project_id = str(create_project(client, "Reject invalid source frame")["id"])
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/point-cloud-preview",
        json={**PARAMS, "coordinate_frame_id": invalid_frame},
    )
    assert response.status_code == 422, response.text


def test_bounds_preserve_negative_source_coordinates() -> None:
    result = measure_point_cloud_preview(
        points=[[-2, -3, -4], [1, 2, 3]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified ruler",
    )
    assert result["axis_aligned_min_in_source_frame_m"] == pytest.approx([-0.02, -0.03, -0.04])
    assert result["axis_aligned_max_in_source_frame_m"] == pytest.approx([0.01, 0.02, 0.03])
    assert result["axis_aligned_dimensions_m"] == pytest.approx([0.03, 0.05, 0.07])
    assert result["arithmetic_centroid_in_source_frame_scale_interval_m"] is None
    assert result["measurement_status"] == "caller_supplied_unverified"


def test_centroid_scale_intervals_preserve_signed_source_frame() -> None:
    result = measure_point_cloud_preview(
        points=[[-2, 2, 0], [0, 4, 0]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified ruler",
        relative_scale_uncertainty=0.1,
    )
    assert result["arithmetic_centroid_in_source_frame_m"] == pytest.approx([-0.01, 0.03, 0.0])
    intervals = result["arithmetic_centroid_in_source_frame_scale_interval_m"]
    assert intervals is not None
    expected_intervals = [[-0.011, -0.009], [0.027, 0.033], [0, 0]]
    for actual, expected in zip(intervals, expected_intervals, strict=True):
        assert actual == pytest.approx(expected)
    assert result["provenance"]["coordinate_registration_verified"] is False


def test_preview_sampling_keeps_original_indices_and_provisional_status() -> None:
    points = [[float(index), -float(index), 0.0] for index in range(2000)]
    kwargs = {
        "points": points,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified field ruler",
        "relative_scale_uncertainty": 0.1,
        "point_index_pairs": [[1000, 1999]],
    }
    first = measure_point_cloud_preview(**kwargs)
    second = measure_point_cloud_preview(**kwargs)
    indices = first["preview_point_indices"]
    sample = first["preview_points_in_source_frame_m"]
    assert len(indices) == len(sample) == 512
    assert indices[0] == 0
    assert indices[-1] == 1999
    assert indices == sorted(set(indices))
    assert 1000 not in indices  # Selected measurement endpoints need not be displayed.
    assert first["axis_aligned_dimensions_m"] == pytest.approx([19.99, 19.99, 0])
    centroid = first["arithmetic_centroid_in_source_frame_m"]
    assert centroid == pytest.approx([9.995, -9.995, 0])
    assert sample == [[value * 0.01 for value in points[i]] for i in indices]
    assert sample == second["preview_points_in_source_frame_m"]
    chord = first["selected_point_chords"][0]
    assert chord["point_indices"] == [1000, 1999]
    assert chord["chord_distance_m"] == pytest.approx(14.127993)
    assert first["surface_area_m2"] is None
    assert first["branch_length_m"] is None
    assert first["provenance"]["calibration_verified"] is False
    assert first["measurement_status"] == "caller_supplied_unverified"


def test_single_point_preview_preserves_zero_extents_without_biological_inference() -> None:
    result = measure_point_cloud_preview(
        points=[[2.0, -1.0, 3.0]],
        meters_per_unit=0.1,
        calibration_method="ruler",
        calibration_evidence="Unverified ruler",
    )
    assert result["preview_point_indices"] == [0]
    assert result["preview_points_in_source_frame_m"][0] == pytest.approx([0.2, -0.1, 0.3])
    assert result["axis_aligned_dimensions_m"] == [0.0, 0.0, 0.0]
    assert result["surface_area_m2"] is None
    assert result["branch_length_m"] is None
    assert result["provenance"]["calibration_verified"] is False


def test_sampling_threshold_preserves_full_geometry_and_provisional_status() -> None:
    for count in (512, 513):
        result = measure_point_cloud_preview(
            points=[[float(index), 0.0, 0.0] for index in range(count)],
            meters_per_unit=0.01,
            calibration_method="ruler",
            calibration_evidence="Unreviewed scale bar",
            relative_scale_uncertainty=0.1,
        )
        indices = result["preview_point_indices"]
        assert len(indices) == 512
        assert indices[0] == 0
        assert indices[-1] == count - 1
        assert len(set(indices)) == 512
        assert result["point_count"] == count
        expected_extent = (count - 1) * 0.01
        assert result["axis_aligned_dimensions_m"][0] == pytest.approx(expected_extent)
        uncertainty = result["axis_aligned_dimension_scale_uncertainty_m"]
        assert uncertainty[0] == pytest.approx(expected_extent * 0.1)
        assert result["surface_area_m2"] is None
        assert result["branch_length_m"] is None
        assert result["provenance"]["calibration_verified"] is False


def test_hidden_extreme_is_reported_without_changing_full_cloud_measurements() -> None:
    points = [[float(index), 0.0, 0.0] for index in range(513)]
    points[511] = [1_000_000.0, 0.0, 0.0]
    result = measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified field scale",
        relative_scale_uncertainty=0.1,
    )
    assert 511 not in result["preview_point_indices"]
    assert result["preview_axis_extrema_covered"] is False
    assert result["preview_omitted_axis_extrema"] == ["x_max"]
    assert "preview_omits_axis_extrema" in result["qc_warnings"]
    assert result["axis_aligned_dimensions_m"] == pytest.approx([10000.0, 0, 0])
    assert result["axis_aligned_dimension_scale_uncertainty_m"] == pytest.approx([1000.0, 0, 0])
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["surface_area_m2"] is None
    assert result["branch_length_m"] is None


def test_hidden_extreme_standalone_and_saved_workflow_parity(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Point cloud hidden outlier")["id"])
    base = f"/api/v1/projects/{project_id}"
    points = [[float(index), 0.0, 0.0] for index in range(513)]
    points[511] = [1_000_000.0, 0.0, 0.0]
    parameters = {
        "points": points,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified scale",
    }
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=parameters)
    assert standalone.status_code == 200, standalone.text
    graph = {
        "graph_id": "point-cloud-hidden-extreme-v14",
        "name": "Hidden source extent",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "cloud",
                "node_type": "point_cloud_preview",
                "parameters": parameters,
            },
        ],
        "edges": [
            {
                "edge_id": "project-cloud",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "cloud",
                "target_port_id": "project",
            }
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
        a for a in detail.json()["artifacts"] if a["data_type"] == "point_cloud_measurement_preview"
    )
    expected = standalone.json()
    for key in (
        "preview_point_indices",
        "preview_omitted_axis_extrema",
        "preview_axis_extrema_covered",
        "qc_warnings",
        "axis_aligned_dimensions_m",
        "axis_aligned_dimension_scale_uncertainty_m",
        "measurement_status",
        "provenance",
    ):
        assert artifact["payload_json"][key] == expected[key]
    assert expected["preview_omitted_axis_extrema"] == ["x_max"]
    assert artifact["payload_json"]["surface_area_m2"] is None
    assert len(artifact["payload_sha256"]) == 64


@pytest.mark.parametrize(
    "invalid",
    [
        {"specimen_id": "invalid id"},
        {"specimen_id": ""},
        {"observation_id": "invalid/observation"},
        {"observation_id": " "},
        {"observed_at_utc": "2026-10-24T10:30:00"},
    ],
)
def test_point_cloud_rejects_unreviewable_identity_and_naive_time(
    client: TestClient, invalid: dict[str, str]
) -> None:
    project_id = str(create_project(client, "Point cloud metadata validation")["id"])
    response = client.post(
        f"/api/v1/projects/{project_id}/spatial/point-cloud-preview",
        json={**PARAMS, **invalid},
    )
    assert response.status_code == 422, response.text


def test_point_cloud_observation_metadata_does_not_change_geometry_identity(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Point cloud provenance")["id"])
    endpoint = f"/api/v1/projects/{project_id}/spatial/point-cloud-preview"
    original = client.post(endpoint, json=PARAMS)
    alternate = client.post(
        endpoint,
        json={
            **PARAMS,
            "specimen_id": "coral-20",
            "observation_id": "survey:2026-10-25",
            "observed_at_utc": "2026-10-25T15:30:00Z",
        },
    )
    assert original.status_code == 200, original.text
    assert alternate.status_code == 200, alternate.text
    first = original.json()
    second = alternate.json()
    assert first["provenance"]["geometry_sha256"] == second["provenance"]["geometry_sha256"]
    assert (
        first["provenance"]["ordered_geometry_sha256"]
        == (second["provenance"]["ordered_geometry_sha256"])
    )
    assert first["provenance"]["specimen_id"] != second["provenance"]["specimen_id"]
    assert second["provenance"]["specimen_identity_verified"] is False
    assert second["provenance"]["observation_metadata_verified"] is False
    assert second["measurement_status"] == "caller_supplied_unverified"


@pytest.mark.parametrize(
    "bad_ply",
    [
        PLY.replace("0 2 0", "0 ٢ 0"),
        PLY.replace("end_header", "comment temperature °C\nend_header"),
        PLY.replace("0 2 0", "0 2 0\u00a0"),
    ],
    ids=["unicode_digit", "unicode_comment", "unicode_whitespace"],
)
def test_non_ascii_ply_rejected_without_standalone_or_workflow_artifact(
    client: TestClient, bad_ply: str
) -> None:
    """ASCII PLY is byte-restricted even when Unicode parses as a number or whitespace."""
    with pytest.raises(ValueError, match="ASCII text only"):
        parse_ascii_ply_points(bad_ply)
    project_id = str(create_project(client, "Non-ASCII point-cloud rejection")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {**PARAMS, "ply_text": bad_ply}
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 400, standalone.text

    graph = {
        "graph_id": "reject-unicode-ply-v14",
        "name": "Fail closed on non-ASCII PLY",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-cloud",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "cloud",
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
        artifact["data_type"] == "point_cloud_measurement_preview"
        for artifact in detail.json()["artifacts"]
    )


def test_ascii_ply_comment_remains_supported() -> None:
    with_comment = PLY.replace("end_header", "comment temperature C\nend_header")
    assert parse_ascii_ply_points(with_comment) == parse_ascii_ply_points(PLY)


@pytest.mark.parametrize("as_ply", [False, True])
def test_duplicate_coordinate_centroid_qc_direct_api_and_persisted_workflow(
    client: TestClient, as_ply: bool
) -> None:
    """Repeated scan rows affect a row-weighted centroid, not verified biology."""
    points = [[-1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0]]
    direct = measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.1,
        calibration_method="ruler",
        calibration_evidence="Unverified acquisition scale",
        relative_scale_uncertainty=0.1,
    )
    assert direct["duplicate_point_row_count"] == 1
    assert direct["duplicate_point_row_fraction"] == pytest.approx(0.25)
    assert direct["preview_unique_coordinate_count"] == 3
    assert direct["preview_unique_coordinate_coverage_fraction"] == pytest.approx(1.0)
    assert "preview_omits_unique_coordinate_loci" not in direct["qc_warnings"]
    assert direct["unique_point_count"] == 3
    assert direct["maximum_coordinate_multiplicity"] == 2
    assert direct["arithmetic_centroid_in_source_frame_m"] == pytest.approx([-0.025, 0.05, 0.0])
    assert direct["unique_coordinate_centroid_in_source_frame_m"] == pytest.approx(
        [0.0, 0.2 / 3, 0.0]
    )
    separation = direct["row_vs_unique_coordinate_centroid_separation_m"]
    assert separation == pytest.approx((0.025**2 + (1 / 60) ** 2) ** 0.5)
    separation_interval = direct["row_vs_unique_coordinate_centroid_separation_scale_interval_m"]
    assert separation_interval == pytest.approx([0.9 * separation, 1.1 * separation])
    assert "duplicate_points_present" in direct["qc_warnings"]
    assert "nonuniform_duplicate_coordinates_can_bias_row_centroid" in direct["qc_warnings"]
    assert direct["branch_length_m"] is None
    assert direct["surface_area_m2"] is None
    assert direct["measurement_status"] == "caller_supplied_unverified"

    # Exact unique loci are stable under repeated scan rows and reordering.
    # Full geometry hashes must still bind the acquisition multiplicities.
    repeated_rows = measure_point_cloud_preview(
        points=[*points, points[0]],
        meters_per_unit=0.1,
        calibration_method="ruler",
        calibration_evidence="Unverified acquisition scale",
        relative_scale_uncertainty=0.1,
    )
    reordered_rows = measure_point_cloud_preview(
        points=list(reversed(points)),
        meters_per_unit=0.1,
        calibration_method="ruler",
        calibration_evidence="Unverified acquisition scale",
        relative_scale_uncertainty=0.1,
    )
    unique_sha = direct["provenance"]["unique_coordinate_geometry_sha256"]
    assert repeated_rows["provenance"]["unique_coordinate_geometry_sha256"] == unique_sha
    assert reordered_rows["provenance"]["unique_coordinate_geometry_sha256"] == unique_sha
    assert repeated_rows["duplicate_point_row_fraction"] == pytest.approx(0.4)
    assert reordered_rows["duplicate_point_row_fraction"] == pytest.approx(0.25)
    assert repeated_rows["provenance"]["geometry_sha256"] != direct["provenance"]["geometry_sha256"]
    assert (
        reordered_rows["provenance"]["geometry_sha256"] == direct["provenance"]["geometry_sha256"]
    )
    assert (
        reordered_rows["provenance"]["ordered_geometry_sha256"]
        != direct["provenance"]["ordered_geometry_sha256"]
    )
    assert (
        repeated_rows["unique_coordinate_centroid_in_source_frame_m"]
        == direct["unique_coordinate_centroid_in_source_frame_m"]
    )
    assert (
        repeated_rows["arithmetic_centroid_in_source_frame_m"]
        != direct["arithmetic_centroid_in_source_frame_m"]
    )

    # Uniform duplicate multiplicities cannot change a mathematical centroid.
    balanced = measure_point_cloud_preview(
        points=[[-1.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
        meters_per_unit=0.1,
        calibration_method="ruler",
        calibration_evidence="Unverified acquisition scale",
        relative_scale_uncertainty=0.1,
    )
    assert balanced["row_vs_unique_coordinate_centroid_separation_m"] == 0.0
    assert balanced["duplicate_point_row_fraction"] == pytest.approx(0.5)
    nonuniform_warning = "nonuniform_duplicate_coordinates_can_bias_row_centroid"
    assert nonuniform_warning not in balanced["qc_warnings"]

    project_id = str(create_project(client, "Repeated scan coordinates")["id"])
    base = f"/api/v1/projects/{project_id}"
    parameters: dict = {
        "meters_per_unit": 0.1,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified acquisition scale",
        "relative_scale_uncertainty": 0.1,
    }
    if as_ply:
        parameters["ply_text"] = (
            "ply\nformat ascii 1.0\nelement vertex 4\n"
            "property float x\nproperty float y\nproperty float z\nend_header\n"
            "-1 0 0\n-1 0 0\n1 0 0\n0 2 0\n"
        )
    else:
        parameters["points"] = points
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=parameters)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    fields = (
        "duplicate_point_row_count",
        "duplicate_point_row_fraction",
        "preview_unique_coordinate_count",
        "preview_unique_coordinate_coverage_fraction",
        "unique_point_count",
        "maximum_coordinate_multiplicity",
        "arithmetic_centroid_in_source_frame_m",
        "unique_coordinate_centroid_in_source_frame_m",
        "unique_coordinate_centroid_in_source_frame_scale_interval_m",
        "row_vs_unique_coordinate_centroid_separation_m",
        "row_vs_unique_coordinate_centroid_separation_scale_interval_m",
        "qc_warnings",
        "measurement_status",
        "provenance",
    )
    for key in fields[:-1]:
        assert expected[key] == direct[key]
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["unique_coordinate_geometry_sha256"] == unique_sha

    graph = {
        "graph_id": "duplicate-point-centroid-v14",
        "name": "Repeated scan coordinate sensitivity",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": parameters},
        ],
        "edges": [
            {
                "edge_id": "project-cloud",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "cloud",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    for _ in range(2):
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
            a
            for a in detail.json()["artifacts"]
            if a["data_type"] == "point_cloud_measurement_preview"
        )
        for key in fields:
            assert artifact["payload_json"][key] == expected[key]
        assert artifact["payload_json"]["surface_area_m2"] is None
        assert artifact["payload_json"]["project_id"] == project_id


@pytest.mark.parametrize("as_ply", [False, True])
def test_bounded_preview_unique_locus_coverage_direct_api_and_saved_workflow(
    client: TestClient, as_ply: bool
) -> None:
    """A 512-point display can hide source loci despite preserving all extrema."""
    points = [[float(i), 0.0, 0.0] for i in range(513)]
    calibration = {
        "meters_per_unit": 0.001,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified scan scale",
    }
    direct = measure_point_cloud_preview(points=points, **calibration)
    assert direct["unique_point_count"] == 513
    assert direct["preview_unique_coordinate_count"] == 512
    assert direct["preview_unique_coordinate_coverage_fraction"] == pytest.approx(512 / 513)
    assert direct["preview_axis_extrema_covered"] is True
    assert "preview_omits_axis_extrema" not in direct["qc_warnings"]
    assert "preview_omits_unique_coordinate_loci" in direct["qc_warnings"]
    assert direct["provenance"]["calibration_verified"] is False
    assert direct["branch_length_m"] is None

    parameters = {**calibration}
    if as_ply:
        parameters["ply_text"] = (
            "ply\nformat ascii 1.0\nelement vertex 513\n"
            "property float x\nproperty float y\nproperty float z\nend_header\n"
            + "".join(f"{i} 0 0\n" for i in range(513))
        )
    else:
        parameters["points"] = points
    project_id = str(create_project(client, "Distinct XYZ preview coverage")["id"])
    base = f"/api/v1/projects/{project_id}"
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=parameters)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    fields = (
        "point_count",
        "unique_point_count",
        "preview_unique_coordinate_count",
        "preview_unique_coordinate_coverage_fraction",
        "preview_point_indices",
        "preview_axis_extrema_covered",
        "qc_warnings",
        "measurement_status",
        "provenance",
    )
    for field in fields[:-1]:
        assert expected[field] == direct[field]
    assert expected["provenance"]["geometry_sha256"] == direct["provenance"]["geometry_sha256"]
    assert expected["provenance"]["calibration_verified"] is False

    graph = {
        "graph_id": "distinct-point-preview-v14",
        "name": "Audit missing distinct XYZ display loci",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "cloud", "node_type": "point_cloud_preview", "parameters": parameters},
        ],
        "edges": [
            {
                "edge_id": "project-cloud",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "cloud",
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
            if item["data_type"] == "point_cloud_measurement_preview"
        )
        for field in fields:
            assert artifact["payload_json"][field] == expected[field]
        assert artifact["payload_json"]["branch_length_m"] is None
        assert artifact["payload_json"]["project_id"] == project_id


def test_duplicate_rich_preview_does_not_fake_missing_distinct_loci() -> None:
    """Hundreds of duplicated rows can still display every unique XYZ location."""
    points = [[0.0, 0.0, 0.0]] * 300 + [[1.0, 0.0, 0.0]] * 300
    preview = measure_point_cloud_preview(
        points=points,
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified scan scale",
    )
    assert preview["point_count"] == 600
    assert preview["unique_point_count"] == 2
    assert preview["preview_unique_coordinate_count"] == 2
    assert preview["preview_unique_coordinate_coverage_fraction"] == pytest.approx(1.0)
    assert preview["duplicate_point_row_fraction"] == pytest.approx(598 / 600)
    assert "preview_omits_unique_coordinate_loci" not in preview["qc_warnings"]
    assert preview["provenance"]["calibration_verified"] is False

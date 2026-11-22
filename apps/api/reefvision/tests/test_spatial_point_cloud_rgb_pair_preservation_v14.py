"""Guard colored PLY observation retention without biological interpretation."""

from __future__ import annotations

import hashlib
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_point_cloud_v14 import measure_point_cloud_preview
from reefvision.tests.test_annotations import create_project

CALIBRATION = {
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Unverified field scale",
    "relative_scale_uncertainty": 0.1,
}
PLY_HEADER = (
    "ply\nformat ascii 1.0\nelement vertex {count}\n"
    "property float x\nproperty float y\nproperty float z\n"
    "property uchar red\nproperty uchar green\n"
    "property uchar blue\nend_header\n"
)


def _colored_ply(rows: list[str]) -> str:
    return PLY_HEADER.format(count=len(rows)) + "\n".join(rows) + "\n"


def test_ordered_rgb_acquisition_fingerprint_catches_hidden_observations(
    client: TestClient,
) -> None:
    """Omitted RGB rows change full acquisition evidence, not preview evidence."""
    points = [[0, 0, 0], [1, 0, 0]]
    colors = [[10, 20, 30], [40, 50, 60]]
    direct = measure_point_cloud_preview(
        points=points, point_colors=colors, **CALIBRATION
    )
    expected_hash = hashlib.sha256(
        b"[[0.0,0.0,0.0,10,20,30],[1.0,0.0,0.0,40,50,60]]"
    ).hexdigest()
    assert direct["provenance"]["source_ordered_xyz_rgb_sha256"] == expected_hash
    changed = measure_point_cloud_preview(
        points=points, point_colors=[[10, 20, 31], [40, 50, 60]], **CALIBRATION
    )
    assert changed["provenance"]["geometry_sha256"] == direct["provenance"]["geometry_sha256"]
    assert changed["provenance"]["source_ordered_xyz_rgb_sha256"] != expected_hash
    uncolored = measure_point_cloud_preview(points=points, **CALIBRATION)
    assert uncolored["provenance"]["source_ordered_xyz_rgb_sha256"] is None

    pid = str(create_project(client, "Off-preview RGB acquisition evidence")["id"])
    endpoint = f"/api/v1/projects/{pid}/spatial/point-cloud-preview"
    sampled = {i * 599 // 511 for i in range(512)}
    hidden_index = next(i for i in range(600) if i not in sampled)
    rows = [f"{i} 0 0 10 20 30" for i in range(600)]
    changed_rows = rows.copy()
    changed_rows[hidden_index] = f"{hidden_index} 0 0 11 20 30"
    first = client.post(endpoint, json={**CALIBRATION, "ply_text": _colored_ply(rows)})
    second = client.post(
        endpoint, json={**CALIBRATION, "ply_text": _colored_ply(changed_rows)}
    )
    assert first.status_code == second.status_code == 200
    before, after = first.json(), second.json()
    assert hidden_index not in before["preview_point_indices"]
    assert before["preview_point_indices"] == after["preview_point_indices"]
    assert before["provenance"]["ordered_geometry_sha256"] == (
        after["provenance"]["ordered_geometry_sha256"]
    )
    assert before["provenance"]["source_ordered_xyz_rgb_sha256"] != (
        after["provenance"]["source_ordered_xyz_rgb_sha256"]
    )
    assert before["preview_rgb_variant_support"]["preview_sample_xyz_rgb_sha256"] == (
        after["preview_rgb_variant_support"]["preview_sample_xyz_rgb_sha256"]
    )
    assert before["provenance"]["calibration_verified"] is False
    assert before["provenance"]["specimen_identity_verified"] is False



def test_ply_channel_reordering_preserves_semantic_rgb_hash_and_saved_workflow(
    client: TestClient,
) -> None:
    """Exact PLY bytes differ, but parsed acquisition-row RGB evidence is stable."""
    pid = str(create_project(client, "Canonical point-cloud RGB evidence")["id"])
    base = f"/api/v1/projects/{pid}"
    canonical = _colored_ply(["0 0 0 10 20 30", "1 0 0 40 50 60"])
    reordered = "\n".join(
        [
            "ply",
            "format ascii 1.0",
            "comment independent exporter uses a different property order",
            "element vertex 2",
            "property uchar blue",
            "property double z",
            "property uchar red",
            "property float x",
            "property uchar green",
            "property double y",
            "end_header",
            "30 0 10 0 20 0",
            "60 0 40 1 50 0",
            "",
        ]
    )
    original_response = client.post(
        f"{base}/spatial/point-cloud-preview",
        json={**CALIBRATION, "ply_text": canonical},
    )
    reordered_params = {**CALIBRATION, "ply_text": reordered}
    reordered_response = client.post(
        f"{base}/spatial/point-cloud-preview", json=reordered_params
    )
    assert original_response.status_code == 200, original_response.text
    assert reordered_response.status_code == 200, reordered_response.text
    original = original_response.json()
    normalized = reordered_response.json()
    expected = hashlib.sha256(
        b"[[0.0,0.0,0.0,10,20,30],[1.0,0.0,0.0,40,50,60]]"
    ).hexdigest()
    for artifact in (original, normalized):
        assert artifact["provenance"]["source_ordered_xyz_rgb_sha256"] == expected
        assert artifact["provenance"]["source_ordered_xyz_rgb_canonicalization"] == (
            "ordered_normalized_float64_xyz_uint8_rgb_compact_json_utf8_v1"
        )
        assert artifact["preview_point_colors_rgb_uint8"] == [
            [10, 20, 30],
            [40, 50, 60],
        ]
        assert artifact["provenance"]["calibration_verified"] is False
        assert artifact["provenance"]["specimen_identity_verified"] is False
    assert original["provenance"]["source_payload_sha256"] != (
        normalized["provenance"]["source_payload_sha256"]
    )
    assert original["provenance"]["ordered_geometry_sha256"] == (
        normalized["provenance"]["ordered_geometry_sha256"]
    )
    assert original["preview_sample_geometry_sha256"] == (
        normalized["preview_sample_geometry_sha256"]
    )
    assert original["preview_rgb_variant_support"] == normalized["preview_rgb_variant_support"]

    graph = {
        "graph_id": "canonical-point-cloud-rgb-v14",
        "name": "Imported PLY semantic fingerprint QC",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {
                "node_id": "c",
                "node_type": "point_cloud_preview",
                "parameters": reordered_params,
            },
        ],
        "edges": [
            {
                "edge_id": "e",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "c",
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
    for _ in range(2):
        run = client.post(
            f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]}
        )
        assert run.status_code == 202, run.text
        app = cast(FastAPI, client.app)
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
        assert artifact["payload_json"] == normalized
        digests.append(artifact["payload_sha256"])
    assert len(set(digests)) == 1


def test_rgb_pair_preservation_standalone_and_two_saved_graph_replays(
    client: TestClient,
) -> None:
    """A rare observed color must survive without claiming coral condition."""
    pid = str(create_project(client, "Color observation completeness")["id"])
    base = f"/api/v1/projects/{pid}"
    default_indices = {i * 599 // 511 for i in range(512)}
    rare_index = next(i for i in range(1, 300) if i not in default_indices)
    rows = []
    for i in range(600):
        rgb = "80 90 100" if i == rare_index else ("10 20 30" if i < 300 else "40 50 60")
        rows.append(f"{0 if i < 300 else 1} 0 0 {rgb}")
    params = {**CALIBRATION, "ply_text": _colored_ply(rows)}
    normal_response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    pinned_params = {**params, "preserve_distinct_xyz_rgb_pairs_in_preview": True}
    pinned_response = client.post(f"{base}/spatial/point-cloud-preview", json=pinned_params)
    assert normal_response.status_code == 200, normal_response.text
    assert pinned_response.status_code == 200, pinned_response.text
    normal, pinned = normal_response.json(), pinned_response.json()
    assert rare_index not in normal["preview_point_indices"]
    assert rare_index in pinned["preview_point_indices"]
    assert len(pinned["preview_point_indices"]) == 512
    assert normal["preview_rgb_variant_support"]["preview_distinct_xyz_rgb_pairs"] == 2
    normal_rgb = normal["preview_rgb_variant_support"]
    assert normal_rgb["source_rgb_channel_ranges_uint8"] == {
        "red": [10, 80],
        "green": [20, 90],
        "blue": [30, 100],
    }
    assert normal_rgb["preview_rgb_channel_ranges_uint8"] == {
        "red": [10, 40],
        "green": [20, 50],
        "blue": [30, 60],
    }
    assert normal_rgb["preview_omitted_source_rgb_channel_extrema"] == [
        "red_max",
        "green_max",
        "blue_max",
    ]
    assert "preview_omits_rgb_channel_extrema" in normal["qc_warnings"]
    support = pinned["preview_rgb_variant_support"]
    assert support["source_distinct_xyz_rgb_pairs"] == 3
    assert support["preview_distinct_xyz_rgb_pairs"] == 3
    assert (
        support["preview_rgb_channel_ranges_uint8"] == (support["source_rgb_channel_ranges_uint8"])
    )
    assert support["preview_omitted_source_rgb_channel_extrema"] == []
    assert "preview_omits_rgb_channel_extrema" not in pinned["qc_warnings"]
    assert support["multi_rgb_xyz_loci_with_complete_preview"] == 1
    assert support["multi_rgb_xyz_loci_with_incomplete_preview"] == 0
    assert pinned["preview_distinct_xyz_rgb_pairs_preservation_requested"] is True
    assert "source_xyz_loci_have_multiple_rgb_values" in pinned["qc_warnings"]
    assert "preview_omits_multi_rgb_locus_variants" in normal["qc_warnings"]
    assert "preview_omits_multi_rgb_locus_variants" not in pinned["qc_warnings"]
    assert "preview_omits_distinct_xyz_rgb_observations" not in pinned["qc_warnings"]
    assert pinned["provenance"] == normal["provenance"]
    assert len(pinned["provenance"]["source_ordered_xyz_rgb_sha256"]) == 64
    assert pinned["preview_sample_geometry_sha256"] != (normal["preview_sample_geometry_sha256"])
    assert pinned["provenance"]["calibration_verified"] is False
    assert pinned["provenance"]["specimen_identity_verified"] is False
    assert pinned["surface_area_m2"] is None
    assert pinned["branch_length_m"] is None

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    node = next(n for n in registry.json() if n["node_type"] == "point_cloud_preview")
    assert node["executable"] is True
    assert node["optional_parameters"]["preserve_distinct_xyz_rgb_pairs_in_preview"] is False
    graph = {
        "graph_id": "color-observation-retention-v14",
        "name": "Retain imported PLY RGB observations",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {
                "node_id": "c",
                "node_type": "point_cloud_preview",
                "parameters": pinned_params,
            },
        ],
        "edges": [
            {
                "edge_id": "e",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "c",
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
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "point_cloud_measurement_preview"
        )
        assert artifact["payload_json"] == pinned
        digests.append(artifact["payload_sha256"])
    assert len(set(digests)) == 1
    assert len(digests[0]) == 64


def test_rgb_pair_preservation_strict_source_and_capacity(
    client: TestClient,
) -> None:
    pid = str(create_project(client, "Color preservation budget")["id"])
    base = f"/api/v1/projects/{pid}/spatial/point-cloud-preview"
    uncolored = {**CALIBRATION, "points": [[0, 0, 0], [1, 0, 0]]}
    invalid_source = client.post(
        base, json={**uncolored, "preserve_distinct_xyz_rgb_pairs_in_preview": True}
    )
    assert invalid_source.status_code == 400, invalid_source.text
    invalid_type = client.post(
        base,
        json={
            **uncolored,
            "preserve_distinct_xyz_rgb_pairs_in_preview": "true",
        },
    )
    assert invalid_type.status_code == 422, invalid_type.text
    with pytest.raises(ValueError, match="must be a boolean"):
        measure_point_cloud_preview(
            points=[[0, 0, 0], [1, 0, 0]],
            **CALIBRATION,
            preserve_distinct_xyz_rgb_pairs_in_preview="true",  # type: ignore[arg-type]
        )

    # 513 distinct color observations at two XYZ locations cannot fit in 512.
    rows = [f"{i // 256} 0 0 {i % 256} {i // 256} 0" for i in range(513)]
    colored = {**CALIBRATION, "ply_text": _colored_ply(rows)}
    over_budget = client.post(
        base, json={**colored, "preserve_distinct_xyz_rgb_pairs_in_preview": True}
    )
    assert over_budget.status_code == 400, over_budget.text
    assert "display budget" in over_budget.text

    # A repeated final acquisition row is not a distinct RGB observation.
    exact_rows = [*rows[:512], rows[0]]
    feasible = client.post(
        base,
        json={
            **CALIBRATION,
            "ply_text": _colored_ply(exact_rows),
            "preserve_distinct_xyz_rgb_pairs_in_preview": True,
        },
    )
    assert feasible.status_code == 200, feasible.text
    sample = feasible.json()
    support = sample["preview_rgb_variant_support"]
    assert support["source_distinct_xyz_rgb_pairs"] == 512
    assert support["preview_distinct_xyz_rgb_pairs"] == 512
    assert sample["preview_source_acquisition_endpoint_support"] == {
        "first_row_displayed": True,
        "last_row_displayed": False,
    }
    assert "preview_omits_acquisition_endpoint_row" in sample["qc_warnings"]


@pytest.mark.parametrize(
    "invalid_rgb",
    [
        [[0, 0, 0]],
        [[0, 0, 0], [256, 0, 0]],
        [[0, 0, 0], [True, 0, 0]],
        [[0, 0, 0], [1.5, 0, 0]],
        [[0, 0, 0], "not-an-rgb-triplet"],
    ],
)
@pytest.mark.parametrize("pin_rgb_pairs", [False, True])
def test_direct_rgb_rows_require_valid_uint8_triplets(
    invalid_rgb: list[object], pin_rgb_pairs: bool
) -> None:
    """Service callers cannot introduce unvalidated synthetic RGB evidence."""
    with pytest.raises(ValueError, match="one uint8 RGB triplet per source row"):
        measure_point_cloud_preview(
            points=[[0, 0, 0], [1, 0, 0]],
            **CALIBRATION,
            point_colors=invalid_rgb,  # type: ignore[arg-type]
            preserve_distinct_xyz_rgb_pairs_in_preview=pin_rgb_pairs,
        )


def test_direct_rgb_rows_accept_uint8_endpoints() -> None:
    """Color limits are valid; RGB support never validates coral condition."""
    measured = measure_point_cloud_preview(
        points=[[0, 0, 0], [1, 0, 0]],
        **CALIBRATION,
        point_colors=[[0, 0, 0], [255, 255, 255]],
        preserve_distinct_xyz_rgb_pairs_in_preview=True,
    )
    assert measured["preview_distinct_xyz_rgb_pairs_preservation_requested"] is True
    assert measured["preview_point_indices"] == [0, 1]
    assert measured["provenance"]["calibration_verified"] is False
    assert measured["provenance"]["specimen_identity_verified"] is False


def test_preview_centroid_sampling_displacement_standalone_and_saved_workflow(
    client: TestClient,
) -> None:
    """A rare omitted observation changes display centering, not coral movement."""
    pid = str(create_project(client, "Point sampling centroid provenance")["id"])
    base = f"/api/v1/projects/{pid}"
    default_indices = {i * 599 // 511 for i in range(512)}
    rare_index = next(i for i in range(1, 300) if i not in default_indices)
    points = [[0, 0, 0] if i < 300 else [1, 0, 0] for i in range(600)]
    points[rare_index] = [20, 0, 0]
    params = {**CALIBRATION, "points": points}
    direct = measure_point_cloud_preview(points=points, **CALIBRATION)
    source_x = sum(point[0] for point in points) * 0.01 / len(points)
    display_x = (
        sum(points[i][0] for i in direct["preview_point_indices"])
        * 0.01
        / len(direct["preview_point_indices"])
    )
    assert rare_index not in direct["preview_point_indices"]
    assert direct["arithmetic_centroid_in_source_frame_m"][0] == pytest.approx(source_x)
    assert direct["preview_row_centroid_in_source_frame_m"][0] == pytest.approx(display_x)
    separation = abs(display_x - source_x)
    assert separation > 0
    assert direct["preview_minus_source_row_centroid_offset_m"] == pytest.approx(
        [display_x - source_x, 0.0, 0.0]
    )
    assert direct["preview_minus_source_row_centroid_offset_m"][0] < 0
    signed_interval = direct["preview_minus_source_row_centroid_offset_scale_interval_m"]
    assert signed_interval is not None
    assert signed_interval[0] == pytest.approx(
        sorted([(display_x - source_x) * 0.9, (display_x - source_x) * 1.1])
    )
    assert signed_interval[1:] == [[0.0, 0.0], [0.0, 0.0]]
    assert direct["preview_vs_source_row_centroid_separation_m"] == pytest.approx(separation)
    assert direct["preview_vs_source_row_centroid_separation_scale_interval_m"] == (
        pytest.approx([separation * 0.9, separation * 1.1])
    )
    assert direct[
        "preview_vs_source_row_centroid_separation_fraction_of_bbox_diagonal"
    ] == pytest.approx(separation / 0.2)
    assert direct["surface_area_m2"] is None
    assert direct["branch_length_m"] is None

    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    measured = response.json()
    for key in (
        "preview_row_centroid_in_source_frame_m",
        "preview_minus_source_row_centroid_offset_m",
        "preview_minus_source_row_centroid_offset_scale_interval_m",
        "preview_vs_source_row_centroid_separation_m",
        "preview_vs_source_row_centroid_separation_scale_interval_m",
        "preview_vs_source_row_centroid_separation_fraction_of_bbox_diagonal",
    ):
        assert measured[key] == direct[key]
    assert measured["provenance"]["calibration_verified"] is False
    assert measured["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": "source-versus-preview-centroid-v14",
        "name": "Source versus sampled point-cloud centroid",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {"node_id": "c", "node_type": "point_cloud_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "e",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "c",
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
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "point_cloud_measurement_preview"
        )
        assert artifact["payload_json"] == measured
        hashes.append(artifact["payload_sha256"])
    assert len(set(hashes)) == 1
    assert len(hashes[0]) == 64


def test_preview_centroid_has_no_false_bias_for_complete_or_coincident_source() -> None:
    complete = measure_point_cloud_preview(points=[[0, 0, 0], [1, 0, 0]], **CALIBRATION)
    assert complete["preview_minus_source_row_centroid_offset_m"] == [0.0, 0.0, 0.0]
    assert complete["preview_minus_source_row_centroid_offset_scale_interval_m"] == [
        [0.0, 0.0],
        [0.0, 0.0],
        [0.0, 0.0],
    ]
    assert complete["preview_vs_source_row_centroid_separation_m"] == 0
    assert complete["preview_vs_source_row_centroid_separation_scale_interval_m"] == [
        0,
        0,
    ]
    assert complete["preview_vs_source_row_centroid_separation_fraction_of_bbox_diagonal"] == 0

    coincident = measure_point_cloud_preview(points=[[7, 7, 7]] * 600, **CALIBRATION)
    assert coincident["preview_minus_source_row_centroid_offset_m"] == [0.0, 0.0, 0.0]
    assert coincident["preview_vs_source_row_centroid_separation_m"] == 0
    assert coincident["preview_vs_source_row_centroid_separation_fraction_of_bbox_diagonal"] is None
    assert coincident["surface_area_m2"] is None
    assert coincident["branch_length_m"] is None


def test_preview_centroid_signed_offset_uncertainty_missing_and_exact() -> None:
    """Missing scale uncertainty is unknown; zero uncertainty keeps signed offsets."""
    points = [[0, 0, 0]] * 599 + [[10, 0, 0]]
    # The last acquisition is visible by uniform preview sampling. The
    # nonuniform source rows still shift the preview centroid relative to all
    # 600 rows, without indicating any real movement of an organism.
    missing = measure_point_cloud_preview(
        points=points,
        **{**CALIBRATION, "relative_scale_uncertainty": None},
    )
    assert missing["preview_minus_source_row_centroid_offset_scale_interval_m"] is None
    exact = measure_point_cloud_preview(
        points=points,
        **{**CALIBRATION, "relative_scale_uncertainty": 0.0},
    )
    offset = exact["preview_minus_source_row_centroid_offset_m"]
    assert offset[0] > 0
    assert exact["preview_minus_source_row_centroid_offset_scale_interval_m"] == [
        [value, value] for value in offset
    ]
    assert (
        "preview_centroid_offset_uncertainty_interval_below_numeric_resolution"
        not in (exact["qc_warnings"])
    )
    assert exact["provenance"]["specimen_identity_verified"] is False


def test_preview_centroid_signed_offset_tracks_direction_on_all_three_axes() -> None:
    """Preview bias direction is measured, not registered specimen movement."""
    default_indices = {i * 599 // 511 for i in range(512)}
    rare_index = next(i for i in range(1, 300) if i not in default_indices)
    points = [[0, 0, 0] if i < 300 else [1, 2, 3] for i in range(600)]
    points[rare_index] = [20, -30, 40]
    measured = measure_point_cloud_preview(points=points, **CALIBRATION)
    indices = measured["preview_point_indices"]
    assert rare_index not in indices
    source = [sum(row[axis] for row in points) * 0.01 / len(points) for axis in range(3)]
    shown = [sum(points[i][axis] for i in indices) * 0.01 / len(indices) for axis in range(3)]
    expected = [shown[axis] - source[axis] for axis in range(3)]
    offset = measured["preview_minus_source_row_centroid_offset_m"]
    assert offset == pytest.approx(expected)
    assert offset[0] < 0
    assert offset[1] > 0
    assert offset[2] < 0
    intervals = measured["preview_minus_source_row_centroid_offset_scale_interval_m"]
    assert intervals is not None
    for signed_value, interval in zip(offset, intervals, strict=True):
        assert interval == pytest.approx(sorted([signed_value * 0.9, signed_value * 1.1]))
        assert interval[0] <= interval[1]
    assert measured["preview_vs_source_row_centroid_separation_m"] == pytest.approx(
        sum(value * value for value in expected) ** 0.5
    )
    assert measured["provenance"]["coordinate_registration_verified"] is False


def test_full_colored_ply_preview_does_not_warn_about_missing_rgb_extrema(
    client: TestClient,
) -> None:
    """Distinct RGB-channel bounds are visible when every row is displayed."""
    pid = str(create_project(client, "Complete RGB sensor bounds")["id"])
    rows = [
        "0 0 0 255 0 0",
        "1 0 0 0 255 0",
        "2 0 0 0 0 255",
    ]
    response = client.post(
        f"/api/v1/projects/{pid}/spatial/point-cloud-preview",
        json={**CALIBRATION, "ply_text": _colored_ply(rows)},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    support = payload["preview_rgb_variant_support"]
    assert support["source_rgb_channel_ranges_uint8"] == {
        "red": [0, 255],
        "green": [0, 255],
        "blue": [0, 255],
    }
    assert (
        support["preview_rgb_channel_ranges_uint8"] == (support["source_rgb_channel_ranges_uint8"])
    )
    assert support["preview_omitted_source_rgb_channel_extrema"] == []
    assert "preview_omits_rgb_channel_extrema" not in payload["qc_warnings"]
    assert payload["provenance"]["calibration_verified"] is False

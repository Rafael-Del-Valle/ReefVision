"""Exact joint XYZ/RGB preview row-cover boundary, including persisted workflows."""

from __future__ import annotations

from itertools import combinations
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_obj_v14 import MAX_VERTICES
from reefvision.services.spatial_point_cloud_v14 import (
    _minimum_joint_locus_color_cover,
    measure_point_cloud_preview,
    parse_ascii_ply_points,
)
from reefvision.tests.test_annotations import create_project

CALIBRATION = {
    "meters_per_unit": 0.01,
    "calibration_method": "ruler",
    "calibration_evidence": "Synthetic, provisional source-scale witness",
    "relative_scale_uncertainty": 0.1,
}


def _alternating_source(repeated_rows: int) -> tuple[list[list[float]], list[list[int]], str]:
    # The first-occurrence rows for A, B, C are A/1, B/2, C/1.
    # A/2, B/3, C/1 is a three-row cover of all three loci and colors.
    # A local single-swap heuristic rejects this feasible cover because
    # B/2 is the only initially retained acquisition of color 2.
    observations: list[tuple[int, list[int]]] = [
        (0, [1, 0, 0]),
        (0, [2, 0, 0]),
        (1, [2, 0, 0]),
        (1, [3, 0, 0]),
        (2, [1, 0, 0]),
    ]
    # Repeat both an ultimately rejected edge and a selected edge. Matching
    # must retain the earliest original row for the selected parallel edge.
    observations[2:2] = [observations[1]] * repeated_rows
    observations[1:1] = [observations[0]] * repeated_rows
    observations.extend((locus, [locus % 256, locus // 256, 1]) for locus in range(3, 512))
    points = [[float(locus), 0.0, 0.0] for locus, _ in observations]
    colors = [rgb for _, rgb in observations]
    assert len(points) == 514 + 2 * repeated_rows
    assert len({tuple(point) for point in points}) == 512
    assert len({tuple(rgb) for rgb in colors}) == 512
    rows = [f"{locus} 0 0 {rgb[0]} {rgb[1]} {rgb[2]}" for locus, rgb in observations]
    ply_text = (
        "ply\nformat ascii 1.0\n"
        f"element vertex {len(rows)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n" + "\n".join(rows) + "\n"
    )
    return points, colors, ply_text


def _graph(params: dict, suffix: str) -> dict:
    return {
        "graph_id": f"joint-locus-color-matching-{suffix}",
        "name": f"Exact joint XYZ and RGB row cover: {suffix}",
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


@pytest.mark.parametrize("repeated_rows", [0, (MAX_VERTICES - 514) // 2])
def test_alternating_joint_cover_minimal_rows_and_saved_workflow(
    client: TestClient, repeated_rows: int
) -> None:
    points, colors, ply_text = _alternating_source(repeated_rows)
    project = create_project(client, "Alternating joint point-cloud cover")
    project_id = str(project["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **CALIBRATION,
        "ply_text": ply_text,
        "preserve_distinct_xyz_loci_in_preview": True,
        "preserve_distinct_rgb_triplets_in_preview": True,
    }
    offset = 2 * repeated_rows
    expected = [1 + repeated_rows, 3 + offset, *range(4 + offset, 514 + offset)]
    direct = measure_point_cloud_preview(
        points=points,
        point_colors=colors,
        preserve_distinct_xyz_loci_in_preview=True,
        preserve_distinct_rgb_triplets_in_preview=True,
        **CALIBRATION,
    )
    assert direct["preview_point_indices"] == expected
    assert direct["preview_unique_coordinate_count"] == 512
    assert direct["provenance"]["calibration_verified"] is False
    assert direct["provenance"]["specimen_identity_verified"] is False
    assert direct["surface_area_m2"] is None
    assert direct["branch_length_m"] is None

    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert response.status_code == 200, response.text
    artifact = response.json()
    assert artifact["preview_point_indices"] == expected
    assert artifact["preview_unique_coordinate_coverage_fraction"] == 1.0
    assert artifact["preview_source_acquisition_endpoint_support"] == {
        "first_row_displayed": False,
        "last_row_displayed": True,
    }
    support = artifact["preview_rgb_variant_support"]
    assert support["source_distinct_rgb_triplets"] == 512
    assert support["preview_distinct_rgb_triplets"] == 512
    assert support["preview_omitted_distinct_rgb_triplets"] == 0
    assert support["source_distinct_xyz_rgb_pairs"] == 514
    assert support["preview_distinct_xyz_rgb_pairs"] == 512
    assert "preview_omits_acquisition_endpoint_row" in artifact["qc_warnings"]
    assert "preview_omits_distinct_rgb_triplets" not in artifact["qc_warnings"]
    assert "preview_omits_distinct_xyz_rgb_observations" in artifact["qc_warnings"]
    assert "preview_shifts_rgb_triplet_frequency_distribution" in artifact["qc_warnings"]
    assert artifact["provenance"]["geometry_sha256"] == direct["provenance"]["geometry_sha256"]
    assert artifact["provenance"]["calibration_verified"] is False
    assert artifact["provenance"]["specimen_identity_verified"] is False

    pair_required = {**params, "preserve_distinct_xyz_rgb_pairs_in_preview": True}
    extrema_required = {**params, "preserve_axis_extrema_in_preview": True}
    with pytest.raises(ValueError, match="Protected point indices exceed the display budget"):
        measure_point_cloud_preview(
            points=points,
            point_colors=colors,
            preserve_distinct_xyz_loci_in_preview=True,
            preserve_distinct_rgb_triplets_in_preview=True,
            preserve_axis_extrema_in_preview=True,
            **CALIBRATION,
        )
    for rejected_params in (pair_required, extrema_required):
        rejected = client.post(f"{base}/spatial/point-cloud-preview", json=rejected_params)
        assert rejected.status_code == 400, rejected.text
        assert "display budget" in rejected.text

    # Persist each typed graph and execute it twice: no invalid success
    # artifact and no variation in the accepted scientific evidence.
    app = cast(FastAPI, client.app)
    for suffix, parameters, expected_status in (
        ("matched", params, "succeeded"),
        ("all-pairs", pair_required, "failed"),
        ("fixed-extrema", extrema_required, "failed"),
    ):
        graph = _graph(parameters, suffix)
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
            ran = process_workflow_run_job(
                app.state.settings,
                app.state.session_factory,
                str(run.json()["job_id"]),
            )
            assert ran is (expected_status == "succeeded")
            detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["run"]["status"] == expected_status
            outputs = [
                item
                for item in detail.json()["artifacts"]
                if item["data_type"] == "point_cloud_measurement_preview"
            ]
            if expected_status == "succeeded":
                assert len(outputs) == 1
                assert outputs[0]["payload_json"] == artifact
                hashes.append(outputs[0]["payload_sha256"])
            else:
                assert "display budget" in detail.json()["run"]["error_message"]
                assert outputs == []
        if expected_status == "succeeded":
            assert len(set(hashes)) == 1
            assert len(hashes[0]) == 64


def test_duplicate_acquisitions_above_source_limit_fail_closed() -> None:
    # The source acquisition limit is independent of the display row budget.
    # Do not silently deduplicate oversized source data to make it admissible.
    repeated_rows = (MAX_VERTICES - 514) // 2 + 1
    points, colors, ply_text = _alternating_source(repeated_rows)
    assert len(points) > MAX_VERTICES
    staged_colors: list[list[int]] = []
    with pytest.raises(ValueError, match="vertex count outside preview bounds"):
        parse_ascii_ply_points(ply_text, colors_out=staged_colors)
    assert staged_colors == []
    with pytest.raises(ValueError, match="Point-cloud size outside preview bounds"):
        measure_point_cloud_preview(
            points=points,
            point_colors=colors,
            preserve_distinct_xyz_loci_in_preview=True,
            preserve_distinct_rgb_triplets_in_preview=True,
            **CALIBRATION,
        )


def test_joint_matching_minimum_cover_against_exhaustive_original_rows() -> None:
    """Small independent oracle guards duplicates, anchors and augmenting chains.

    Enumerate original acquisition subsets rather than replicating the matching
    algorithm. The oracle only establishes exact row-cover minimality, not
    calibrated organism geometry or RGB reflectance validity.
    """
    # 3 exact XYZ loci x 3 raw uint8 RGB triplets, with varying missing edges.
    # This covers disconnected components, isolated obligations, alternating
    # paths, and source-row duplicates. Some cases force an acquisition anchor.
    for mask in range(1, 1 << 9, 5):
        observations = [
            (locus, color)
            for locus in range(3)
            for color in range(3)
            if mask & (1 << (3 * locus + color))
        ]
        if mask % 4 == 0:
            observations.append(observations[0])
        vertices = [(float(locus), 0.0, 0.0) for locus, _ in observations]
        colors = [[color, 0, 0] for _, color in observations]
        if mask % 3 == 0:
            mandatory = {0}
        elif mask % 3 == 1:
            mandatory = {len(observations) - 1}
        else:
            mandatory = set()

        selected = _minimum_joint_locus_color_cover(vertices, colors, mandatory)
        assert mandatory.issubset(selected)
        assert selected.issubset(set(range(len(observations))))
        assert {vertices[index] for index in selected} == set(vertices)
        assert {tuple(colors[index]) for index in selected} == {tuple(color) for color in colors}

        # Independent brute-force certificate for the true minimum number of
        # rows satisfying both cover constraints and all mandatory acquisitions.
        remaining = sorted(set(range(len(observations))) - mandatory)
        best_size = None
        for extra_count in range(len(remaining) + 1):
            for extra in combinations(remaining, extra_count):
                candidate = mandatory | set(extra)
                if {vertices[index] for index in candidate} != set(vertices):
                    continue
                if {tuple(colors[index]) for index in candidate} != {
                    tuple(color) for color in colors
                }:
                    continue
                best_size = len(candidate)
                break
            if best_size is not None:
                break
        assert best_size is not None
        assert len(selected) == best_size, f"mask={mask}, anchored={mandatory}"


@pytest.mark.parametrize(
    "anchored_source_rows",
    [
        (0, 1),
        (0, 3),
        (0, 4, 8),
        (0, 1, 2),
        (0, 1, 9),
    ],
)
def test_joint_cover_multiple_mandatory_acquisitions_and_order(
    anchored_source_rows: tuple[int, ...],
) -> None:
    """Independent minimum cover with multiple fixed acquisitions and duplicates.

    Source-row ordering is not specimen identity or scientific calibration.
    Reversing acquisition order must retain coverage and minimal row count;
    repeated runs on the same order must produce identical selected indices.
    """
    acquisitions = [(locus, color) for locus in range(3) for color in range(3)]
    acquisitions.append((0, 0))  # Duplicate original acquisition, not a new locus.
    for order in (tuple(range(10)), tuple(reversed(range(10)))):
        vertices = [(float(acquisitions[index][0]), 0.0, 0.0) for index in order]
        colors = [[acquisitions[index][1], 0, 0] for index in order]
        mandatory = {order.index(index) for index in anchored_source_rows}
        selected = _minimum_joint_locus_color_cover(vertices, colors, mandatory)
        assert selected == _minimum_joint_locus_color_cover(vertices, colors, mandatory)
        assert mandatory.issubset(selected)
        source_loci = set(vertices)
        source_colors = {tuple(color) for color in colors}
        assert {vertices[index] for index in selected} == source_loci
        assert {tuple(colors[index]) for index in selected} == source_colors

        # Enumerate original acquisition-row subsets, without calling matching.
        remaining = sorted(set(range(len(order))) - mandatory)
        optimal_size = None
        for extra_count in range(len(remaining) + 1):
            for extra in combinations(remaining, extra_count):
                candidate = mandatory | set(extra)
                if {vertices[index] for index in candidate} != source_loci:
                    continue
                if {tuple(colors[index]) for index in candidate} != source_colors:
                    continue
                optimal_size = len(candidate)
                break
            if optimal_size is not None:
                break
        assert optimal_size is not None
        assert len(selected) == optimal_size, (
            f"fixed={anchored_source_rows}, reversed={order[0] != 0}"
        )


@pytest.mark.parametrize("repair", [False, True])
def test_joint_cover_hall_deficiency_saved_workflow(client: TestClient, repair: bool) -> None:
    """Equal marginal counts need not imply a feasible joint row cover."""
    # A and B only observe color 1; C observes both colors 2 and 3.
    # All four original rows are necessary despite three loci and colors.
    # A new B/2 observation repairs the deficiency, allowing a three-row
    # cover A/1, B/2, C/3. The other 509 loci have one unique color each.
    observations = [(0, 1), (1, 1), (2, 2), (2, 3)]
    if repair:
        observations.append((1, 2))
    observations.extend((locus, locus + 1) for locus in range(3, 512))
    vertices = [(float(locus), 0.0, 0.0) for locus, _ in observations]
    colors = [[color % 256, color // 256, 0] for _, color in observations]
    assert len(set(vertices)) == 512
    assert len({tuple(rgb) for rgb in colors}) == 512
    cover = _minimum_joint_locus_color_cover(vertices, colors, set())
    assert len(cover) == (512 if repair else 513)
    assert {vertices[index] for index in cover} == set(vertices)
    assert {tuple(colors[index]) for index in cover} == {tuple(rgb) for rgb in colors}

    points = [list(vertex) for vertex in vertices]
    rows = [
        f"{locus} 0 0 {rgb[0]} {rgb[1]} {rgb[2]}"
        for (locus, _), rgb in zip(observations, colors, strict=True)
    ]
    ply_text = (
        "ply\nformat ascii 1.0\n"
        f"element vertex {len(rows)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        "end_header\n" + "\n".join(rows) + "\n"
    )
    constraints = {
        "preserve_distinct_xyz_loci_in_preview": True,
        "preserve_distinct_rgb_triplets_in_preview": True,
    }
    if repair:
        direct = measure_point_cloud_preview(
            points=points, point_colors=colors, **constraints, **CALIBRATION
        )
        assert direct["preview_point_indices"] == sorted(cover)
        assert direct["provenance"]["calibration_verified"] is False
        assert direct["provenance"]["specimen_identity_verified"] is False
    else:
        with pytest.raises(ValueError, match="Protected point indices exceed the display budget"):
            measure_point_cloud_preview(
                points=points, point_colors=colors, **constraints, **CALIBRATION
            )

    project = create_project(client, "Joint cover Hall deficiency")
    base = f"/api/v1/projects/{project['id']}"
    params = {**CALIBRATION, **constraints, "ply_text": ply_text}
    response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    if repair:
        assert response.status_code == 200, response.text
        artifact = response.json()
        assert artifact["preview_point_indices"] == sorted(cover)
        assert artifact["preview_unique_coordinate_coverage_fraction"] == 1.0
        assert artifact["preview_rgb_variant_support"]["preview_distinct_rgb_triplets"] == 512
        assert artifact["provenance"]["specimen_identity_verified"] is False
    else:
        assert response.status_code == 400, response.text
        assert "display budget" in response.text

    graph = _graph(params, f"hall-{repair}")
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(
            f"{base}/workflow-runs",
            json={"graph_record_id": saved.json()["id"]},
        )
        assert run.status_code == 202, run.text
        ran = process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(run.json()["job_id"]),
        )
        assert ran is repair
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        result = detail.json()
        outputs = [
            item
            for item in result["artifacts"]
            if item["data_type"] == "point_cloud_measurement_preview"
        ]
        if repair:
            assert result["run"]["status"] == "succeeded"
            assert len(outputs) == 1
            assert outputs[0]["payload_json"] == artifact
            hashes.append(outputs[0]["payload_sha256"])
        else:
            assert result["run"]["status"] == "failed"
            assert "display budget" in result["run"]["error_message"]
            assert outputs == []
    if repair:
        assert len(set(hashes)) == 1
        assert len(hashes[0]) == 64

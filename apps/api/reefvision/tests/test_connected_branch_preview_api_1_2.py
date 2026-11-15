"""Read-only branch editing API contracts on a persisted skeleton revision."""

from math import hypot
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reefvision.schemas.connected_branch_editing import ConnectedBranchPreviewResponse
from reefvision.tests.test_skeleton_records_api import _seed_mask


def test_branch_preview_uses_saved_graph_without_changing_source(client: TestClient) -> None:
    mask_id = _seed_mask(client)
    saved = client.post(
        f"/api/v1/mask-annotations/{mask_id}/skeleton-analyses",
        json={"terminal_spur_max_length_pixels": 0},
    )
    assert saved.status_code == 200, saved.text
    record = saved.json()
    skeleton = record["result"]
    occupied = {(point["x"], point["y"]) for point in skeleton["final_skeleton_pixels"]}

    proposed_path = None
    for node in skeleton["final_graph_nodes"]:
        if node["kind"] != "endpoint":
            continue
        x, y = int(node["x"]), int(node["y"])
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            path = [(x + offset * dx, y + offset * dy) for offset in range(3)]
            if all(
                0 <= px < 80 and 0 <= py < 60 and (px, py) not in occupied for px, py in path[1:]
            ):
                proposed_path = path
                break
        if proposed_path is not None:
            break
    assert proposed_path is not None, "Expected a free endpoint extension on fixture skeleton"

    response = client.post(
        f"/api/v1/skeleton-analyses/{record['id']}/branch-edits/preview",
        json={
            "edit_id": "test-preview",
            "points": [{"x": x, "y": y} for x, y in proposed_path],
        },
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["base_analysis_id"] == record["id"]
    assert preview["base_result_sha256"] == record["result_sha256"]
    assert preview["evidence_level"] == "proposal_unverified"
    assert preview["review_gate"] == "scientist_review_required"
    assert preview["persistent_change_applied"] is False
    assert preview["physical_length_computed"] is False
    assert preview["calibration"] is None
    assert all(edge["length_physical"] is None for edge in preview["edges"])
    assert preview["added_length_pixels"] == 2
    assert len(preview["edges"]) == len(skeleton["final_graph_edges"]) + 1

    unchanged = client.get(f"/api/v1/skeleton-analyses/{record['id']}")
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json() == record

    # Previously persisted pixel-only preview rows lack the additive fields.
    preview.pop("calibration")
    for edge in preview["edges"]:
        edge.pop("length_physical")
    assert ConnectedBranchPreviewResponse.model_validate(preview).calibration is None


def _save_calibrated_analysis(
    client: TestClient,
    homography: list[list[float]] | None = None,
) -> tuple[str, dict[str, Any], list[dict[str, int]]]:
    mask_id = _seed_mask(client)
    uncalibrated = client.post(f"/api/v1/mask-annotations/{mask_id}/skeleton-analyses", json={})
    assert uncalibrated.status_code == 200, uncalibrated.text
    image_id = uncalibrated.json()["image_id"]
    updated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={
            "distance_per_pixel": 0.25,
            "unit": "mm",
            "source": "manual_scale_bar",
            "perspective_homography": homography,
        },
    )
    assert updated.status_code == 200, updated.text
    saved = client.post(f"/api/v1/mask-annotations/{mask_id}/skeleton-analyses", json={})
    assert saved.status_code == 200, saved.text
    source = saved.json()
    pixels = source["result"]["final_skeleton_pixels"]
    junction = pixels[len(pixels) // 2]
    path = [{"x": junction["x"], "y": junction["y"] - step} for step in range(4)]
    return image_id, source, path


@pytest.mark.parametrize(
    ("matrix", "method"),
    [
        (None, "scalar_distance_per_pixel"),
        (
            [[0.5, 0.0, 0.0], [0.0, 0.7, 0.0], [0.01, 0.02, 1.0]],
            "reference_plane_homography",
        ),
    ],
)
def test_calibrated_branch_split_measures_each_edge_once(
    client: TestClient, matrix: list[list[float]] | None, method: str
) -> None:
    _, source, path = _save_calibrated_analysis(client, matrix)
    response = client.post(
        f"/api/v1/skeleton-analyses/{source['id']}/branch-edits/preview",
        json={"edit_id": "calibrated-y", "points": path},
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["physical_length_computed"] is True
    assert preview["persistent_change_applied"] is False
    assert preview["geometry_space"] == "source_image_pixels_2d"
    assert preview["review_gate"] == "scientist_review_required"
    calibration = preview["calibration"]
    assert calibration["calibration_sha256"] == source["calibration_sha256"]
    assert calibration["unit"] == "mm"
    assert calibration["source"] == "manual_scale_bar"
    assert calibration["method"] == method
    assert len(preview["edges"]) == 3
    if matrix is None:
        length = 0.75
    else:

        def project(point: dict[str, int]) -> tuple[float, float]:
            x, y = point["x"], point["y"]
            denominator = 0.01 * x + 0.02 * y + 1
            return 0.5 * x / denominator, 0.7 * y / denominator

        start_x, start_y = project(path[0])
        tip_x, tip_y = project(path[-1])
        length = hypot(tip_x - start_x, tip_y - start_y)
    edges = {edge["id"]: edge["length_physical"] for edge in preview["edges"]}
    assert edges[preview["added_edge_id"]] == pytest.approx(length)
    assert calibration["added_length"] == pytest.approx(length)
    baseline = source["result"]["final_total_linear_extension_physical"]
    assert calibration["original_total_length"] == pytest.approx(baseline)
    assert calibration["proposed_total_length"] == pytest.approx(baseline + length)
    assert sum(edges.values()) == pytest.approx(calibration["proposed_total_length"])


def test_branch_preview_rejects_projective_horizon_between_draft_pixels(client: TestClient) -> None:
    _, source, path = _save_calibrated_analysis(
        client, [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 1.0, -23.5]]
    )
    assert path[-1]["y"] < 23.5 < path[0]["y"]
    response = client.post(
        f"/api/v1/skeleton-analyses/{source['id']}/branch-edits/preview",
        json={"edit_id": "invalid-plane", "points": path},
    )
    assert response.status_code == 400, response.text
    assert "projective horizon" in response.json()["detail"]


def test_branch_preview_rejects_replaced_image_calibration(client: TestClient) -> None:
    image_id, source, path = _save_calibrated_analysis(client)
    updated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={"distance_per_pixel": 0.5, "unit": "mm", "source": "manual_scale_bar"},
    )
    assert updated.status_code == 200, updated.text
    response = client.post(
        f"/api/v1/skeleton-analyses/{source['id']}/branch-edits/preview",
        json={"edit_id": "stale-calibration", "points": path},
    )
    assert response.status_code == 400, response.text
    assert "latest non-stale skeleton" in response.json()["detail"]


def test_branch_preview_fails_closed_on_disconnected_and_forged_requests(
    client: TestClient,
) -> None:
    mask_id = _seed_mask(client)
    saved = client.post(f"/api/v1/mask-annotations/{mask_id}/skeleton-analyses", json={})
    assert saved.status_code == 200, saved.text
    analysis_id = saved.json()["id"]
    endpoint = f"/api/v1/skeleton-analyses/{analysis_id}/branch-edits/preview"

    disconnected = client.post(
        endpoint,
        json={
            "edit_id": "disconnected",
            "points": [{"x": 0, "y": 0}, {"x": 0, "y": 1}],
        },
    )
    assert disconnected.status_code >= 400
    bad_evidence = client.post(
        endpoint,
        json={
            "edit_id": "forged",
            "points": [{"x": 0, "y": 0}, {"x": 0, "y": 1}],
            "verified": True,
        },
    )
    assert bad_evidence.status_code == 422
    out_of_bounds = client.post(
        endpoint,
        json={
            "edit_id": "outside",
            "points": [{"x": 80, "y": 0}, {"x": 80, "y": 1}],
        },
    )
    assert out_of_bounds.status_code >= 400

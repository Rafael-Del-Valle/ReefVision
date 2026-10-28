"""Read-only branch editing API contracts on a persisted skeleton revision."""

from fastapi.testclient import TestClient

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
    assert preview["added_length_pixels"] == 2
    assert len(preview["edges"]) == len(skeleton["final_graph_edges"]) + 1

    unchanged = client.get(f"/api/v1/skeleton-analyses/{record['id']}")
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json() == record


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

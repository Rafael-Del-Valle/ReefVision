"""Saved Workflow Builder parity for non-destructive connected coral branch proposals."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_skeleton_records_api import _seed_mask


def _source(client: TestClient) -> tuple[str, dict[str, Any], list[dict[str, int]]]:
    mask_id = _seed_mask(client)
    response = client.post(
        f"/api/v1/mask-annotations/{mask_id}/skeleton-analyses",
        json={"terminal_spur_max_length_pixels": 0},
    )
    assert response.status_code == 200, response.text
    source = response.json()
    occupied = {
        (point["x"], point["y"])
        for point in source["result"]["final_skeleton_pixels"]
    }
    proposed = None
    for node in source["result"]["final_graph_nodes"]:
        if node["kind"] != "endpoint":
            continue
        x, y = int(node["x"]), int(node["y"])
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            path = [(x + step * dx, y + step * dy) for step in range(3)]
            if all(
                0 <= px < 80 and 0 <= py < 60 and (px, py) not in occupied
                for px, py in path[1:]
            ):
                proposed = [{"x": px, "y": py} for px, py in path]
                break
        if proposed is not None:
            break
    assert proposed is not None
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, source["image_id"])
        assert image is not None
        project_id = image.project_id
    return project_id, source, proposed


def _graph(source_id: str, points: list[dict[str, int]]) -> dict[str, Any]:
    return {
        "graph_id": "branch-preview-saved-1-2",
        "name": "Unverified connected branch preview",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "branch",
                "node_type": "ecology_connected_branch_preview",
                "parameters": {
                    "analysis_id": source_id,
                    "edit_id": "workflow-branch",
                    "points": points,
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-branch",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "branch",
                "target_port_id": "project",
            }
        ],
    }


def _run(client: TestClient, project_id: str, graph: dict[str, Any]) -> dict[str, Any]:
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    return detail.json()


def test_saved_branch_preview_matches_api_and_preserves_skeleton(client: TestClient) -> None:
    project_id, source, points = _source(client)
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200
    definition = next(
        row for row in registry.json()
        if row["node_type"] == "ecology_connected_branch_preview"
    )
    assert definition["executable"] is True
    assert definition["output_ports"][0]["accepted_types"] == ["connected_branch_preview"]
    graph = _graph(source["id"], points)
    planned = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert planned.status_code == 200, planned.text
    assert planned.json()["executable"] is True
    standalone = client.post(
        f"/api/v1/skeleton-analyses/{source['id']}/branch-edits/preview",
        json={"edit_id": "workflow-branch", "points": points},
    )
    assert standalone.status_code == 200, standalone.text
    detail = _run(client, project_id, graph)
    assert detail["run"]["status"] == "succeeded"
    artifacts = [
        item for item in detail["artifacts"]
        if item["data_type"] == "connected_branch_preview"
    ]
    assert len(artifacts) == 1
    payload = dict(artifacts[0]["payload_json"])
    assert payload.pop("project_id") == project_id
    assert payload == standalone.json()
    assert payload["base_result_sha256"] == source["result_sha256"]
    assert payload["evidence_level"] == "proposal_unverified"
    assert payload["review_gate"] == "scientist_review_required"
    assert payload["persistent_change_applied"] is False
    assert payload["physical_length_computed"] is False
    unchanged = client.get(f"/api/v1/skeleton-analyses/{source['id']}")
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json() == source

    graph["nodes"].append({"node_id": "dataset", "node_type": "dataset_version_create"})
    graph["edges"].append(
        {
            "edge_id": "preview-verified",
            "source_node_id": "branch",
            "source_port_id": "preview",
            "target_node_id": "dataset",
            "target_port_id": "reviewed",
        }
    )
    invalid = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs/validate", json=graph
    )
    assert invalid.status_code == 200, invalid.text
    assert invalid.json()["valid"] is False


def test_saved_branch_preview_rejects_cross_project_source(client: TestClient) -> None:
    _, source, points = _source(client)
    other = create_project(client, "Foreign branch preview")
    detail = _run(client, str(other["id"]), _graph(source["id"], points))
    assert detail["run"]["status"] == "failed"
    assert not [
        item for item in detail["artifacts"]
        if item["data_type"] == "connected_branch_preview"
    ]


def test_saved_branch_preview_rejects_forged_verification(client: TestClient) -> None:
    project_id, source, points = _source(client)
    graph = _graph(source["id"], points)
    graph["nodes"][1]["parameters"]["verified"] = True
    detail = _run(client, project_id, graph)
    assert detail["run"]["status"] == "failed"
    assert not [
        item for item in detail["artifacts"]
        if item["data_type"] == "connected_branch_preview"
    ]

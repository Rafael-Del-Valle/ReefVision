from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models.computed_metric import ComputedMetricResult
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_workflow_computed_metrics import save_and_queue


def test_verified_mask_comparison_executes_with_workflow_lineage(client: TestClient) -> None:
    project = create_project(client, "Mask comparison workflow")
    class_id = project["label_classes"][0]["id"]
    report = import_one(
        client,
        project["id"],
        filename="workflow-comparison.png",
        relative_path="workflow-comparison.png",
        size=(10, 10),
    )
    image_id = report["successful"][0]["image_id"]
    first_id, second_id = str(uuid4()), str(uuid4())
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": first_id,
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 1, "y": 1},
                        {"x": 4, "y": 1},
                        {"x": 4, "y": 4},
                        {"x": 1, "y": 4},
                    ],
                },
                {
                    "id": second_id,
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 2, "y": 1},
                        {"x": 5, "y": 1},
                        {"x": 5, "y": 4},
                        {"x": 2, "y": 4},
                    ],
                },
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    parameters = {
        "name": "Workflow mask comparison",
        "image_id": image_id,
        "geometry_kind": "masks",
        "source_a": {"kind": "verified_masks", "mask_annotation_ids": [first_id]},
        "source_b": {"kind": "verified_masks", "mask_annotation_ids": [second_id]},
        "reference_side": "a",
        "iou_threshold": 0.5,
    }
    graph = {
        "graph_id": "verified-mask-comparison",
        "name": "Verified mask comparison",
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "comparison",
                "node_type": "annotation_comparison",
                "parameters": parameters,
            },
        ],
        "edges": [
            {
                "edge_id": "project-comparison",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "comparison",
                "target_port_id": "project",
            }
        ],
    }

    registry = client.get("/api/v1/workflow-graphs/node-registry").json()
    node = next(item for item in registry if item["node_type"] == "annotation_comparison")
    assert node["executable"] is True
    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True

    queued = save_and_queue(client, project["id"], graph)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued['id']}").json()
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "computed_metric_result"
    )
    result_id = artifact["payload_json"]["result_id"]
    response = client.get(
        f"/api/v1/projects/{project['id']}/annotation-comparisons/{result_id}"
    )
    assert response.status_code == 200, response.text
    assert response.json()["comparison"]["per_class"][class_id]["union_iou"] == 0.6
    assert artifact["payload_json"]["comparison_sha256"] == response.json()["comparison"][
        "content_sha256"
    ]
    with app.state.session_factory() as session:
        row = session.get(ComputedMetricResult, result_id)
        assert row is not None
        assert row.workflow_run_id == queued["id"]
        comparison_node = next(
            item for item in detail["nodes"] if item["node_type"] == "annotation_comparison"
        )
        assert row.workflow_node_run_id == comparison_node["id"]

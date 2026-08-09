from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration
from reefvision.tests.test_annotations import create_project


def test_prompt_assist_node_plans_in_auto_label_review_chain(client: TestClient) -> None:
    project = create_project(client, "Prompt Assist graph")
    class_id = str(project["label_classes"][0]["id"])
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        assist_model = ModelRegistration(
            project_id=project["id"],
            purpose="assist",
            display_name="Graph assist model",
            source_filename="sam_vit_h_graph.pth",
            managed_path=f"projects/{project['id']}/models/sam_vit_h_graph.pth",
            sha256="c" * 64,
            file_size_bytes=10,
            framework="segment_anything",
            task="assist_segmentation",
            provider_name="segment_anything",
            provider_version="test",
            class_map_json={},
            input_size_json={},
            metadata_json={},
        )
        session.add(assist_model)
        session.commit()
        assist_model_id = assist_model.id

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    definition = next(
        item for item in registry.json() if item["node_type"] == "prompt_assist_masks"
    )
    assert definition["executable"] is True
    assert definition["input_ports"][0]["accepted_types"] == ["reviewed_boxes"]
    assert definition["input_ports"][1]["accepted_types"] == ["model_reference"]
    assert definition["output_ports"][0]["accepted_types"] == ["mask_proposals"]

    graph = {
        "graph_id": "vlm-review-prompt-assist",
        "name": "VLM review to Prompt Assist masks",
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "images", "node_type": "project_images"},
            {
                "node_id": "vlm",
                "node_type": "vlm_detection",
                "parameters": {
                    "provider": "openai",
                    "model": "test-vision-model",
                    "label_class_ids": [class_id],
                },
            },
            {"node_id": "box_review", "node_type": "detection_review_gate"},
            {
                "node_id": "assist_model",
                "node_type": "registered_model_source",
                "parameters": {"model_id": assist_model_id},
            },
            {
                "node_id": "prompt_masks",
                "node_type": "prompt_assist_masks",
                "parameters": {"device": "cpu"},
            },
            {"node_id": "mask_review", "node_type": "mask_review_gate"},
        ],
        "edges": [
            {
                "edge_id": "project-images",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "images",
                "target_port_id": "project",
            },
            {
                "edge_id": "images-vlm",
                "source_node_id": "images",
                "source_port_id": "images",
                "target_node_id": "vlm",
                "target_port_id": "images",
            },
            {
                "edge_id": "vlm-review",
                "source_node_id": "vlm",
                "source_port_id": "proposals",
                "target_node_id": "box_review",
                "target_port_id": "proposals",
            },
            {
                "edge_id": "project-assist-model",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "assist_model",
                "target_port_id": "project",
            },
            {
                "edge_id": "review-prompt-masks",
                "source_node_id": "box_review",
                "source_port_id": "boxes",
                "target_node_id": "prompt_masks",
                "target_port_id": "boxes",
            },
            {
                "edge_id": "assist-model-prompt-masks",
                "source_node_id": "assist_model",
                "source_port_id": "model",
                "target_node_id": "prompt_masks",
                "target_port_id": "model",
            },
            {
                "edge_id": "prompt-masks-review",
                "source_node_id": "prompt_masks",
                "source_port_id": "proposals",
                "target_node_id": "mask_review",
                "target_port_id": "proposals",
            },
        ],
    }
    plan = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/plan",
        json=graph,
    )
    assert plan.status_code == 200, plan.text
    payload = plan.json()
    assert payload["valid"] is True
    assert payload["executable"] is True
    assert payload["execution_blocker"] is None
    prompt_step = next(step for step in payload["steps"] if step["node_id"] == "prompt_masks")
    assert prompt_step["executable"] is True

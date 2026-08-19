from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project


def _vlm_graph(*, provider: str, class_id: str) -> dict[str, object]:
    return {
        "graph_id": "vlm-validation",
        "name": "Cloud VLM validation",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "images", "node_type": "project_images"},
            {
                "node_id": "vlm",
                "node_type": "vlm_detection",
                "parameters": {
                    "provider": provider,
                    "model": "test-vision-model",
                    "label_class_ids": [class_id],
                    "prompt": "Detect the selected class.",
                },
            },
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
        ],
    }


def test_vlm_node_is_registered_and_plans_as_executable(client: TestClient) -> None:
    project = create_project(client, "VLM workflow")
    class_id = str(project["label_classes"][0]["id"])

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    vlm = next(item for item in registry.json() if item["node_type"] == "vlm_detection")
    assert vlm["executable"] is True
    assert vlm["required_parameters"] == ["provider", "model", "label_class_ids"]
    assert vlm["output_ports"][0]["accepted_types"] == ["detection_proposals"]

    graph = _vlm_graph(provider="openai", class_id=class_id)
    plan = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/plan",
        json=graph,
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is True
    assert plan.json()["execution_blocker"] is None


def test_vlm_graph_rejects_unknown_provider_and_foreign_class(client: TestClient) -> None:
    project = create_project(client, "VLM project")
    other_project = create_project(client, "Other VLM project")
    local_class_id = str(project["label_classes"][0]["id"])
    foreign_class_id = str(other_project["label_classes"][0]["id"])

    unsupported = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/validate",
        json=_vlm_graph(provider="not-a-provider", class_id=local_class_id),
    )
    assert unsupported.status_code == 200, unsupported.text
    assert unsupported.json()["valid"] is False
    assert any(
        issue["code"] == "unsupported_vlm_provider" for issue in unsupported.json()["issues"]
    )

    foreign = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/validate",
        json=_vlm_graph(provider="gemini", class_id=foreign_class_id),
    )
    assert foreign.status_code == 200, foreign.text
    assert foreign.json()["valid"] is False
    assert any(issue["code"] == "vlm_class_scope_mismatch" for issue in foreign.json()["issues"])

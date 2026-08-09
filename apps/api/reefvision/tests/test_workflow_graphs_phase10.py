from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration
from reefvision.tests.test_annotations import create_project


def _project_and_images_graph() -> dict[str, object]:
    return {
        "graph_id": "images-plan",
        "name": "Project image source",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "images", "node_type": "project_images"},
        ],
        "edges": [
            {
                "edge_id": "project-to-images",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "images",
                "target_port_id": "project",
            }
        ],
    }


def test_workflow_registry_and_dry_run_plan(client: TestClient) -> None:
    project = create_project(client, "Workflow graph")
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    registry_by_type = {item["node_type"]: item for item in registry.json()}
    assert {
        "project_source",
        "detection_inference",
        "detection_consensus",
        "segmentation_inference",
        "classification_inference",
        "mask_review_gate",
        "mask_measurements",
        "video_tracking",
        "project_exchange_export",
    }.issubset(registry_by_type)
    assert registry_by_type["project_source"]["executable"] is True
    assert registry_by_type["project_images"]["executable"] is True
    assert registry_by_type["project_exchange_export"]["executable"] is True
    assert registry_by_type["detection_inference"]["executable"] is True
    assert registry_by_type["detection_consensus"]["executable"] is True
    assert registry_by_type["segmentation_inference"]["executable"] is True
    assert registry_by_type["classification_inference"]["executable"] is True
    assert registry_by_type["mask_measurements"]["executable"] is True
    assert registry_by_type["video_tracking"]["executable"] is True
    assert registry_by_type["mask_review_gate"]["executable"] is True
    assert registry_by_type["mask_review_gate"]["execution_state"] == "pausable_review_gate"
    consensus_input = registry_by_type["detection_consensus"]["input_ports"][0]
    assert consensus_input["port_id"] == "predictions"
    assert consensus_input["multiple"] is True
    assert registry_by_type["detection_consensus"]["optional_parameters"]["required_votes"] == 2

    validation = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/validate",
        json=_project_and_images_graph(),
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["valid"] is True
    assert validation.json()["topological_order"] == ["project", "images"]

    plan = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/plan",
        json=_project_and_images_graph(),
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is True
    assert [item["node_id"] for item in plan.json()["steps"]] == [
        "project",
        "images",
    ]
    assert all(item["executable"] for item in plan.json()["steps"])
    assert plan.json()["execution_blocker"] is None


def test_workflow_validation_reports_type_and_parameter_errors(
    client: TestClient,
) -> None:
    project = create_project(client, "Invalid workflow")
    graph = {
        "graph_id": "bad-plan",
        "name": "Bad graph",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "dataset", "node_type": "dataset_version_source"},
            {"node_id": "exchange", "node_type": "project_exchange_export"},
        ],
        "edges": [
            {
                "edge_id": "wrong-type",
                "source_node_id": "dataset",
                "source_port_id": "images",
                "target_node_id": "exchange",
                "target_port_id": "project",
            }
        ],
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/validate",
        json=graph,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is False
    codes = {item["code"] for item in payload["issues"]}
    assert "missing_parameter" in codes
    assert "incompatible_port_types" in codes
    assert "required_input_missing" in codes


def test_workflow_validation_checks_model_purpose(client: TestClient) -> None:
    project = create_project(client, "Model graph")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project["id"],
            purpose="classifier",
            display_name="Classifier for mismatch",
            source_filename="classifier.pt",
            managed_path=f"projects/{project['id']}/models/classifier.pt",
            sha256="c" * 64,
            file_size_bytes=10,
            framework="test",
            task="classify",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            input_size_json={"width": 224, "height": 224},
            metadata_json={},
        )
        session.add(model)
        session.commit()
        model_id = model.id

    graph = {
        "graph_id": "model-mismatch",
        "name": "Classifier connected to detector",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "images", "node_type": "project_images"},
            {
                "node_id": "model",
                "node_type": "registered_model_source",
                "parameters": {"model_id": model_id},
            },
            {"node_id": "detect", "node_type": "detection_inference"},
        ],
        "edges": [
            {
                "edge_id": "p-images",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "images",
                "target_port_id": "project",
            },
            {
                "edge_id": "p-model",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "model",
                "target_port_id": "project",
            },
            {
                "edge_id": "images-detect",
                "source_node_id": "images",
                "source_port_id": "images",
                "target_node_id": "detect",
                "target_port_id": "images",
            },
            {
                "edge_id": "model-detect",
                "source_node_id": "model",
                "source_port_id": "model",
                "target_node_id": "detect",
                "target_port_id": "model",
            },
        ],
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/validate",
        json=graph,
    )
    assert response.status_code == 200, response.text
    assert response.json()["valid"] is False
    assert any(
        item["code"] == "model_purpose_mismatch" for item in response.json()["issues"]
    )

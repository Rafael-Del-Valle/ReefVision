from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration
from reefvision.tests.test_annotations import create_project


def _register_model(
    client: TestClient,
    project_id: str,
    *,
    purpose: str,
    task: str,
    name: str,
) -> str:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project_id,
            purpose=purpose,
            display_name=name,
            source_filename=f"{name}.pt",
            managed_path=f"projects/{project_id}/models/{name}.pt",
            sha256=(task[0] if task else "a") * 64,
            file_size_bytes=1,
            framework="test",
            task=task,
            provider_name="test",
            provider_version="1",
            class_map_json={},
            metadata_json={},
        )
        session.add(model)
        session.commit()
        return model.id


def test_valid_workflow_produces_deterministic_execution_stages(
    client: TestClient,
) -> None:
    project = create_project(client, "Workflow planning")
    segmenter_id = _register_model(
        client,
        str(project["id"]),
        purpose="segmenter",
        task="segment",
        name="coral-segmenter",
    )
    payload = {
        "name": "Coral measurement pipeline",
        "nodes": [
            {"id": "images", "node_type": "image_input"},
            {
                "id": "segment",
                "node_type": "segmenter",
                "configuration": {"model_id": segmenter_id},
            },
            {"id": "measure", "node_type": "measurement"},
            {"id": "export", "node_type": "export"},
        ],
        "edges": [
            {
                "source_node_id": "images",
                "source_port": "images",
                "target_node_id": "segment",
                "target_port": "images",
            },
            {
                "source_node_id": "segment",
                "source_port": "masks",
                "target_node_id": "measure",
                "target_port": "masks",
            },
            {
                "source_node_id": "measure",
                "source_port": "measurements",
                "target_node_id": "export",
                "target_port": "artifact",
            },
        ],
    }

    first = client.post(
        f"/api/v1/projects/{project['id']}/workflows/validate",
        json=payload,
    )
    second = client.post(
        f"/api/v1/projects/{project['id']}/workflows/validate",
        json=payload,
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    result = first.json()
    assert result["valid"] is True
    assert result["issues"] == []
    assert result["topological_order"] == [
        "images",
        "segment",
        "measure",
        "export",
    ]
    assert [stage["node_ids"] for stage in result["execution_stages"]] == [
        ["images"],
        ["segment"],
        ["measure"],
        ["export"],
    ]
    assert result["workflow_checksum"] == second.json()["workflow_checksum"]


def test_workflow_reports_port_type_model_task_and_required_input_errors(
    client: TestClient,
) -> None:
    project = create_project(client, "Invalid workflow")
    classifier_id = _register_model(
        client,
        str(project["id"]),
        purpose="classifier",
        task="classify",
        name="wrong-segmenter",
    )
    response = client.post(
        f"/api/v1/projects/{project['id']}/workflows/validate",
        json={
            "nodes": [
                {"id": "images", "node_type": "image_input"},
                {
                    "id": "segment",
                    "node_type": "segmenter",
                    "configuration": {"model_id": classifier_id},
                },
                {"id": "measure", "node_type": "measurement"},
            ],
            "edges": [
                {
                    "source_node_id": "images",
                    "source_port": "images",
                    "target_node_id": "measure",
                    "target_port": "masks",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is False
    codes = {item["code"] for item in payload["issues"]}
    assert "model_task_mismatch" in codes
    assert "port_type_mismatch" in codes
    assert "required_input_missing" in codes


def test_workflow_cycle_is_rejected_and_templates_are_available(
    client: TestClient,
) -> None:
    project = create_project(client, "Cyclic workflow")
    response = client.post(
        f"/api/v1/projects/{project['id']}/workflows/validate",
        json={
            "nodes": [
                {"id": "first", "node_type": "export"},
                {"id": "second", "node_type": "export"},
            ],
            "edges": [
                {
                    "source_node_id": "first",
                    "source_port": "archive",
                    "target_node_id": "second",
                    "target_port": "artifact",
                },
                {
                    "source_node_id": "second",
                    "source_port": "archive",
                    "target_node_id": "first",
                    "target_port": "artifact",
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["valid"] is False
    assert "workflow_cycle" in {item["code"] for item in response.json()["issues"]}

    definitions = client.get("/api/v1/workflow-node-definitions")
    templates = client.get("/api/v1/workflow-templates")
    assert definitions.status_code == 200, definitions.text
    assert templates.status_code == 200, templates.text
    assert {item["node_type"] for item in definitions.json()} >= {
        "detector",
        "segmenter",
        "classifier",
        "tracker",
        "measurement",
        "active_learning",
        "export",
    }
    assert {item["template_id"] for item in templates.json()} == {
        "coral-segmentation-measurement",
        "polyp-detection-classification",
        "fish-tracking-behavior",
    }

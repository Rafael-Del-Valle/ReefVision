from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration, ProjectExchangePackage
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project, import_one


def _project_images_graph(*, annotation_status: str | None = None) -> dict[str, object]:
    parameters: dict[str, object] = {}
    if annotation_status is not None:
        parameters["annotation_status"] = annotation_status
    return {
        "graph_id": "project-images-runtime",
        "name": "Project images runtime",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "images",
                "node_type": "project_images",
                "parameters": parameters,
            },
        ],
        "edges": [
            {
                "edge_id": "project-images",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "images",
                "target_port_id": "project",
            }
        ],
    }


def _save_graph(
    client: TestClient,
    project_id: str,
    graph: dict[str, object],
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _queue_run(
    client: TestClient,
    project_id: str,
    graph_record_id: object,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": graph_record_id},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_executable_workflow_persists_nodes_and_typed_artifacts(
    client: TestClient,
) -> None:
    project = create_project(client, "Executable workflow")
    first = import_one(
        client,
        project["id"],
        filename="workflow-first.png",
        relative_path="workflow/first.png",
    )
    second = import_one(
        client,
        project["id"],
        filename="workflow-second.png",
        relative_path="workflow/second.png",
    )
    image_ids = {
        str(first["successful"][0]["image_id"]),
        str(second["successful"][0]["image_id"]),
    }

    graph = _project_images_graph()
    plan = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/plan",
        json=graph,
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True

    saved = _save_graph(client, project["id"], graph)
    assert saved["revision"] == 1
    assert len(str(saved["graph_sha256"])) == 64
    run = _queue_run(client, project["id"], saved["id"])
    assert run["status"] == "queued"
    assert run["job_id"]

    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        str(run["job_id"]),
    ) is True

    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["run"]["status"] == "succeeded"
    assert payload["run"]["result_json"]["completed_nodes"] == 2
    assert [node["status"] for node in payload["nodes"]] == [
        "succeeded",
        "succeeded",
    ]
    assert payload["nodes"][1]["input_artifact_ids_json"] == [
        payload["nodes"][0]["output_artifact_ids_json"][0]
    ]

    artifacts = {item["data_type"]: item for item in payload["artifacts"]}
    assert {"project_reference", "image_collection"}.issubset(artifacts)
    assert artifacts["project_reference"]["payload_json"]["project_id"] == project["id"]
    assert set(artifacts["image_collection"]["payload_json"]["image_ids"]) == image_ids
    assert artifacts["image_collection"]["payload_json"]["count"] == 2
    assert all(len(item["payload_sha256"]) == 64 for item in payload["artifacts"])


def test_workflow_graph_revisions_are_deduplicated_and_versioned(
    client: TestClient,
) -> None:
    project = create_project(client, "Workflow revisions")
    first = _save_graph(client, project["id"], _project_images_graph())
    duplicate = _save_graph(client, project["id"], _project_images_graph())
    changed = _save_graph(
        client,
        project["id"],
        _project_images_graph(annotation_status="reviewed"),
    )

    assert duplicate["id"] == first["id"]
    assert duplicate["revision"] == 1
    assert changed["id"] != first["id"]
    assert changed["revision"] == 2
    assert changed["graph_sha256"] != first["graph_sha256"]

    listing = client.get(f"/api/v1/projects/{project['id']}/workflow-graphs")
    assert listing.status_code == 200, listing.text
    assert [item["revision"] for item in listing.json()] == [2, 1]


def test_workflow_export_node_builds_project_exchange_artifact(
    client: TestClient,
) -> None:
    project = create_project(client, "Workflow exchange")
    graph = {
        "graph_id": "workflow-exchange",
        "name": "Workflow project export",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "exchange",
                "node_type": "project_exchange_export",
                "parameters": {
                    "include_media": False,
                    "include_model_weights": False,
                    "include_generated_artifacts": False,
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-exchange",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "exchange",
                "target_port_id": "project",
            }
        ],
    }
    saved = _save_graph(client, project["id"], graph)
    run = _queue_run(client, project["id"], saved["id"])
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        str(run["job_id"]),
    ) is True

    detail = client.get(f"/api/v1/workflow-runs/{run['id']}").json()
    artifact = next(
        item
        for item in detail["artifacts"]
        if item["data_type"] == "project_exchange_package"
    )
    package_id = str(artifact["payload_json"]["package_id"])
    with app.state.session_factory() as session:
        package = session.get(ProjectExchangePackage, package_id)
        assert package is not None
        assert package.status == "complete"
        assert package.project_id == project["id"]
        assert package.manifest_sha256 == artifact["payload_json"]["manifest_sha256"]


def test_queue_rejects_valid_graph_with_pending_execution_adapter(
    client: TestClient,
) -> None:
    project = create_project(client, "Pending workflow adapter")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project["id"],
            purpose="detector",
            display_name="Workflow detector",
            source_filename="detector.pt",
            managed_path=f"projects/{project['id']}/models/detector.pt",
            sha256="d" * 64,
            file_size_bytes=10,
            framework="test",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            input_size_json={"width": 640, "height": 640},
            metadata_json={},
        )
        session.add(model)
        session.commit()
        model_id = model.id

    graph = {
        "graph_id": "pending-detection",
        "name": "Pending detector adapter",
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
    plan = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/plan",
        json=graph,
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is False
    assert "Detection Inference" in str(plan.json()["execution_blocker"])

    saved = _save_graph(client, project["id"], graph)
    response = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": saved["id"]},
    )
    assert response.status_code == 400
    assert "not executable yet" in response.json()["detail"]


def test_cancelling_queued_workflow_updates_run_and_nodes(client: TestClient) -> None:
    project = create_project(client, "Cancelled workflow")
    saved = _save_graph(client, project["id"], _project_images_graph())
    run = _queue_run(client, project["id"], saved["id"])

    cancelled = client.post(f"/api/v1/jobs/{run['job_id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    detail = client.get(f"/api/v1/workflow-runs/{run['id']}").json()
    assert detail["run"]["status"] == "cancelled"
    assert {node["status"] for node in detail["nodes"]} == {"cancelled"}

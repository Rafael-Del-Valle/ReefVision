from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import (
    ModelRegistration,
    ProjectExchangePackage,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.domain.errors import ConflictError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_provenance import (
    build_workflow_run_provenance,
    verify_succeeded_node_artifacts,
)
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
    *,
    create_new_revision: bool = True,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": create_new_revision},
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
        size=(81, 60),
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
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(run["job_id"]),
        )
        is True
    )

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

    # This executed two-node graph has a real producer -> consumer edge.
    # Reversing both saved positions remains contiguous but must invalidate
    # run detail and exported scientific provenance until restored.
    with app.state.session_factory() as session:
        producer = session.get(WorkflowNodeRun, payload["nodes"][0]["id"])
        consumer = session.get(WorkflowNodeRun, payload["nodes"][1]["id"])
        assert producer is not None and consumer is not None
        assert (producer.execution_order, consumer.execution_order) == (1, 2)
        producer.execution_order = 2
        consumer.execution_order = 1
        session.commit()

    reversed_detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert reversed_detail.status_code == 409, reversed_detail.text
    assert reversed_detail.json() == {
        "detail": "Workflow run node lineage does not match saved graph"
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="node lineage does not match saved graph"),
    ):
        build_workflow_run_provenance(session, run_id=str(run["id"]))

    with app.state.session_factory() as session:
        producer = session.get(WorkflowNodeRun, payload["nodes"][0]["id"])
        consumer = session.get(WorkflowNodeRun, payload["nodes"][1]["id"])
        assert producer is not None and consumer is not None
        producer.execution_order = 1
        consumer.execution_order = 2
        session.commit()
    assert client.get(f"/api/v1/workflow-runs/{run['id']}").json() == payload

    # The completed image-collection node cannot consume its own output.
    # That output has a valid checksum and belongs to the same run, so
    # artifact integrity alone cannot detect the falsified input lineage.
    with app.state.session_factory() as session:
        consumer = session.get(WorkflowNodeRun, payload["nodes"][1]["id"])
        assert consumer is not None
        consumer.input_artifact_ids_json = [payload["nodes"][1]["output_artifact_ids_json"][0]]
        session.commit()

    invalid_input = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert invalid_input.status_code == 409, invalid_input.text
    assert invalid_input.json() == {
        "detail": "Succeeded workflow node input lacks an earlier succeeded producer"
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="input lacks an earlier succeeded producer"),
    ):
        build_workflow_run_provenance(session, run_id=str(run["id"]))

    with app.state.session_factory() as session:
        consumer = session.get(WorkflowNodeRun, payload["nodes"][1]["id"])
        assert consumer is not None
        consumer.input_artifact_ids_json = payload["nodes"][1]["input_artifact_ids_json"]
        session.commit()
    assert client.get(f"/api/v1/workflow-runs/{run['id']}").json() == payload

    # An empty saved input list must not erase the graph's producer edge.
    # This checks an actual completed two-node run, not a fabricated fixture.
    with app.state.session_factory() as session:
        consumer = session.get(WorkflowNodeRun, payload["nodes"][1]["id"])
        assert consumer is not None
        consumer.input_artifact_ids_json = []
        session.commit()

    missing_binding = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert missing_binding.status_code == 409, missing_binding.text
    assert missing_binding.json() == {
        "detail": "Succeeded workflow node input count does not match saved graph"
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="input count does not match saved graph"),
    ):
        build_workflow_run_provenance(session, run_id=str(run["id"]))

    with app.state.session_factory() as session:
        consumer = session.get(WorkflowNodeRun, payload["nodes"][1]["id"])
        assert consumer is not None
        consumer.input_artifact_ids_json = payload["nodes"][1]["input_artifact_ids_json"]
        session.commit()
    assert client.get(f"/api/v1/workflow-runs/{run['id']}").json() == payload

    # A saved input can still reference an earlier succeeded producer while
    # consuming the wrong output port. Change the producer's declared port
    # consistently so its output summary and artifact checksums remain valid.
    with app.state.session_factory() as session:
        artifact = session.get(WorkflowArtifact, artifacts["project_reference"]["id"])
        producer = session.get(WorkflowNodeRun, payload["nodes"][0]["id"])
        assert artifact is not None and producer is not None
        original_port = artifact.producer_port_id
        original_result = dict(producer.result_json or {})
        assert original_port == "project"
        declared_outputs = original_result["outputs"]
        assert declared_outputs[0]["port_id"] == original_port
        artifact.producer_port_id = "substituted-port"
        producer.result_json = {
            **original_result,
            "outputs": [{**item, "port_id": "substituted-port"} for item in declared_outputs],
        }
        session.commit()

    wrong_port = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert wrong_port.status_code == 409, wrong_port.text
    assert wrong_port.json() == {
        "detail": "Succeeded workflow node inputs do not match saved graph edges"
    }
    with (
        app.state.session_factory() as session,
        pytest.raises(ConflictError, match="inputs do not match saved graph edges"),
    ):
        build_workflow_run_provenance(session, run_id=str(run["id"]))

    with app.state.session_factory() as session:
        artifact = session.get(WorkflowArtifact, artifacts["project_reference"]["id"])
        producer = session.get(WorkflowNodeRun, payload["nodes"][0]["id"])
        assert artifact is not None and producer is not None
        artifact.producer_port_id = original_port
        producer.result_json = original_result
        session.commit()
    assert client.get(f"/api/v1/workflow-runs/{run['id']}").json() == payload

    # The executed project's input may have a valid checksum and the exact
    # graph-required producer/port but still be an undeclared, substituted
    # artifact. Verify persisted-node reuse independently of terminal-run
    # checks, which do not apply during interrupted workflow recovery.
    with app.state.session_factory() as session:
        producer = session.get(WorkflowNodeRun, payload["nodes"][0]["id"])
        consumer = session.get(WorkflowNodeRun, payload["nodes"][1]["id"])
        original = session.get(WorkflowArtifact, artifacts["project_reference"]["id"])
        assert producer is not None and consumer is not None and original is not None
        undeclared = WorkflowArtifact(
            workflow_run_id=str(run["id"]),
            producer_node_run_id=producer.id,
            producer_port_id=original.producer_port_id,
            data_type=original.data_type,
            payload_json=dict(original.payload_json),
            payload_sha256=original.payload_sha256,
        )
        session.add(undeclared)
        session.flush()
        consumer.input_artifact_ids_json = [undeclared.id]
        session.flush()
        with pytest.raises(ConflictError, match="input is not a declared producer output"):
            verify_succeeded_node_artifacts(session, run_id=str(run["id"]), node_run=consumer)
        session.rollback()
    assert client.get(f"/api/v1/workflow-runs/{run['id']}").json() == payload

    # This graph was actually executed and its provenance frozen at closeout.
    # Removing *both* saved provenance fields used to bypass the integrity check.
    with app.state.session_factory() as session:
        saved_run = session.get(WorkflowRun, str(run["id"]))
        assert saved_run is not None
        original_result = dict(saved_run.result_json or {})
        assert "provenance_manifest" in original_result
        assert "provenance_sha256" in original_result
        saved_run.result_json = {
            key: value
            for key, value in original_result.items()
            if key not in {"provenance_manifest", "provenance_sha256"}
        }
        session.commit()

    missing_provenance = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert missing_provenance.status_code == 409, missing_provenance.text
    assert missing_provenance.json() == {
        "detail": "Succeeded workflow run is missing saved provenance"
    }

    with app.state.session_factory() as session:
        saved_run = session.get(WorkflowRun, str(run["id"]))
        assert saved_run is not None
        saved_run.result_json = original_result
        session.commit()
    assert client.get(f"/api/v1/workflow-runs/{run['id']}").json() == payload


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


def test_changed_workflow_is_immutable_even_when_client_requests_in_place_update(
    client: TestClient,
) -> None:
    project = create_project(client, "Immutable workflow revisions")
    first = _save_graph(client, project["id"], _project_images_graph())
    changed = _save_graph(
        client,
        project["id"],
        _project_images_graph(annotation_status="reviewed"),
        create_new_revision=False,
    )

    assert changed["id"] != first["id"]
    assert changed["revision"] == 2
    listing = client.get(f"/api/v1/projects/{project['id']}/workflow-graphs").json()
    original = next(item for item in listing if item["id"] == first["id"])
    assert original["revision"] == 1
    assert original["graph_sha256"] == first["graph_sha256"]


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
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(run["job_id"]),
        )
        is True
    )

    detail = client.get(f"/api/v1/workflow-runs/{run['id']}").json()
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "project_exchange_package"
    )
    package_id = str(artifact["payload_json"]["package_id"])
    with app.state.session_factory() as session:
        package = session.get(ProjectExchangePackage, package_id)
        assert package is not None
        assert package.status == "complete"
        assert package.project_id == project["id"]
        assert package.manifest_sha256 == artifact["payload_json"]["manifest_sha256"]


def test_workflow_with_human_review_gate_can_be_queued(
    client: TestClient,
) -> None:
    project = create_project(client, "Pausable human review workflow")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project["id"],
            purpose="segmenter",
            display_name="Workflow segmenter",
            source_filename="segmenter.pt",
            managed_path=f"projects/{project['id']}/models/segmenter.pt",
            sha256="d" * 64,
            file_size_bytes=10,
            framework="test",
            task="segment",
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
        "graph_id": "pausable-mask-review",
        "name": "Segmentation waiting for review",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "images", "node_type": "project_images"},
            {
                "node_id": "model",
                "node_type": "registered_model_source",
                "parameters": {"model_id": model_id},
            },
            {"node_id": "segment", "node_type": "segmentation_inference"},
            {"node_id": "review", "node_type": "mask_review_gate"},
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
                "edge_id": "images-segment",
                "source_node_id": "images",
                "source_port_id": "images",
                "target_node_id": "segment",
                "target_port_id": "images",
            },
            {
                "edge_id": "model-segment",
                "source_node_id": "model",
                "source_port_id": "model",
                "target_node_id": "segment",
                "target_port_id": "model",
            },
            {
                "edge_id": "segment-review",
                "source_node_id": "segment",
                "source_port_id": "proposals",
                "target_node_id": "review",
                "target_port_id": "proposals",
            },
        ],
    }
    plan = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/plan",
        json=graph,
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is True
    assert plan.json()["execution_blocker"] is None

    saved = _save_graph(client, project["id"], graph)
    response = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": saved["id"]},
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"


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

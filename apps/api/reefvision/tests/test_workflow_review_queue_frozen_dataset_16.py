"""A typed saved QC graph must preserve immutable dataset-version evidence."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ReviewQueue, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_dataset_versions import create_version, save_annotations
from reefvision.tests.test_review_queue_annotation_evidence_16 import _queue_item


def _frozen_graph(version_id: str) -> dict[str, Any]:
    return {
        "graph_id": f"frozen-qc-{uuid4()}",
        "name": "Frozen biological QC review",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "version",
                "node_type": "dataset_version_source",
                "parameters": {"dataset_version_id": version_id},
            },
            {"node_id": "qc", "node_type": "qc_review_queue"},
        ],
        "edges": [
            {
                "edge_id": "project-version",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "version",
                "target_port_id": "project",
            },
            {
                "edge_id": "project-qc",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "qc",
                "target_port_id": "project",
            },
            {
                "edge_id": "version-qc",
                "source_node_id": "version",
                "source_port_id": "dataset",
                "target_node_id": "qc",
                "target_port_id": "dataset",
            },
        ],
    }


def _run_frozen_graph(
    client: TestClient, project_id: str, graph_record_id: str
) -> tuple[str, dict[str, Any]]:
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": graph_record_id},
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )
        is True
    )
    run_id = queued.json()["id"]
    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    outputs = [
        artifact
        for artifact in detail.json()["artifacts"]
        if artifact["data_type"] == "review_queue_reference"
    ]
    assert len(outputs) == 1
    payload = outputs[0]["payload_json"]
    assert payload["priority_score_unit"] == "dimensionless"
    assert payload["review_status"] == "requires_researcher_review"
    assert payload["workflow_run_id"] == run_id
    return run_id, payload


def _study(client: TestClient) -> tuple[str, str, str, dict[str, Any]]:
    project = create_project(client, "Frozen octocoral workflow QC")
    project_id = project["id"]
    imported = import_one(client, project_id, filename="frozen-qc-coral.png")
    image_id = imported["successful"][0]["image_id"]
    annotation = {
        "id": str(uuid4()),
        "label_class_id": project["label_classes"][0]["id"],
        "x_min": 5,
        "y_min": 5,
        "x_max": 25,
        "y_max": 25,
    }
    save_annotations(
        client,
        image_id,
        base_revision=0,
        annotation_status="reviewed",
        annotations=[annotation],
    )
    version = create_version(client, project_id, name="Frozen coral study")
    return project_id, image_id, version["id"], annotation


def test_frozen_dataset_qc_standalone_and_saved_graph_preserve_review_evidence(
    client: TestClient,
) -> None:
    project_id, image_id, version_id, annotation = _study(client)
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    qc_node = next(node for node in registry.json() if node["node_type"] == "qc_review_queue")
    assert any(
        port["port_id"] == "dataset"
        and port["accepted_types"] == ["dataset_version"]
        and port["required"] is False
        for port in qc_node["input_ports"]
    )

    version_url = f"/api/v1/dataset-versions/{version_id}/review-queues"
    standalone_before = client.post(version_url, json={})
    assert standalone_before.status_code == 201, standalone_before.text
    frozen_before = _queue_item(client, standalone_before.json()["id"])
    graph = _frozen_graph(version_id)
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    first_run_id, first_payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    assert first_payload["dataset_version_id"] == version_id
    assert first_payload["dataset_manifest_sha256"]
    first_item = _queue_item(client, first_payload["queue_id"])
    assert first_item["input_checksum"] == frozen_before["input_checksum"]
    assert first_item["score"] == frozen_before["score"]

    # Later live geometry edits must not rewrite the frozen study's priorities.
    save_annotations(
        client,
        image_id,
        base_revision=1,
        annotation_status="reviewed",
        annotations=[{**annotation, "x_min": 12, "x_max": 32}],
    )
    standalone_after = client.post(version_url, json={})
    assert standalone_after.status_code == 201, standalone_after.text
    frozen_after = _queue_item(client, standalone_after.json()["id"])
    second_run_id, second_payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    assert second_run_id != first_run_id
    assert second_payload["queue_id"] != first_payload["queue_id"]
    assert second_payload["dataset_manifest_sha256"] == first_payload["dataset_manifest_sha256"]
    assert frozen_after["input_checksum"] == frozen_before["input_checksum"]
    assert (
        _queue_item(client, second_payload["queue_id"])["input_checksum"]
        == (first_item["input_checksum"])
    )
    assert _queue_item(client, first_payload["queue_id"])["review_state"] == "pending"
    live = client.post(f"/api/v1/projects/{project_id}/review-queues", json={})
    assert live.status_code == 201, live.text
    assert (
        _queue_item(client, live.json()["id"])["input_checksum"] != (first_item["input_checksum"])
    )


def test_saved_frozen_qc_rejects_resigned_dataset_manifest(
    client: TestClient,
) -> None:
    project_id, _, version_id, _ = _study(client)
    graph = _frozen_graph(version_id)
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run_id, payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        node_runs = session.scalars(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        ).all()
        by_type = {node.node_type: node for node in node_runs}
        project_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == by_type["project_source"].id,
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        dataset_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == by_type["dataset_version_source"].id,
                WorkflowArtifact.producer_port_id == "dataset",
            )
        )
        assert project_artifact is not None and dataset_artifact is not None
        # Re-signing a forged payload digest is not permission to replace the
        # persisted immutable dataset manifest or create a replacement queue.
        dataset_artifact.payload_json = {
            **dataset_artifact.payload_json,
            "manifest_sha256": "0" * 64,
        }
        dataset_artifact.payload_sha256 = canonical_json_sha256(dataset_artifact.payload_json)
        session.flush()
        qc_run = by_type["qc_review_queue"]
        with pytest.raises(ValidationError, match="manifest"):
            create_review_queue_workflow_artifact(
                session,
                app.state.settings,
                project_id,
                {
                    **dict(qc_run.parameters_json or {}),
                    "__workflow_run_id": run_id,
                    "__workflow_node_run_id": qc_run.id,
                },
                {"project": [project_artifact], "dataset": [dataset_artifact]},
            )
        session.rollback()
    # A failed replay cannot rewrite a researcher's historical review queue.
    assert _queue_item(client, payload["queue_id"])["review_state"] == "pending"


@pytest.mark.parametrize(
    ("tamper", "expected_error"),
    [
        ("wrong_queue_scope", "retry parameters changed or queue incomplete"),
        ("wrong_item_version", "snapshot failed integrity"),
    ],
)
def test_saved_frozen_qc_replay_enforces_dataset_scope(
    client: TestClient, tamper: str, expected_error: str
) -> None:
    """A completed frozen queue must be replayable, but never as live evidence."""
    project_id, _, version_id, _ = _study(client)
    graph = _frozen_graph(version_id)
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run_id, payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        nodes = session.scalars(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        ).all()
        by_type = {node.node_type: node for node in nodes}
        project_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == by_type["project_source"].id,
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        dataset_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == by_type["dataset_version_source"].id,
                WorkflowArtifact.producer_port_id == "dataset",
            )
        )
        queue = session.get(ReviewQueue, payload["queue_id"])
        assert project_artifact is not None and dataset_artifact is not None
        assert queue is not None
        assert queue.scope_type == "dataset_version"
        assert queue.dataset_version_id == version_id
        assert len(queue.items) == 1
        assert queue.items[0].dataset_version_id == version_id
        qc_node = by_type["qc_review_queue"]
        parameters = {
            **dict(qc_node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": qc_node.id,
        }
        inputs = {"project": [project_artifact], "dataset": [dataset_artifact]}

        # The original frozen queue is a valid idempotent saved-node replay.
        original = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, parameters, inputs
        )
        assert original[0]["payload"] == payload

        if tamper == "wrong_queue_scope":
            queue.scope_type = "project"
        else:
            queue.items[0].dataset_version_id = None
        session.flush()
        with pytest.raises(ValidationError, match=expected_error):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, parameters, inputs
            )
        session.rollback()

        # A failed attempt cannot rewrite the original queue or reviewer state.
        restored = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, parameters, inputs
        )
        assert restored[0]["payload"] == payload
        session.rollback()

    assert _queue_item(client, payload["queue_id"])["review_state"] == "pending"


def test_frozen_unannotated_study_has_no_invented_rare_class_priority(
    client: TestClient,
) -> None:
    """Standalone and executable saved graphs agree when no taxa were annotated."""
    project = create_project(client, "Unannotated octocoral study")
    project_id = project["id"]
    imported = import_one(client, project_id, filename="unannotated-coral.png")
    image_id = imported["successful"][0]["image_id"]
    save_annotations(
        client,
        image_id,
        base_revision=0,
        annotation_status="reviewed",
        annotations=[],
    )
    version_id = create_version(client, project_id, name="Unannotated frozen study")["id"]

    standalone = client.post(
        f"/api/v1/dataset-versions/{version_id}/review-queues", json={}
    )
    assert standalone.status_code == 201, standalone.text
    standalone_item = _queue_item(client, standalone.json()["id"])
    graph = _frozen_graph(version_id)
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    _, payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    workflow_item = _queue_item(client, payload["queue_id"])

    for item in (standalone_item, workflow_item):
        assert item["label_class_ids_json"] == []
        assert item["signal_values_json"]["rare_class_presence"] == 0.0
        assert item["normalized_signals_json"]["rare_class_presence"] == 0.0
        assert item["review_state"] == "pending"
    assert workflow_item["input_checksum"] == standalone_item["input_checksum"]
    assert workflow_item["score"] == standalone_item["score"]

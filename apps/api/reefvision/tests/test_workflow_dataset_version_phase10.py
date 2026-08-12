from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import DatasetVersion, DatasetVersionItem, WorkflowNodeRun, WorkflowRun
from reefvision.schemas.workflow_graphs import WorkflowGraphRequest
from reefvision.services.workflow_datasets import create_workflow_dataset_version
from reefvision.services.workflow_graphs import WorkflowGraphService
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_dataset_versions import (
    create_version,
    import_image,
    save_annotations,
    update_image,
)


def _dataset_fixture(client: TestClient) -> tuple[dict[str, Any], dict[str, Any], str]:
    project = create_project(client, "Workflow dataset versions")
    imported = import_image(
        client,
        project["id"],
        filename="dataset-v2.png",
        relative_path="workflow/dataset-v2.png",
        color=(30, 90, 60),
    )
    image_id = str(imported["successful"][0]["image_id"])
    update_image(client, image_id, group_key="fragment-a", annotation_status="reviewed")
    save_annotations(
        client,
        image_id,
        base_revision=0,
        annotation_status="reviewed",
        annotations=[
            {
                "id": "dataset-v2-box",
                "label_class_id": project["label_classes"][0]["id"],
                "x_min": 4,
                "y_min": 5,
                "x_max": 22,
                "y_max": 24,
            }
        ],
    )
    version = create_version(client, project["id"], name="Parent dataset v1")
    return project, version, image_id


def test_workflow_dataset_version_is_idempotent_and_reuses_parent_split(
    client: TestClient,
    test_settings,
) -> None:
    project, parent, image_id = _dataset_fixture(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        parent_item = session.scalar(
            select(DatasetVersionItem).where(
                DatasetVersionItem.dataset_version_id == parent["id"],
                DatasetVersionItem.image_id == image_id,
            )
        )
        assert parent_item is not None

        result = create_workflow_dataset_version(
            session,
            test_settings,
            project_id=str(project["id"]),
            run_id="workflow-run-dataset-v2",
            node_run_id="workflow-node-dataset-v2",
            parameters={
                "name": "Reviewed dataset v2",
                "eligible_annotation_statuses": ["reviewed"],
                "reuse_parent_assignments": None,
            },
            project_payload={"project_id": project["id"]},
            parent_dataset_payload={
                "project_id": project["id"],
                "dataset_version_id": parent["id"],
            },
            reviewed_payloads=[
                {
                    "project_id": project["id"],
                    "source_data_type": "detection_consensus",
                    "annotation_ids": ["dataset-v2-box"],
                }
            ],
        )
        assert result["parent_version_id"] == parent["id"]
        assert result["version_number"] == int(parent["version_number"]) + 1
        assert result["image_count"] == 1
        assert result["annotation_count"] == 1
        assert result["created_by"].startswith("workflow:workflow-run-dataset-v2")
        assert result["manifest_sha256"]

        child_item = session.scalar(
            select(DatasetVersionItem).where(
                DatasetVersionItem.dataset_version_id == result["dataset_version_id"],
                DatasetVersionItem.image_id == image_id,
            )
        )
        assert child_item is not None
        assert child_item.split == parent_item.split

        duplicate = create_workflow_dataset_version(
            session,
            test_settings,
            project_id=str(project["id"]),
            run_id="workflow-run-dataset-v2",
            node_run_id="workflow-node-dataset-v2",
            parameters={"name": "Should not create another version"},
            project_payload={"project_id": project["id"]},
            parent_dataset_payload={
                "project_id": project["id"],
                "dataset_version_id": parent["id"],
            },
        )
        assert duplicate["dataset_version_id"] == result["dataset_version_id"]
        versions = list(
            session.scalars(
                select(DatasetVersion).where(DatasetVersion.project_id == project["id"])
            )
        )
        assert len(versions) == 2


def test_dataset_v2_can_feed_training_in_one_executable_graph(client: TestClient) -> None:
    project, parent, _image_id = _dataset_fixture(client)
    graph = WorkflowGraphRequest.model_validate(
        {
            "graph_id": "review-to-retrain",
            "name": "Reviewed state to retraining",
            "nodes": [
                {"node_id": "project", "node_type": "project_source", "parameters": {}},
                {
                    "node_id": "parent",
                    "node_type": "dataset_version_source",
                    "parameters": {"dataset_version_id": parent["id"]},
                },
                {
                    "node_id": "dataset_v2",
                    "node_type": "dataset_version_create",
                    "parameters": {"name": "Reviewed dataset v2"},
                },
                {
                    "node_id": "train",
                    "node_type": "model_training",
                    "parameters": {"task": "detect", "architecture": "yolo11n.yaml"},
                },
                {
                    "node_id": "register",
                    "node_type": "register_trained_model",
                    "parameters": {},
                },
                {
                    "node_id": "infer",
                    "node_type": "detection_inference",
                    "parameters": {"confidence": 0.25, "iou": 0.5},
                },
            ],
            "edges": [
                {
                    "edge_id": "project-parent",
                    "source_node_id": "project",
                    "source_port_id": "project",
                    "target_node_id": "parent",
                    "target_port_id": "project",
                },
                {
                    "edge_id": "project-v2",
                    "source_node_id": "project",
                    "source_port_id": "project",
                    "target_node_id": "dataset_v2",
                    "target_port_id": "project",
                },
                {
                    "edge_id": "parent-v2",
                    "source_node_id": "parent",
                    "source_port_id": "dataset",
                    "target_node_id": "dataset_v2",
                    "target_port_id": "parent_dataset",
                },
                {
                    "edge_id": "v2-train",
                    "source_node_id": "dataset_v2",
                    "source_port_id": "dataset",
                    "target_node_id": "train",
                    "target_port_id": "dataset",
                },
                {
                    "edge_id": "train-register",
                    "source_node_id": "train",
                    "source_port_id": "training",
                    "target_node_id": "register",
                    "target_port_id": "training",
                },
                {
                    "edge_id": "v2-infer-images",
                    "source_node_id": "dataset_v2",
                    "source_port_id": "images",
                    "target_node_id": "infer",
                    "target_port_id": "images",
                },
                {
                    "edge_id": "register-infer-model",
                    "source_node_id": "register",
                    "source_port_id": "model",
                    "target_node_id": "infer",
                    "target_port_id": "model",
                },
            ],
        }
    )
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        plan = WorkflowGraphService(session).plan(str(project["id"]), graph)
    assert plan.valid is True
    assert plan.executable is True
    assert [step.node_type for step in plan.steps] == [
        "project_source",
        "dataset_version_source",
        "dataset_version_create",
        "model_training",
        "register_trained_model",
        "detection_inference",
    ]


def test_dataset_version_create_registry_accepts_reviewed_results(client: TestClient) -> None:
    project, _parent, _image_id = _dataset_fixture(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        definition = WorkflowGraphService(session).registry["dataset_version_create"]
    reviewed = next(port for port in definition.input_ports if port.port_id == "reviewed")
    assert reviewed.required is False
    assert reviewed.multiple is True
    assert set(reviewed.accepted_types) == {
        "reviewed_boxes",
        "reviewed_masks",
        "reviewed_labels",
    }

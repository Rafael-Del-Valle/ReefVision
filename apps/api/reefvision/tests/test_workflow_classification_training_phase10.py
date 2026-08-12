from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import ClassificationDataset, Job, ModelRegistration, Project
from reefvision.schemas.workflow_graphs import WorkflowGraphRequest
from reefvision.services.workflow_classification import (
    materialize_workflow_classification_dataset,
    train_workflow_classifier,
)
from reefvision.services.workflow_graphs import WorkflowGraphService
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_dataset_versions import create_version, import_image, update_image


def _classification_version(client: TestClient) -> tuple[dict[str, Any], dict[str, Any], str]:
    project = create_project(client, "Workflow classification")
    imported = import_image(
        client,
        project["id"],
        filename="classified.png",
        relative_path="classification/classified.png",
        color=(70, 30, 100),
    )
    image_id = str(imported["successful"][0]["image_id"])
    update_image(client, image_id, group_key="classification-1", annotation_status="reviewed")
    class_id = str(project["label_classes"][0]["id"])
    labels = client.put(
        f"/api/v1/images/{image_id}/classification-labels",
        json={"label_set": "species", "label_class_ids": [class_id]},
    )
    assert labels.status_code == 200, labels.text
    version = create_version(client, project["id"], name="Classification workflow v1")
    return project, version, image_id


def _fake_classification_processor(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        request = dict(job.request_json)
        dataset = session.get(
            ClassificationDataset,
            str(request["classification_dataset_id"]),
        )
        assert dataset is not None
        project = session.get(Project, dataset.project_id)
        assert project is not None
        model_id = "workflow-classifier-model"
        managed_path = f"{project.storage_root}/models/{model_id}.pt"
        checkpoint = resolve_managed_project_path(settings, managed_path)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b"synthetic-classification-checkpoint")
        model = ModelRegistration(
            id=model_id,
            project_id=project.id,
            purpose="classifier",
            display_name="Workflow classifier",
            source_filename="synthetic.pt",
            managed_path=managed_path,
            sha256="e" * 64,
            file_size_bytes=checkpoint.stat().st_size,
            framework="ultralytics",
            task="classify",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={"label_set": dataset.label_set},
            input_size_json={"width": 224, "height": 224},
            metadata_json={
                "classification_dataset_id": dataset.id,
                "dataset_manifest_sha256": dataset.manifest_sha256,
                "training_metrics": {"accuracy": 0.95},
            },
        )
        session.add(model)
        job.status = "succeeded"
        job.progress_current = job.progress_total
        job.result_json = {
            "model_id": model.id,
            "checkpoint_path": managed_path,
            "metrics": {"accuracy": 0.95},
            "provider_version": "test",
        }
        session.commit()
    return True


def test_workflow_materializes_classification_dataset_and_trains_registered_model(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project, version, _image_id = _classification_version(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        dataset_payload = materialize_workflow_classification_dataset(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": project["id"],
                "dataset_version_id": version["id"],
                "manifest_sha256": version["manifest_sha256"],
            },
            parameters={"mode": "image", "label_set": "species"},
        )
        assert dataset_payload["sample_count"] == 1
        assert dataset_payload["mode"] == "image"
        assert dataset_payload["label_set"] == "species"
        assert resolve_managed_project_path(
            test_settings,
            str(dataset_payload["output_path"]),
        ).is_dir()
        assert resolve_managed_project_path(
            test_settings,
            str(dataset_payload["archive_path"]),
        ).is_file()

        model_payload = train_workflow_classifier(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload=dataset_payload,
            parameters={
                "architecture": "yolo11n-cls.pt",
                "run_name": "workflow-classifier",
                "epochs": 1,
                "image_size": 224,
                "batch": 1,
                "device": "cpu",
            },
            processor=_fake_classification_processor,
        )
        assert model_payload["model_id"] == "workflow-classifier-model"
        assert model_payload["purpose"] == "classifier"
        assert model_payload["task"] == "classify"
        assert model_payload["classification_dataset_id"] == dataset_payload[
            "classification_dataset_id"
        ]
        assert model_payload["metrics"]["accuracy"] == 0.95
        assert model_payload["registered_from_workflow"] is True


def test_classification_training_nodes_form_executable_graph(client: TestClient) -> None:
    project, version, _image_id = _classification_version(client)
    graph = WorkflowGraphRequest.model_validate(
        {
            "graph_id": "classification-training-loop",
            "name": "Classification dataset to model",
            "nodes": [
                {"node_id": "project", "node_type": "project_source", "parameters": {}},
                {
                    "node_id": "dataset",
                    "node_type": "dataset_version_source",
                    "parameters": {"dataset_version_id": version["id"]},
                },
                {
                    "node_id": "classification_dataset",
                    "node_type": "classification_dataset_materialize",
                    "parameters": {"mode": "image", "label_set": "species"},
                },
                {
                    "node_id": "train_classifier",
                    "node_type": "classification_training",
                    "parameters": {"epochs": 1},
                },
            ],
            "edges": [
                {
                    "edge_id": "project-dataset",
                    "source_node_id": "project",
                    "source_port_id": "project",
                    "target_node_id": "dataset",
                    "target_port_id": "project",
                },
                {
                    "edge_id": "dataset-classification",
                    "source_node_id": "dataset",
                    "source_port_id": "dataset",
                    "target_node_id": "classification_dataset",
                    "target_port_id": "dataset",
                },
                {
                    "edge_id": "classification-train",
                    "source_node_id": "classification_dataset",
                    "source_port_id": "classification_dataset",
                    "target_node_id": "train_classifier",
                    "target_port_id": "classification_dataset",
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
        "classification_dataset_materialize",
        "classification_training",
    ]
    train_step = next(step for step in plan.steps if step.node_type == "classification_training")
    assert train_step.output_types["model"] == ["model_reference"]

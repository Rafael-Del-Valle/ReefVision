from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    ExperimentRecord,
    Job,
    ModelRegistration,
    Project,
    TrainingRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.training import TrainingDraftWriteRequest, TrainingRunCreateRequest
from reefvision.schemas.workflow_graphs import WorkflowGraphRequest
from reefvision.services.workflow_graphs import WorkflowGraphService
from reefvision.services.workflow_training import (
    create_workflow_training_result,
    register_workflow_trained_model,
)
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_dataset_versions import (
    create_version,
    import_image,
    save_annotations,
    update_image,
)


class _FakeTrainingService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.draft_request: TrainingDraftWriteRequest | None = None
        self.draft_id = "workflow-training-draft"

    def create_draft(
        self,
        project_id: str,
        payload: TrainingDraftWriteRequest,
    ) -> SimpleNamespace:
        assert project_id
        self.draft_request = payload
        return SimpleNamespace(id=self.draft_id)

    def create_run(
        self,
        project_id: str,
        payload: TrainingRunCreateRequest,
    ) -> SimpleNamespace:
        assert payload.draft_id == self.draft_id
        assert self.draft_request is not None
        request = self.draft_request
        version = self.session.get(DatasetVersion, request.dataset_version_id)
        assert version is not None
        run = TrainingRun(
            project_id=project_id,
            draft_id=None,
            dataset_version_id=version.id,
            dataset_manifest_sha256=version.manifest_sha256,
            split_manifest_sha256="b" * 64,
            task=str(request.task),
            catalog_model_id=request.catalog_model_id,
            provider_id=str(request.provider_id),
            architecture=str(request.architecture),
            initial_checkpoint_source=request.initial_checkpoint_source,
            initial_checkpoint_model_id=request.initial_checkpoint_model_id,
            device=request.device,
            precision=request.precision,
            run_name=request.run_name or "workflow-test",
            notes=request.notes,
            random_seed=request.random_seed,
            tiling_config_json=dict(request.tiling_config),
            training_config_json=dict(request.training_config),
            tuning_config_json=dict(request.tuning_config),
            evaluation_config_json=dict(request.evaluation_config),
            resource_limits_json=dict(request.resource_limits),
            preflight_report_json={"status": "ready", "fake": True},
            draft_snapshot_json=request.model_dump(mode="json"),
            status="queued",
            stage="queued",
        )
        self.session.add(run)
        self.session.flush()
        job = Job(
            project_id=project_id,
            job_type="training",
            status="queued",
            progress_current=0,
            progress_total=max(1, int(request.training_config.get("epochs", 1))),
            request_json={"training_run_id": run.id},
            result_json={"stage": "queued"},
        )
        self.session.add(job)
        self.session.flush()
        run.job_id = job.id
        self.session.commit()
        return SimpleNamespace(id=run.id, job_id=job.id)


def _fake_training_factory(session: Session, settings: Settings) -> _FakeTrainingService:
    return _FakeTrainingService(session, settings)


def _fake_training_processor(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        run = session.get(TrainingRun, str(job.request_json["training_run_id"]))
        assert run is not None
        project = session.get(Project, run.project_id)
        assert project is not None
        relative_checkpoint = f"{project.storage_root}/training/{run.id}/fake-best.pt"
        checkpoint = resolve_managed_project_path(settings, relative_checkpoint)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b"reefvision-workflow-training-checkpoint")
        run.status = "completed"
        run.stage = "completed"
        run.metrics_json = {"metrics/mAP50(B)": 0.91}
        run.metrics_history_json = {"epoch": [1]}
        run.warnings_json = ["synthetic workflow training test"]
        run.artifact_manifest_json = {"checkpoint": relative_checkpoint}
        run.result_checkpoint_path = relative_checkpoint
        job.status = "succeeded"
        job.progress_current = max(job.progress_total, 1)
        job.result_json = {"stage": "completed", "result_checkpoint_path": relative_checkpoint}
        experiment = ExperimentRecord(
            project_id=run.project_id,
            training_run_id=run.id,
            dataset_version_id=run.dataset_version_id,
            dataset_manifest_sha256=run.dataset_manifest_sha256,
            split_manifest_sha256=run.split_manifest_sha256,
            task=run.task,
            provider_id=run.provider_id,
            architecture=run.architecture,
            summary_metrics_json=dict(run.metrics_json),
            comparison_warnings_json=list(run.warnings_json),
            artifact_manifest_json=dict(run.artifact_manifest_json),
            package_versions_json={"test": "synthetic"},
        )
        session.add(experiment)
        session.commit()
    return True


class _FakeModelService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def register_model_from_run(self, project_id: str, payload: Any) -> SimpleNamespace:
        run = self.session.get(TrainingRun, payload.training_run_id)
        assert run is not None and run.project_id == project_id
        experiment = self.session.query(ExperimentRecord).filter_by(training_run_id=run.id).one()
        return SimpleNamespace(
            id="registered-workflow-model",
            sha256="c" * 64,
            purpose="detector" if run.task == "detect" else "segmenter",
            task=run.task,
            provider_name=run.provider_id,
            provider_version="test",
            framework="test",
            metadata_json={
                "source_training_run_id": run.id,
                "source_experiment_id": experiment.id,
                "source_dataset_version_id": run.dataset_version_id,
                "source_dataset_manifest_sha256": run.dataset_manifest_sha256,
                "source_split_manifest_sha256": run.split_manifest_sha256,
            },
        )


def _fake_model_factory(session: Session, settings: Settings) -> _FakeModelService:
    return _FakeModelService(session, settings)


def _training_dataset(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    project = create_project(client, "Workflow training")
    imported = import_image(
        client,
        project["id"],
        filename="train.png",
        relative_path="workflow/train.png",
        color=(20, 80, 120),
    )
    image_id = str(imported["successful"][0]["image_id"])
    updated = update_image(client, image_id, group_key="fragment-1", annotation_status="reviewed")
    save_annotations(
        client,
        image_id,
        base_revision=int(updated["annotation_revision"]),
        annotation_status="reviewed",
        annotations=[
            {
                "id": "workflow-train-box",
                "label_class_id": project["label_classes"][0]["id"],
                "x_min": 5,
                "y_min": 5,
                "x_max": 25,
                "y_max": 25,
            }
        ],
    )
    version = create_version(client, project["id"], name="Workflow training v1")
    return project, version


def test_workflow_training_and_registration_preserve_lineage_without_real_gpu(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project, version = _training_dataset(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        result = create_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": project["id"],
                "dataset_version_id": version["id"],
                "manifest_sha256": version["manifest_sha256"],
            },
            parameters={
                "task": "detect",
                "architecture": "yolo11n.yaml",
                "run_name": "workflow-detect-test",
                "training_config": {"epochs": 1},
                "random_seed": 17,
            },
            training_service_factory=_fake_training_factory,
            processor=_fake_training_processor,
        )
        assert result["task"] == "detect"
        assert result["dataset_version_id"] == version["id"]
        assert result["dataset_manifest_sha256"] == version["manifest_sha256"]
        assert result["split_manifest_sha256"] == "b" * 64
        assert result["metrics"]["metrics/mAP50(B)"] == 0.91
        assert result["result_checkpoint_sha256"]
        assert result["result_checkpoint_size_bytes"] > 0
        assert result["experiment_id"]
        assert result["created_by_workflow"] is True

        registered = register_workflow_trained_model(
            session,
            test_settings,
            project_id=str(project["id"]),
            training_payload=result,
            parameters={"display_name": "Workflow detector v2"},
            model_service_factory=_fake_model_factory,
        )
        assert registered["model_id"] == "registered-workflow-model"
        assert registered["source_training_run_id"] == result["training_run_id"]
        assert registered["source_experiment_id"] == result["experiment_id"]
        assert registered["source_dataset_version_id"] == version["id"]
        assert registered["registered_from_workflow"] is True


def test_workflow_training_rejects_semantic_retraining_from_registered_model(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project, version = _training_dataset(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project["id"],
            purpose="detector",
            display_name="Seed detector",
            source_filename="seed.pt",
            managed_path=f"projects/{project['id']}/models/seed.pt",
            sha256="d" * 64,
            file_size_bytes=10,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            input_size_json={},
            metadata_json={"source_architecture": "yolo11n.yaml"},
        )
        session.add(model)
        session.commit()
        with pytest.raises(ValidationError, match="starts from scratch"):
            create_workflow_training_result(
                session,
                test_settings,
                project_id=str(project["id"]),
                dataset_payload={
                    "project_id": project["id"],
                    "dataset_version_id": version["id"],
                    "manifest_sha256": version["manifest_sha256"],
                },
                parameters={"task": "semantic_segment"},
                initial_model_payload={"model_id": model.id},
                training_service_factory=_fake_training_factory,
                processor=_fake_training_processor,
            )


def test_training_nodes_form_an_executable_dataset_to_registered_model_graph(
    client: TestClient,
) -> None:
    project, version = _training_dataset(client)
    graph = WorkflowGraphRequest.model_validate(
        {
            "graph_id": "training-loop",
            "name": "Dataset to trained model",
            "nodes": [
                {"node_id": "project", "node_type": "project_source", "parameters": {}},
                {
                    "node_id": "dataset",
                    "node_type": "dataset_version_source",
                    "parameters": {"dataset_version_id": version["id"]},
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
                    "edge_id": "dataset-train",
                    "source_node_id": "dataset",
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
        "model_training",
        "register_trained_model",
    ]
    training_step = next(step for step in plan.steps if step.node_type == "model_training")
    assert training_step.output_types["training"] == ["training_result"]
    register_step = next(step for step in plan.steps if step.node_type == "register_trained_model")
    assert register_step.output_types["model"] == ["model_reference"]

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.schemas.workflow_graphs import (
    WorkflowGraphRequest,
)
from reefvision.services.workflow_graphs import (
    WorkflowGraphService,
)
from reefvision.services.workflow_results_packages import (
    execute_training_results_package_adapter,
)
from reefvision.services.workflow_training import (
    create_workflow_training_result,
)
from reefvision.storage.datasets import (
    canonical_json_sha256,
)
from reefvision.storage.projects import (
    resolve_managed_project_path,
)
from reefvision.tests.test_workflow_training_phase10 import (
    _fake_training_factory,
    _fake_training_processor,
    _training_dataset,
)


def test_training_results_package_node_is_executable(
    client: TestClient,
) -> None:
    project, version = _training_dataset(client)

    graph = WorkflowGraphRequest.model_validate(
        {
            "graph_id": "training-results-package",
            "name": "Training to Results Package",
            "nodes": [
                {
                    "node_id": "project",
                    "node_type": "project_source",
                },
                {
                    "node_id": "dataset",
                    "node_type": "dataset_version_source",
                    "parameters": {
                        "dataset_version_id": (version["id"]),
                    },
                },
                {
                    "node_id": "train",
                    "node_type": "model_training",
                    "parameters": {
                        "task": "detect",
                        "architecture": "yolo11n.yaml",
                    },
                },
                {
                    "node_id": "package",
                    "node_type": ("training_results_package"),
                    "parameters": {
                        "checkpoint_mode": "none",
                    },
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
                    "edge_id": "train-package",
                    "source_node_id": "train",
                    "source_port_id": "training",
                    "target_node_id": "package",
                    "target_port_id": "training",
                },
            ],
        }
    )

    app = cast(
        FastAPI,
        client.app,
    )

    with app.state.session_factory() as session:
        plan = WorkflowGraphService(session).plan(
            str(project["id"]),
            graph,
        )

    assert plan.valid is True
    assert plan.executable is True

    package_step = next(step for step in plan.steps if step.node_type == "training_results_package")

    assert package_step.output_types["package"] == ["results_package"]


def test_workflow_results_package_preserves_training_lineage_and_verifies(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project, version = _training_dataset(client)

    app = cast(
        FastAPI,
        client.app,
    )

    with app.state.session_factory() as session:
        training = create_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": project["id"],
                "dataset_version_id": (version["id"]),
                "manifest_sha256": (version["manifest_sha256"]),
            },
            parameters={
                "task": "detect",
                "architecture": "yolo11n.yaml",
                "run_name": ("phase10-results-package"),
                "training_config": {
                    "epochs": 1,
                },
                "random_seed": 23,
            },
            workflow_run_id=("workflow-results-test"),
            workflow_node_run_id=("workflow-train-node"),
            training_service_factory=(_fake_training_factory),
            processor=(_fake_training_processor),
        )

        source = cast(
            WorkflowArtifact,
            SimpleNamespace(
                id="workflow-training-artifact",
                payload_json=training,
                payload_sha256=(canonical_json_sha256(training)),
            ),
        )

        outputs = execute_training_results_package_adapter(
            session,
            test_settings,
            str(project["id"]),
            {
                "include_excel": False,
                "include_machine_data": True,
                "include_native_artifacts": False,
                "include_logs": False,
                "checkpoint_mode": "none",
            },
            {
                "training": [source],
            },
        )

        assert len(outputs) == 1

        output = outputs[0]

        assert output["port_id"] == "package"
        assert output["data_type"] == "results_package"

        payload = output["payload"]

        assert payload["project_id"] == project["id"]
        assert payload["training_run_id"] == training["training_run_id"]

        assert payload["source_training_artifact_id"] == source.id

        assert payload["source_training_artifact_sha256"] == source.payload_sha256

        assert payload["dataset_manifest_sha256"] == version["manifest_sha256"]

        assert payload["split_manifest_sha256"] == training["split_manifest_sha256"]

        assert payload["result_checkpoint_sha256"] == training["result_checkpoint_sha256"]

        assert payload["verification_valid"] is True
        assert payload["verification_errors"] == []
        assert payload["verification_checked_files"] > 0

        assert len(payload["archive_sha256"]) == 64

        archive = resolve_managed_project_path(
            test_settings,
            payload["archive_path"],
        )

        package_directory = resolve_managed_project_path(
            test_settings,
            payload["package_directory_path"],
        )

        assert archive.is_file()
        assert package_directory.is_dir()

        assert archive.stat().st_size == payload["archive_size_bytes"]

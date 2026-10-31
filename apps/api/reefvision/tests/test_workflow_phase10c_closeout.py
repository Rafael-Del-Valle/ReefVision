from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import reefvision.jobs.video_tracking as tracking_job_module
import reefvision.services.workflow_execution as workflow_execution_module
import reefvision.services.workflow_runtime_adapters as runtime_adapters
from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    ModelRegistration,
    TrainingRun,
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.jobs import worker
from reefvision.jobs.workflow import (
    process_workflow_run_job,
)
from reefvision.ml.providers import DetectionModelMetadata
from reefvision.schemas.workflow_graphs import (
    WorkflowGraphRequest,
)
from reefvision.services.workflow_execution import (
    WorkflowExecutionService,
)
from reefvision.services.workflow_graphs import (
    WorkflowGraphService,
)
from reefvision.services.workflow_pose import (
    execute_pose_inference_adapter,
)
from reefvision.services.workflow_pose_training import (
    create_pose_workflow_training_result,
)
from reefvision.services.workflow_training import (
    register_workflow_trained_model,
)
from reefvision.storage.datasets import (
    canonical_json_sha256,
)
from reefvision.tests.test_annotations import (
    create_project,
)
from reefvision.tests.test_pose_provider_backends import (
    _FakeCanonicalPoseVideoProvider,
    _import_pose_video,
    _pose_model,
)
from reefvision.tests.test_workflow_pose_registration_phase10 import (
    _fake_pose_model_factory,
    _FakePoseRegistrationService,
    _FakeTrainedPoseProvider,
)
from reefvision.tests.test_workflow_pose_review_resume_phase10 import (
    _review_temporal_blockers,
    _save_and_queue,
    _tracking_job_count,
)
from reefvision.tests.test_workflow_pose_training_phase10 import (
    _fake_pose_processor,
    _frozen_dataset,
    _seed_model,
)


def _simple_graph() -> dict[str, object]:
    return {
        "graph_id": ("phase10c-recovery"),
        "name": ("Phase 10C recovery"),
        "nodes": [
            {
                "node_id": "project",
                "node_type": ("project_source"),
            },
            {
                "node_id": "images",
                "node_type": ("project_images"),
            },
        ],
        "edges": [
            {
                "edge_id": ("project-images"),
                "source_node_id": ("project"),
                "source_port_id": ("project"),
                "target_node_id": ("images"),
                "target_port_id": ("project"),
            }
        ],
    }


def _prime_interrupted_run(
    client: TestClient,
    project_id: str,
) -> tuple[
    str,
    str,
    str,
]:
    graph = _simple_graph()

    run_id, job_id = _save_and_queue(
        client,
        project_id,
        graph,
    )

    app = cast(
        FastAPI,
        client.app,
    )

    with app.state.session_factory() as session:
        run = session.get(
            WorkflowRun,
            run_id,
        )

        assert run is not None

        record = session.get(
            WorkflowGraphRecord,
            run.workflow_graph_record_id,
        )

        assert record is not None

        parsed = WorkflowGraphRequest.model_validate(record.graph_json)

        plan = WorkflowGraphService(session).plan(
            project_id,
            parsed,
        )

        first = plan.steps[0]

        first_node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_id == first.node_id,
            )
        )

        second_node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_id == plan.steps[1].node_id,
            )
        )

        assert first_node is not None
        assert second_node is not None

        service = WorkflowExecutionService(
            session,
            app.state.settings,
        )

        specifications = service.execute_node(
            project_id=project_id,
            run_id=run_id,
            node_run=first_node,
            step=first,
            inputs={},
        )

        assert len(specifications) == 1

        artifact = service.persist_artifact(
            run_id=run_id,
            node_run=first_node,
            specification=(specifications[0]),
        )

        first_node.status = "succeeded"
        first_node.output_artifact_ids_json = [artifact.id]
        first_node.result_json = {
            "outputs": [
                {
                    "artifact_id": (artifact.id),
                    "port_id": (artifact.producer_port_id),
                    "data_type": (artifact.data_type),
                    "payload_sha256": (artifact.payload_sha256),
                }
            ]
        }

        second_node.status = "running"

        run.status = "running"

        job = session.get(
            Job,
            job_id,
        )

        assert job is not None

        job.status = "running"

        session.commit()

        return (
            run_id,
            job_id,
            artifact.id,
        )


def test_interrupted_workflow_reuses_succeeded_artifacts_and_reopens_with_provenance(
    client: TestClient,
) -> None:
    project = create_project(
        client,
        "Phase 10C restart recovery",
    )

    run_id, job_id, first_artifact_id = _prime_interrupted_run(
        client,
        str(project["id"]),
    )

    app = cast(
        FastAPI,
        client.app,
    )

    recovered = worker.recover_interrupted_jobs(
        app.state.session_factory,
        app.state.settings,
    )

    assert recovered >= 1

    with app.state.session_factory() as session:
        run = session.get(
            WorkflowRun,
            run_id,
        )
        job = session.get(
            Job,
            job_id,
        )

        assert run is not None
        assert job is not None

        assert run.status == "queued"
        assert job.status == "queued"

        nodes = {
            item.node_id: item
            for item in session.scalars(
                select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
            )
        }

        assert nodes["project"].status == "succeeded"

        assert nodes["images"].status == "pending"

        assert nodes["project"].output_artifact_ids_json == [first_artifact_id]

        history = list(
            dict(run.result_json or {}).get(
                "recovery_history",
                [],
            )
        )

        assert history
        assert history[-1]["action"] == "requeued_on_startup"

    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    detail = client.get(f"/api/v1/workflow-runs/{run_id}")

    assert detail.status_code == 200, detail.text

    payload = detail.json()

    assert payload["run"]["status"] == "succeeded"

    nodes = {item["node_id"]: item for item in payload["nodes"]}

    assert nodes["project"]["output_artifact_ids_json"] == [first_artifact_id]

    result = payload["run"]["result_json"]

    provenance = result["provenance_manifest"]

    assert canonical_json_sha256(provenance) == result["provenance_sha256"]

    assert provenance["recovery_history"]

    # A second request represents reopening/reloading the saved run
    # through a fresh API database session.
    reopened = client.get(f"/api/v1/workflow-runs/{run_id}")

    assert reopened.status_code == 200

    reopened_result = reopened.json()["run"]["result_json"]

    assert reopened_result["provenance_sha256"] == result["provenance_sha256"]


@pytest.mark.parametrize("payload_corruption", ["changed_values", "equivalent_pairs"])
def test_corrupted_succeeded_artifact_blocks_resume_instead_of_rerunning(
    client: TestClient,
    payload_corruption: str,
) -> None:
    project = create_project(
        client,
        "Phase 10C corruption guard",
    )

    run_id, job_id, artifact_id = _prime_interrupted_run(
        client,
        str(project["id"]),
    )

    app = cast(
        FastAPI,
        client.app,
    )

    worker.recover_interrupted_jobs(
        app.state.session_factory,
        app.state.settings,
    )

    with app.state.session_factory() as session:
        artifact = session.get(
            WorkflowArtifact,
            artifact_id,
        )

        assert artifact is not None

        if payload_corruption == "equivalent_pairs":
            # The prior verifier coerced this JSON array back to a dict,
            # producing the original SHA-256 despite a changed stored type.
            artifact.payload_json = cast(Any, list(artifact.payload_json.items()))
            assert canonical_json_sha256(dict(artifact.payload_json)) == artifact.payload_sha256
        else:
            artifact.payload_json = {"tampered": True}

        session.commit()

    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            job_id,
        )
        is False
    )

    with app.state.session_factory() as session:
        run = session.get(
            WorkflowRun,
            run_id,
        )

        assert run is not None
        assert run.status == "failed"

        project_node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_id == "project",
            )
        )

        assert project_node is not None

        assert "integrity check failed" in (project_node.error_message or "")


def test_pose_inference_retry_reuses_completed_tracking_child(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Phase 10C pose child reuse",
    )

    video = _import_pose_video(
        client,
        str(project["id"]),
        monkeypatch,
    )

    app = cast(
        FastAPI,
        client.app,
    )

    model_id = _pose_model(
        client,
        project,
        app,
        with_schema=True,
    )

    monkeypatch.setattr(
        tracking_job_module,
        "video_tracking_provider_for_name",
        lambda _name: _FakeCanonicalPoseVideoProvider(),
    )

    video_artifact = cast(
        WorkflowArtifact,
        SimpleNamespace(
            payload_json={
                "project_id": (project["id"]),
                "video_id": (video["id"]),
            }
        ),
    )

    model_artifact = cast(
        WorkflowArtifact,
        SimpleNamespace(
            payload_json={
                "project_id": (project["id"]),
                "model_id": model_id,
            }
        ),
    )

    parameters = {
        "device": "cpu",
        "__workflow_run_id": ("phase10c-pose-retry"),
        "__workflow_node_run_id": ("phase10c-pose-node"),
    }

    with app.state.session_factory() as session:
        first = execute_pose_inference_adapter(
            session,
            app.state.settings,
            str(project["id"]),
            parameters,
            {
                "video": [video_artifact],
                "model": [model_artifact],
            },
        )

        job_count = _tracking_job_count(
            app,
            str(project["id"]),
        )

        second = execute_pose_inference_adapter(
            session,
            app.state.settings,
            str(project["id"]),
            parameters,
            {
                "video": [video_artifact],
                "model": [model_artifact],
            },
        )

    assert (
        _tracking_job_count(
            app,
            str(project["id"]),
        )
        == job_count
    )

    assert first[0]["payload"]["tracking_job_id"] == second[0]["payload"]["tracking_job_id"]

    assert first[0]["payload"]["track_ids"] == second[0]["payload"]["track_ids"]


def test_pose_training_retry_reuses_completed_training_science(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, dataset = _frozen_dataset(
        client,
        monkeypatch,
    )

    app = cast(
        FastAPI,
        client.app,
    )

    seed_model_id = _seed_model(
        app,
        project,
        dataset,
    )

    calls = {
        "count": 0,
    }

    def processor(
        settings: Settings,
        factory: Any,
        job_id: str,
    ) -> bool:
        calls["count"] += 1

        return _fake_pose_processor(
            settings,
            factory,
            job_id,
        )

    kwargs: dict[str, Any] = {
        "project_id": str(project["id"]),
        "dataset_payload": {
            "project_id": (project["id"]),
            "dataset_id": (dataset["id"]),
            "manifest_sha256": (dataset["manifest_sha256"]),
        },
        "initial_model_payload": {
            "model_id": (seed_model_id),
        },
        "parameters": {
            "run_name": ("phase10c-idempotent-pose"),
            "device": "cpu",
            "precision": "fp32",
            "random_seed": 51,
            "training_config": {
                "epochs": 1,
            },
        },
        "workflow_run_id": ("phase10c-training-retry"),
        "workflow_node_run_id": ("phase10c-training-node"),
        "processor": processor,
    }

    with app.state.session_factory() as session:
        first = create_pose_workflow_training_result(
            session,
            test_settings,
            **kwargs,
        )

        second = create_pose_workflow_training_result(
            session,
            test_settings,
            **kwargs,
        )

        matching = [
            run
            for run in session.scalars(
                select(TrainingRun).where(
                    TrainingRun.project_id == str(project["id"]),
                    TrainingRun.task == "pose",
                )
            )
            if dict(run.draft_snapshot_json or {}).get("workflow_node_run_id")
            == "phase10c-training-node"
        ]

    assert calls["count"] == 1

    assert first["training_run_id"] == second["training_run_id"]

    assert len(matching) == 1


def test_phase10c_saved_scientist_graph_runs_to_verified_terminal_outputs_and_reopens(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(
        client,
        "Phase 10C complete scientist workflow",
    )

    video = _import_pose_video(
        client,
        str(project["id"]),
        monkeypatch,
    )

    app = cast(
        FastAPI,
        client.app,
    )

    seed_model_id = _pose_model(
        client,
        project,
        app,
        with_schema=True,
    )

    phase10c_seed_checkpoint_sha256 = hashlib.sha256(b"pose-checkpoint").hexdigest()

    with app.state.session_factory() as session:
        seed_registration = session.get(
            ModelRegistration,
            seed_model_id,
        )

        assert seed_registration is not None

        seed_registration.sha256 = phase10c_seed_checkpoint_sha256

        session.commit()

    def inspect_phase10c_three_keypoint_checkpoint(
        self: object,
        model_path: Path,
    ) -> DetectionModelMetadata:
        del self

        assert model_path.is_file()

        return DetectionModelMetadata(
            framework="ultralytics",
            task="pose",
            provider_name="ultralytics",
            provider_version="test",
            class_labels=["organism"],
            input_size={
                "imgsz": 640,
            },
            metadata={
                "pose_keypoint_shape": [
                    3,
                    3,
                ],
                "proposal_geometry": ("keypoints+bbox"),
            },
        )

    original_register_model_path = _FakePoseRegistrationService._register_model_path

    def register_phase10c_three_keypoint_checkpoint(
        self: _FakePoseRegistrationService,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        registered = original_register_model_path(
            self,
            *args,
            **kwargs,
        )

        model = self._model(registered.id)

        metadata = dict(model.metadata_json or {})

        metadata["pose_keypoint_shape"] = [
            3,
            3,
        ]

        model.metadata_json = metadata

        self.session.commit()

        return registered

    monkeypatch.setattr(
        _FakeTrainedPoseProvider,
        "inspect_model",
        inspect_phase10c_three_keypoint_checkpoint,
    )

    monkeypatch.setattr(
        _FakePoseRegistrationService,
        "_register_model_path",
        register_phase10c_three_keypoint_checkpoint,
    )

    monkeypatch.setattr(
        tracking_job_module,
        "video_tracking_provider_for_name",
        lambda _name: _FakeCanonicalPoseVideoProvider(),
    )

    training_calls = {
        "count": 0,
    }

    def fake_pose_training_adapter(
        session: Session,
        settings: Settings,
        project_id: str,
        parameters: dict[str, Any],
        inputs: dict[
            str,
            list[WorkflowArtifact],
        ],
    ) -> list[dict[str, Any]]:
        training_calls["count"] += 1

        dataset_payload = dict(inputs["dataset"][0].payload_json or {})

        initial_model_payload = dict(inputs["initial_model"][0].payload_json or {})

        validation_artifacts = list(
            inputs.get(
                "validation_dataset",
                [],
            )
        )

        validation_payload = (
            dict(validation_artifacts[0].payload_json or {}) if validation_artifacts else None
        )

        result = create_pose_workflow_training_result(
            session,
            settings,
            project_id=project_id,
            dataset_payload=(dataset_payload),
            validation_dataset_payload=(validation_payload),
            initial_model_payload=(initial_model_payload),
            parameters=parameters,
            workflow_run_id=str(parameters.get("__workflow_run_id") or "") or None,
            workflow_node_run_id=str(parameters.get("__workflow_node_run_id") or "") or None,
            processor=(_fake_pose_processor),
        )

        return [
            {
                "port_id": ("training"),
                "data_type": ("training_result"),
                "payload": result,
            }
        ]

    monkeypatch.setitem(
        runtime_adapters._ADAPTERS,
        "pose_model_training",
        fake_pose_training_adapter,
    )

    def fake_registration(
        session: Session,
        settings: Settings,
        *,
        project_id: str,
        training_payload: dict[
            str,
            Any,
        ],
        parameters: dict[
            str,
            Any,
        ],
    ) -> dict[str, Any]:
        return register_workflow_trained_model(
            session,
            settings,
            project_id=project_id,
            training_payload=(training_payload),
            parameters=parameters,
            model_service_factory=(_fake_pose_model_factory),
        )

    monkeypatch.setattr(
        workflow_execution_module,
        "register_workflow_trained_model",
        fake_registration,
    )

    graph: dict[str, object] = {
        "graph_id": ("phase10c-complete-scientist-flow"),
        "name": ("Phase 10C complete scientist flow"),
        "nodes": [
            {
                "node_id": "project",
                "node_type": ("project_source"),
            },
            {
                "node_id": "video",
                "node_type": ("project_video_source"),
                "parameters": {
                    "video_id": (video["id"]),
                },
            },
            {
                "node_id": "seed",
                "node_type": ("registered_model_source"),
                "parameters": {
                    "model_id": (seed_model_id),
                },
            },
            {
                "node_id": "pose",
                "node_type": ("pose_inference"),
                "parameters": {
                    "device": "cpu",
                },
            },
            {
                "node_id": "temporal",
                "node_type": ("pose_temporal_association"),
            },
            {
                "node_id": "pose_review",
                "node_type": ("pose_review_gate"),
            },
            {
                "node_id": "al",
                "node_type": ("pose_active_learning"),
                "parameters": {
                    "requested_size": 1,
                    "diversity_balance": (False),
                },
            },
            {
                "node_id": "al_review",
                "node_type": ("pose_active_learning_review_gate"),
            },
            {
                "node_id": "freeze",
                "node_type": ("pose_training_dataset_freeze"),
                "parameters": {
                    "name": ("Phase 10C verified pose truth"),
                },
            },
            {
                "node_id": "pose_export",
                "node_type": ("pose_training_export"),
                "parameters": {
                    "format": "native",
                },
            },
            {
                "node_id": "train",
                "node_type": ("pose_model_training"),
                "parameters": {
                    "run_name": ("phase10c-pose-retrain"),
                    "device": "cpu",
                    "precision": "fp32",
                    "random_seed": 61,
                    "training_config": {
                        "epochs": 1,
                    },
                },
            },
            {
                "node_id": "register",
                "node_type": ("register_trained_model"),
            },
            {
                "node_id": "results",
                "node_type": ("training_results_package"),
                "parameters": {
                    "include_excel": False,
                    "include_machine_data": (True),
                    "include_native_artifacts": (False),
                    "include_logs": False,
                    "checkpoint_mode": ("none"),
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-video",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "video",
                "target_port_id": "project",
            },
            {
                "edge_id": "project-seed",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "seed",
                "target_port_id": "project",
            },
            {
                "edge_id": "video-pose",
                "source_node_id": "video",
                "source_port_id": "video",
                "target_node_id": "pose",
                "target_port_id": "video",
            },
            {
                "edge_id": "seed-pose",
                "source_node_id": "seed",
                "source_port_id": "model",
                "target_node_id": "pose",
                "target_port_id": "model",
            },
            {
                "edge_id": "pose-temporal",
                "source_node_id": "pose",
                "source_port_id": "poses",
                "target_node_id": "temporal",
                "target_port_id": "poses",
            },
            {
                "edge_id": "temporal-review",
                "source_node_id": "temporal",
                "source_port_id": "tracks",
                "target_node_id": "pose_review",
                "target_port_id": "tracks",
            },
            {
                "edge_id": "review-al",
                "source_node_id": "pose_review",
                "source_port_id": "poses",
                "target_node_id": "al",
                "target_port_id": "tracks",
            },
            {
                "edge_id": "al-review",
                "source_node_id": "al",
                "source_port_id": "round",
                "target_node_id": "al_review",
                "target_port_id": "round",
            },
            {
                "edge_id": "review-freeze",
                "source_node_id": "al_review",
                "source_port_id": "verified_round",
                "target_node_id": "freeze",
                "target_port_id": "verified_round",
            },
            {
                "edge_id": "freeze-export",
                "source_node_id": "freeze",
                "source_port_id": "dataset",
                "target_node_id": "pose_export",
                "target_port_id": "dataset",
            },
            {
                "edge_id": "freeze-train",
                "source_node_id": "freeze",
                "source_port_id": "dataset",
                "target_node_id": "train",
                "target_port_id": "dataset",
            },
            {
                "edge_id": "seed-train",
                "source_node_id": "seed",
                "source_port_id": "model",
                "target_node_id": "train",
                "target_port_id": "initial_model",
            },
            {
                "edge_id": "train-register",
                "source_node_id": "train",
                "source_port_id": "training",
                "target_node_id": "register",
                "target_port_id": "training",
            },
            {
                "edge_id": "train-results",
                "source_node_id": "train",
                "source_port_id": "training",
                "target_node_id": "results",
                "target_port_id": "training",
            },
        ],
    }

    plan = client.post(
        (f"/api/v1/projects/{project['id']}/workflow-graphs/plan"),
        json=graph,
    )

    assert plan.status_code == 200, plan.text

    assert plan.json()["executable"] is True
    # The saved workflow's omitted mode must resolve through the catalog's
    # explicit auto default rather than an invalid null.
    training_step = next(step for step in plan.json()["steps"] if step["node_id"] == "train")
    assert training_step["parameters"]["initialization_mode"] == "auto"

    run_id, job_id = _save_and_queue(
        client,
        str(project["id"]),
        graph,
    )

    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    first_pause = client.get(f"/api/v1/workflow-runs/{run_id}").json()

    assert first_pause["run"]["status"] == "waiting_for_review"

    first_nodes = {item["node_id"]: item for item in first_pause["nodes"]}

    assert first_nodes["pose_review"]["status"] == "waiting_for_review"

    first_artifacts = {item["data_type"]: item for item in first_pause["artifacts"]}

    pose_payload = first_artifacts["pose_tracks"]["payload_json"]

    tracking_jobs_before = _tracking_job_count(
        app,
        str(project["id"]),
    )

    for track_id in pose_payload["track_ids"]:
        _review_temporal_blockers(
            client,
            str(track_id),
        )

    resumed = client.post(
        (f"/api/v1/workflow-node-runs/{first_nodes['pose_review']['id']}/resume-review"),
        json={
            "reviewed_by": ("scientist"),
            "note": ("Phase 10C temporal pose review complete."),
        },
    )

    assert resumed.status_code == 202, resumed.text

    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    second_pause = client.get(f"/api/v1/workflow-runs/{run_id}").json()

    assert second_pause["run"]["status"] == "waiting_for_review"

    second_nodes = {item["node_id"]: item for item in second_pause["nodes"]}

    assert second_nodes["al_review"]["status"] == "waiting_for_review"

    second_artifacts = {item["data_type"]: item for item in second_pause["artifacts"]}

    round_payload = second_artifacts["pose_active_learning_round"]["payload_json"]

    for candidate_id in round_payload["candidate_ids"]:
        response = client.put(
            (f"/api/v1/pose-active-learning-candidates/{candidate_id}/review"),
            json={
                "action": "verify",
                "reviewed_by": ("scientist"),
                "note": ("Verified for the Phase 10C retraining loop."),
            },
        )

        assert response.status_code == 200, response.text

    resumed = client.post(
        (f"/api/v1/workflow-node-runs/{second_nodes['al_review']['id']}/resume-review"),
        json={
            "reviewed_by": ("scientist"),
            "note": ("Phase 10C Active Learning review complete."),
        },
    )

    assert resumed.status_code == 202, resumed.text

    terminal_execution = process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    if not terminal_execution:
        failure_response = client.get(f"/api/v1/workflow-runs/{run_id}")

        assert failure_response.status_code == 200, failure_response.text

        failure_payload = failure_response.json()

        run_state = dict(failure_payload["run"])

        node_states = [
            {
                "node_id": item["node_id"],
                "node_type": item["node_type"],
                "status": item["status"],
                "error_message": item.get("error_message"),
                "result_json": item.get("result_json"),
                "input_artifact_ids": item.get("input_artifact_ids_json"),
                "output_artifact_ids": item.get("output_artifact_ids_json"),
            }
            for item in failure_payload["nodes"]
        ]

        failed_nodes = [item for item in node_states if item["status"] == "failed"]

        artifact_states = [
            {
                "id": item["id"],
                "data_type": item["data_type"],
                "producer_node_run_id": (item["producer_node_run_id"]),
                "producer_port_id": (item["producer_port_id"]),
                "payload_sha256": (item["payload_sha256"]),
            }
            for item in failure_payload["artifacts"]
        ]

        pytest.fail(
            "\nPHASE 10C TERMINAL WORKFLOW FAILURE\n"
            f"RUN STATUS: {run_state.get('status')!r}\n"
            f"RUN ERROR: {run_state.get('error_message')!r}\n"
            f"RUN RESULT: {run_state.get('result_json')!r}\n"
            f"FAILED NODES: {failed_nodes!r}\n"
            f"ALL NODES: {node_states!r}\n"
            f"ARTIFACTS: {artifact_states!r}"
        )

    final = client.get(f"/api/v1/workflow-runs/{run_id}")

    assert final.status_code == 200, final.text

    payload = final.json()

    assert payload["run"]["status"] == "succeeded"

    assert all(node["status"] == "succeeded" for node in payload["nodes"])

    artifacts_by_type: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for artifact in payload["artifacts"]:
        artifacts_by_type.setdefault(
            str(artifact["data_type"]),
            [],
        ).append(artifact)

    assert "reviewed_pose_tracks" in artifacts_by_type

    assert "pose_training_dataset" in artifacts_by_type

    assert "pose_training_package" in artifacts_by_type

    assert "training_result" in artifacts_by_type

    assert "results_package" in artifacts_by_type

    registered_models = [
        item
        for item in artifacts_by_type["model_reference"]
        if item["payload_json"].get("source_training_run_id")
    ]

    assert len(registered_models) == 1

    assert registered_models[0]["payload_json"]["pose_schema_content_hash"]

    results = artifacts_by_type["results_package"][0]["payload_json"]

    assert results["verification_valid"] is True

    assert (
        _tracking_job_count(
            app,
            str(project["id"]),
        )
        == tracking_jobs_before
        == 1
    )

    assert training_calls["count"] == 1

    run_result = payload["run"]["result_json"]

    provenance = run_result["provenance_manifest"]

    assert canonical_json_sha256(provenance) == run_result["provenance_sha256"]

    terminal_types = {item["data_type"] for item in provenance["terminal_artifacts"]}

    assert {
        "pose_training_package",
        "model_reference",
        "results_package",
    } <= terminal_types

    review_nodes = {
        item["node_id"]: item for item in provenance["nodes"] if item["review_approval"] is not None
    }

    assert {
        "pose_review",
        "al_review",
    } <= set(review_nodes)

    # Reopen/read the same saved run again. Its terminal provenance
    # fingerprint must remain identical.
    reopened = client.get(f"/api/v1/workflow-runs/{run_id}")

    assert reopened.status_code == 200

    assert (
        reopened.json()["run"]["result_json"]["provenance_sha256"]
        == run_result["provenance_sha256"]
    )

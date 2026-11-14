from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import Job, Project
from reefvision.domain.errors import WorkflowExecutionCancelled
from reefvision.schemas.pose_evaluation import PoseEvaluationComparisonCreateRequest
from reefvision.services.workflow_node_registry_v1 import workflow_node_registry
from reefvision.services.workflow_pose_evaluation import (
    create_pose_workflow_evaluation_result,
)


def test_pose_evaluation_node_has_typed_multiple_model_input() -> None:
    node = workflow_node_registry()["pose_model_evaluation"]

    assert node.executable is True
    assert [(port.port_id, port.accepted_types, port.multiple) for port in node.input_ports] == [
        ("dataset", ["pose_training_dataset"], False),
        ("models", ["model_reference"], True),
    ]
    assert node.output_ports[0].accepted_types == ["pose_evaluation_comparison"]


def test_workflow_evaluation_executes_production_child_and_returns_provenance(
    client: TestClient,
    monkeypatch,
) -> None:
    from reefvision.services.pose_evaluation_comparison import PoseEvaluationComparisonService

    job = Job(
        id="workflow-comparison-job",
        project_id="project-1",
        job_type="pose_evaluation",
        status="queued",
        progress_current=0,
        progress_total=2,
        request_json={"schema_version": "pose-evaluation-comparison-0001"},
        result_json={"stage": "queued"},
    )

    def submit(
        _service: PoseEvaluationComparisonService,
        project_id: str,
        payload: PoseEvaluationComparisonCreateRequest,
        **kwargs: object,
    ) -> object:
        assert project_id == "project-1"
        assert payload.model_ids == ["model-1", "model-2"]
        assert kwargs["submission_context"] == {
            "workflow_run_id": "workflow-run-1",
            "workflow_node_run_id": "workflow-node-run-1",
        }
        with client.app.state.session_factory() as session:
            session.add(job)
            session.commit()
        return SimpleNamespace(id=job.id)

    monkeypatch.setattr(PoseEvaluationComparisonService, "submit", submit)

    with client.app.state.session_factory() as session:
        session.add(
            Project(
                id="project-1",
                name="Workflow comparison",
                slug="workflow-comparison",
                storage_root="projects/workflow-comparison",
            )
        )
        session.commit()

    def processor(_settings: object, factory: object, job_id: str) -> bool:
        with factory() as session:  # type: ignore[operator]
            persisted = session.get(Job, job_id)
            assert persisted is not None
            persisted.status = "succeeded"
            persisted.progress_current = persisted.progress_total
            persisted.result_json = {
                "schema_version": "reefvision-pose-comparison-0001",
                "stage": "completed",
                "evaluation_run_ids": ["run-1", "run-2"],
                "models": [{"model_id": "model-1"}, {"model_id": "model-2"}],
                "exclusions": [],
                "warnings": [],
                "report_sha256": "a" * 64,
            }
            session.commit()
        return True

    with client.app.state.session_factory() as session:
        result = create_pose_workflow_evaluation_result(
            session,
            client.app.state.settings,
            project_id="project-1",
            dataset_payload={
                "project_id": "project-1",
                "dataset_id": "dataset-1",
                "manifest_sha256": "b" * 64,
            },
            model_payloads=[
                {"project_id": "project-1", "model_id": "model-1"},
                {"project_id": "project-1", "model_id": "model-2"},
            ],
            parameters={"device": "cpu"},
            workflow_run_id="workflow-run-1",
            workflow_node_run_id="workflow-node-run-1",
            processor=processor,
        )

    assert result["comparison_job_id"] == job.id
    assert result["evaluation_run_ids"] == ["run-1", "run-2"]
    assert result["report_sha256"] == "a" * 64
    assert result["workflow_run_id"] == "workflow-run-1"


def test_workflow_child_cancellation_remains_cancellation(
    client: TestClient,
    monkeypatch,
) -> None:
    from reefvision.services.pose_evaluation_comparison import PoseEvaluationComparisonService

    with client.app.state.session_factory() as session:
        session.add(
            Project(
                id="project-c",
                name="Cancelled",
                slug="cancelled",
                storage_root="projects/c",
            )
        )
        session.add(
            Job(
                id="cancelled-child",
                project_id="project-c",
                job_type="pose_evaluation",
                status="cancelled",
                progress_current=0,
                progress_total=1,
                request_json={},
                result_json={"stage": "cancelled"},
            )
        )
        session.commit()

    monkeypatch.setattr(
        PoseEvaluationComparisonService,
        "submit",
        lambda *_args, **_kwargs: SimpleNamespace(id="cancelled-child"),
    )
    with client.app.state.session_factory() as session, pytest.raises(
        WorkflowExecutionCancelled
    ):
        create_pose_workflow_evaluation_result(
            session,
            client.app.state.settings,
            project_id="project-c",
            dataset_payload={"dataset_id": "dataset-c"},
            model_payloads=[{"model_id": "model-c"}],
            parameters={},
            workflow_run_id=None,
            workflow_node_run_id=None,
            processor=lambda *_args, **_kwargs: True,
        )

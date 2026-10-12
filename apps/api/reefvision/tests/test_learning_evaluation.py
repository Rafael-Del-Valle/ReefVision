from __future__ import annotations

from hashlib import sha256
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import Job, ModelRegistration, PredictionProposal, TrainingRun
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.domain.learning_evaluation import ScoredBox, detection_metrics
from reefvision.schemas.learning_evaluation import LearningEvaluationRequest
from reefvision.services.learning_evaluation import LearningEvaluationService
from reefvision.services.project_learning import ProjectLearningService
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_project_learning import config, seed
from reefvision.tests.test_training_workspace import _patch_training_foundation


def box(score: float = 1.0, *, x: float = 1, label: str = "coral") -> ScoredBox:
    return ScoredBox("image", label, score, (x, 1, x + 10, 11))


def test_perfect_detector_has_correct_heldout_metrics() -> None:
    result = detection_metrics([box()], [box(0.9)], image_count=1)
    assert result.map50 == 1 and result.precision == 1 and result.recall == 1
    assert result.count_bias_per_image == 0


def test_duplicate_and_wrong_class_detections_are_false_positives() -> None:
    result = detection_metrics([box()], [box(0.9), box(0.8), box(0.7, label="fish")], image_count=1)
    assert result.precision == pytest.approx(1 / 3)
    assert result.recall == 1
    assert result.count_bias_per_image == 2
    assert result.per_class["coral"].false_positives == 1
    assert result.per_class["fish"].false_positives == 1


def test_unmatched_ground_truth_and_low_confidence_predictions_are_not_hidden() -> None:
    result = detection_metrics([box(), box(x=30)], [box(0.2)], image_count=1)
    assert result.map50 == pytest.approx(0.5)
    assert result.recall == 0 and result.precision == 0
    assert result.count_bias_per_image == -2


def test_empty_predictions_have_zero_quality_not_perfect_background_score() -> None:
    result = detection_metrics([box()], [], image_count=1)
    assert result.map50 == 0 and result.recall == 0
    assert result.per_class["coral"].false_negatives == 1


def evaluation_fixture(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    _patch_training_foundation(monkeypatch)
    project = seed(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        result = ProjectLearningService(session, app.state.settings).improve(
            project["id"], config()
        )
        assert result.run is not None and result.dataset_version is not None
        run = session.get(TrainingRun, result.run.id)
        assert run is not None
        run.status = "completed"
        path = f"projects/{project['id']}/models/evaluation.pt"
        absolute = resolve_managed_project_path(app.state.settings, path)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes(b"mock-checkpoint")
        model = ModelRegistration(
            project_id=project["id"],
            purpose="detector",
            display_name="Candidate",
            source_filename="evaluation.pt",
            managed_path=path,
            sha256=sha256(b"mock-checkpoint").hexdigest(),
            file_size_bytes=15,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="8.3.228",
            metadata_json={"source_training_run_id": run.id},
        )
        session.add(model)
        session.commit()
        project.update(model_id=model.id, version_id=result.dataset_version.id)
    return project


def test_evaluation_queues_only_frozen_holdout_and_requires_completed_inference(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = evaluation_fixture(client, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        service = LearningEvaluationService(session, app.state.settings)
        request = LearningEvaluationRequest(
            dataset_version_id=project["version_id"],
            candidate_model_id=project["model_id"],
            minimum_images=2,
            minimum_objects_per_class=2,
        )
        result = service.create(project["id"], request)
        assert result.status == "waiting" and not result.promotion_eligible
        with pytest.raises(ConflictError):
            service.promote(project["id"], result.id)
        child = session.get(Job, result.candidate_job_id)
        assert child is not None
        learning = ProjectLearningService(session, app.state.settings)
        items = learning.datasets.get_version_items(project["version_id"])
        heldout = [item for item in items if item.split == "validation"]
        assert set(child.request_json["image_ids"]) == {item.image_id for item in heldout}
        model = session.get(ModelRegistration, project["model_id"])
        assert model is not None
        for item in heldout:
            for annotation in item.annotation_snapshot_json:
                session.add(
                    PredictionProposal(
                        project_id=project["id"],
                        image_id=item.image_id,
                        model_id=model.id,
                        inference_job_id=child.id,
                        model_checksum=model.sha256,
                        label_class_id=annotation["label_class_id"],
                        predicted_label=annotation["class_name"],
                        confidence=0.95,
                        x_min=annotation["x_min"],
                        y_min=annotation["y_min"],
                        x_max=annotation["x_max"],
                        y_max=annotation["y_max"],
                        review_status="evaluation_only",
                        provenance_json={"evaluation_only": True},
                    )
                )
        child.status = "succeeded"
        child.progress_current = child.progress_total
        child.result_json = {"proposal_count": sum(item.annotation_count for item in heldout)}
        session.commit()
        final = service.get(project["id"], result.id)
        assert final.promotion_eligible and final.candidate_metrics is not None
        assert final.candidate_metrics.map50 == 1
        deployed = service.promote(project["id"], result.id)
        assert service.active_model_id(project["id"]) == model.id
        assert deployed.active_model_id == model.id
        rollback = service.rollback(project["id"], deployed.id)
        assert rollback.active_model_id is None
        assert service.active_model_id(project["id"]) is None
        assert (
            session.scalar(select(PredictionProposal.review_status).limit(1)) == "evaluation_only"
        )


def test_learning_evaluation_api_queues_the_frozen_holdout(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = evaluation_fixture(client, monkeypatch)
    response = client.post(
        f"/api/v1/projects/{project['id']}/learning/evaluations",
        json={
            "dataset_version_id": project["version_id"],
            "candidate_model_id": project["model_id"],
            "minimum_images": 2,
            "minimum_objects_per_class": 2,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "waiting"
    assert payload["candidate_job_id"]
    assert payload["promotion_eligible"] is False


def test_prior_incumbent_with_group_safe_parent_lineage_can_be_compared(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = evaluation_fixture(client, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        learning = ProjectLearningService(session, app.state.settings)
        next_cycle = learning.improve(project["id"], config().model_copy(update={"seed": 991}))
        assert next_cycle.run is not None and next_cycle.dataset_version is not None
        next_run = session.get(TrainingRun, next_cycle.run.id)
        assert next_run is not None
        next_run.status = "completed"
        candidate_path = f"projects/{project['id']}/models/evaluation-next.pt"
        absolute = resolve_managed_project_path(app.state.settings, candidate_path)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        absolute.write_bytes(b"next-checkpoint")
        candidate = ModelRegistration(
            project_id=project["id"],
            purpose="detector",
            display_name="Next candidate",
            source_filename="evaluation-next.pt",
            managed_path=candidate_path,
            sha256=sha256(b"next-checkpoint").hexdigest(),
            file_size_bytes=15,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="8.3.228",
            metadata_json={"source_training_run_id": next_run.id},
        )
        session.add(candidate)
        session.commit()

        queued = LearningEvaluationService(session, app.state.settings).create(
            project["id"],
            LearningEvaluationRequest(
                dataset_version_id=next_cycle.dataset_version.id,
                candidate_model_id=candidate.id,
                incumbent_model_id=project["model_id"],
                minimum_images=2,
                minimum_objects_per_class=2,
            ),
        )
        assert queued.status == "waiting"
        assert queued.incumbent_job_id is not None


def test_evaluation_rejects_unknown_checkpoint_lineage_and_corruption(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = evaluation_fixture(client, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        service = LearningEvaluationService(session, app.state.settings)
        request = LearningEvaluationRequest(
            dataset_version_id=project["version_id"],
            candidate_model_id=project["model_id"],
            minimum_images=2,
            minimum_objects_per_class=2,
        )
        model = session.get(ModelRegistration, project["model_id"])
        assert model is not None
        metadata = dict(model.metadata_json)
        model.metadata_json = {}
        session.commit()
        with pytest.raises(ValidationError, match="lineage"):
            service.create(project["id"], request)
        model.metadata_json = metadata
        session.commit()
        resolve_managed_project_path(app.state.settings, model.managed_path).write_bytes(b"corrupt")
        with pytest.raises(ValidationError, match="checksum"):
            service.create(project["id"], request)

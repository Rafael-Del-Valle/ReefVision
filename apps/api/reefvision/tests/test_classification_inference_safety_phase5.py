from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

import reefvision.jobs.classification_inference as inference_module
from reefvision.db.models import (
    ClassificationPrediction,
    Job,
    ModelRegistration,
    Project,
)
from reefvision.domain.errors import ValidationError
from reefvision.ml.classification import (
    ClassificationResult,
    UltralyticsClassificationProvider,
)
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_classification_phase5 import _seed_classification_project


class _ProbabilityData:
    def __init__(self, values: list[float]) -> None:
        self.values = values

    def tolist(self) -> list[float]:
        return list(self.values)


class _FakeModel:
    names: ClassVar[dict[int, str]] = {0: "closed", 1: "open"}

    def __init__(self, values: list[float], *, top_index: int, top_confidence: float) -> None:
        self.values = values
        self.top_index = top_index
        self.top_confidence = top_confidence

    def predict(self, *_args: object, **_kwargs: object) -> list[object]:
        probs = SimpleNamespace(
            data=_ProbabilityData(self.values),
            top1=self.top_index,
            top1conf=self.top_confidence,
        )
        return [SimpleNamespace(probs=probs, names=self.names)]


def test_classification_provider_validates_complete_probability_vector() -> None:
    provider = UltralyticsClassificationProvider()
    provider._model = _FakeModel([0.25, 0.75], top_index=1, top_confidence=0.75)

    result = provider.predict(Path("unused.jpg"), device="cpu")

    assert result.label == "open"
    assert result.class_index == 1
    assert result.confidence == pytest.approx(0.75)
    assert result.probabilities == {
        "closed": pytest.approx(0.25),
        "open": pytest.approx(0.75),
    }


@pytest.mark.parametrize(
    ("values", "top_index", "top_confidence", "message"),
    [
        ([float("nan"), 1.0], 1, 1.0, "non-finite"),
        ([0.2, 0.2], 0, 0.2, "does not sum to one"),
        ([0.4, 0.6], 2, 0.6, "out-of-range"),
        ([0.4, 0.6], 1, 0.4, "does not match"),
        ([0.7, 0.3], 1, 0.3, "highest probability"),
    ],
)
def test_classification_provider_rejects_invalid_probability_vectors(
    values: list[float],
    top_index: int,
    top_confidence: float,
    message: str,
) -> None:
    provider = UltralyticsClassificationProvider()
    provider._model = _FakeModel(
        values,
        top_index=top_index,
        top_confidence=top_confidence,
    )

    with pytest.raises(ValidationError, match=message):
        provider.predict(Path("unused.jpg"), device="cpu")


class _FailAfterOneProvider:
    provider_name = "ultralytics"
    provider_version = "test"

    def __init__(self) -> None:
        self.calls = 0

    def load_model(self, model_path: Path, device: str) -> None:
        assert model_path.is_file()
        assert device == "cpu"

    def predict(self, image_path: Path, *, device: str) -> ClassificationResult:
        assert image_path.is_file()
        assert device == "cpu"
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("simulated classifier failure")
        return ClassificationResult(
            label="open",
            class_index=1,
            confidence=0.8,
            probabilities={"closed": 0.2, "open": 0.8, "small": 0.0},
        )

    def unload_model(self) -> None:
        return None


class _SuccessfulProvider:
    provider_name = "ultralytics"
    provider_version = "test"

    def load_model(self, model_path: Path, device: str) -> None:
        assert model_path.is_file()
        assert device == "cpu"

    def predict(self, image_path: Path, *, device: str) -> ClassificationResult:
        assert image_path.is_file()
        assert device == "cpu"
        return ClassificationResult(
            label="open",
            class_index=1,
            confidence=0.8,
            probabilities={"closed": 0.2, "open": 0.8, "small": 0.0},
        )

    def unload_model(self) -> None:
        return None


def _seed_classifier(
    client: TestClient,
    *,
    project_id: str,
    class_ids: dict[str, str],
) -> str:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        project = session.get(Project, project_id)
        assert project is not None
        managed_path = f"{project.storage_root}/models/inference-safety.pt"
        checkpoint = resolve_managed_project_path(app.state.settings, managed_path)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b"classification-inference-safety")
        checksum, file_size = hash_model_file(checkpoint)
        model = ModelRegistration(
            project_id=project_id,
            purpose="classifier",
            display_name="Inference safety classifier",
            source_filename="inference-safety.pt",
            managed_path=managed_path,
            sha256=checksum,
            file_size_bytes=file_size,
            framework="ultralytics",
            task="classify",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={
                "classification_mode": "multiclass",
                "labels": ["closed", "open", "small"],
                "mapping": {
                    "closed": class_ids["closed"],
                    "open": class_ids["open"],
                    "small": class_ids["small"],
                },
            },
            metadata_json={},
        )
        session.add(model)
        session.commit()
        return model.id


def _queue_inference(
    client: TestClient,
    *,
    project_id: str,
    model_id: str,
    image_id: str,
) -> str:
    response = client.post(
        f"/api/v1/projects/{project_id}/classification-inference-jobs",
        json={
            "model_id": model_id,
            "image_ids": [image_id],
            "device": "cpu",
            "minimum_crop_size_px": 1,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_classification_inference_failure_rolls_back_partial_predictions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    model_id = _seed_classifier(client, project_id=str(project["id"]), class_ids=class_ids)
    job_id = _queue_inference(
        client,
        project_id=str(project["id"]),
        model_id=model_id,
        image_id=image_id,
    )
    monkeypatch.setattr(
        inference_module,
        "UltralyticsClassificationProvider",
        _FailAfterOneProvider,
    )
    app = cast(FastAPI, client.app)

    assert not inference_module.process_classification_inference_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        predictions = list(
            session.scalars(
                select(ClassificationPrediction).where(
                    ClassificationPrediction.inference_job_id == job_id
                )
            )
        )
        assert job is not None
        assert job.status == "failed"
        assert job.progress_current == 0
        assert job.result_json["proposal_count"] == 0
        assert predictions == []


def test_classification_inference_retry_replaces_stale_pending_predictions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    model_id = _seed_classifier(client, project_id=project_id, class_ids=class_ids)
    job_id = _queue_inference(
        client,
        project_id=project_id,
        model_id=model_id,
        image_id=image_id,
    )
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        session.add(
            ClassificationPrediction(
                project_id=project_id,
                image_id=image_id,
                annotation_id="e52cc1a2-321a-4c12-ad46-1b95a48600e1",
                model_id=model_id,
                inference_job_id=job_id,
                label_set="default",
                classification_mode="multiclass",
                x_min=5,
                y_min=5,
                x_max=25,
                y_max=25,
                predicted_label="closed",
                predicted_index=0,
                label_class_id=class_ids["closed"],
                confidence=1.0,
                probabilities_json={"closed": 1.0, "open": 0.0, "small": 0.0},
                review_status="pending",
                inference_settings_json={},
                provenance_json={"stale": True},
            )
        )
        session.commit()

    monkeypatch.setattr(
        inference_module,
        "UltralyticsClassificationProvider",
        _SuccessfulProvider,
    )

    assert inference_module.process_classification_inference_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    with app.state.session_factory() as session:
        predictions = list(
            session.scalars(
                select(ClassificationPrediction)
                .where(ClassificationPrediction.inference_job_id == job_id)
                .order_by(ClassificationPrediction.annotation_id)
            )
        )
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert len(predictions) == 3
        assert all(not item.provenance_json.get("stale") for item in predictions)
        assert len({item.annotation_id for item in predictions}) == 3


def test_classification_inference_rejects_changed_registered_checksum(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    model_id = _seed_classifier(client, project_id=project_id, class_ids=class_ids)
    job_id = _queue_inference(
        client,
        project_id=project_id,
        model_id=model_id,
        image_id=image_id,
    )
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        model = session.get(ModelRegistration, model_id)
        assert model is not None
        model.sha256 = "e" * 64
        session.commit()

    class _MustNotLoadProvider(_SuccessfulProvider):
        def load_model(self, model_path: Path, device: str) -> None:
            raise AssertionError("A changed classifier registration must not be loaded")

    monkeypatch.setattr(
        inference_module,
        "UltralyticsClassificationProvider",
        _MustNotLoadProvider,
    )

    assert not inference_module.process_classification_inference_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        predictions = list(
            session.scalars(
                select(ClassificationPrediction).where(
                    ClassificationPrediction.inference_job_id == job_id
                )
            )
        )
        assert job is not None
        assert job.status == "failed"
        assert "changed after this inference job was queued" in str(job.error_message)
        assert predictions == []


def test_classification_inference_rejects_corrupted_checkpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    model_id = _seed_classifier(client, project_id=project_id, class_ids=class_ids)
    job_id = _queue_inference(
        client,
        project_id=project_id,
        model_id=model_id,
        image_id=image_id,
    )
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        model = session.get(ModelRegistration, model_id)
        assert model is not None
        checkpoint = resolve_managed_project_path(app.state.settings, model.managed_path)
    checkpoint.write_bytes(b"corrupted-after-queue")

    class _MustNotLoadProvider(_SuccessfulProvider):
        def load_model(self, model_path: Path, device: str) -> None:
            raise AssertionError("A corrupted classifier checkpoint must not be loaded")

    monkeypatch.setattr(
        inference_module,
        "UltralyticsClassificationProvider",
        _MustNotLoadProvider,
    )

    assert not inference_module.process_classification_inference_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        predictions = list(
            session.scalars(
                select(ClassificationPrediction).where(
                    ClassificationPrediction.inference_job_id == job_id
                )
            )
        )
        assert job is not None
        assert job.status == "failed"
        assert "checkpoint checksum is corrupted" in str(job.error_message)
        assert job.progress_current == 0
        assert job.result_json["proposal_count"] == 0
        assert predictions == []

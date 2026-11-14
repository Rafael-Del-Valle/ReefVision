from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.jobs.inference as inference_module
import reefvision.jobs.training_dispatch as dispatch_module
from reefvision.db.models import (
    Job,
    MaskAnnotationEvent,
    ModelRegistration,
    Project,
    TrainingRun,
)
from reefvision.ml.provider_hub import ProviderCapabilityMatrix
from reefvision.ml.providers import DetectionSettings, PixelBox
from reefvision.ml.segmentation import SegmentationPrediction
from reefvision.ml.segmentation_provider_catalog import segmentation_capability_matrix
from reefvision.schemas.training import TrainingProviderArchitectureResponse
from reefvision.services.segmentation_catalog import SegmentationModelCatalogService
from reefvision.services.segmentation_training import SegmentationTrainingService
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project, import_one


class FakeSegmentationProvider:
    provider_name = "ultralytics"
    provider_version = "test"

    def load_model(self, model_path: Path, device: str) -> None:
        assert model_path.is_file()
        assert device in {"auto", "cpu", "cuda"}

    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[SegmentationPrediction]:
        assert image_path.is_file()
        assert settings.confidence_threshold >= 0
        return [
            SegmentationPrediction(
                label="soft coral",
                class_index=0,
                confidence=0.94,
                box=PixelBox(x_min=8, y_min=6, x_max=36, y_max=30),
                polygon=[
                    [8.0, 6.0],
                    [36.0, 8.0],
                    [33.0, 30.0],
                    [10.0, 28.0],
                ],
            )
        ]

    def unload_model(self) -> None:
        return None


def _seed_segmenter(
    client: TestClient,
    project_id: str,
    label_class_id: str,
) -> ModelRegistration:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        project = session.get(Project, project_id)
        assert project is not None
        managed_path = f"{project.storage_root}/models/test-segmenter.pt"
        checkpoint = resolve_managed_project_path(app.state.settings, managed_path)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b"segmentation-checkpoint")
        model = ModelRegistration(
            project_id=project_id,
            purpose="segmenter",
            display_name="Test Segmenter",
            source_filename="test-segmenter.pt",
            managed_path=managed_path,
            sha256="a" * 64,
            file_size_bytes=checkpoint.stat().st_size,
            framework="ultralytics",
            task="segment",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={
                "labels": ["soft coral"],
                "mapping": {"soft coral": label_class_id},
            },
            input_size_json={"imgsz": 640},
            metadata_json={"proposal_geometry": "polygon_mask"},
        )
        session.add(model)
        session.commit()
        session.refresh(model)
        session.expunge(model)
        return model


def test_segmentation_inference_creates_reviewable_mask_and_accepts_it(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Segmentation inference")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]
    model = _seed_segmenter(client, project["id"], label_class_id)

    monkeypatch.setattr(
        inference_module,
        "segmentation_provider_for_name",
        lambda provider_name: FakeSegmentationProvider(),
    )

    queued = client.post(
        f"/api/v1/projects/{project['id']}/inference-jobs",
        json={"model_id": model.id, "image_ids": [image_id], "device": "cpu"},
    )
    assert queued.status_code == 200, queued.text
    job = queued.json()
    assert job["request_json"]["model_task"] == "segment"

    app = cast(FastAPI, client.app)
    assert (
        inference_module.process_inference_job(
            app.state.settings,
            app.state.session_factory,
            job["id"],
        )
        is True
    )

    proposals_response = client.get(
        f"/api/v1/images/{image_id}/prediction-proposals?review_status=pending"
    )
    assert proposals_response.status_code == 200, proposals_response.text
    proposals = proposals_response.json()["items"]
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["geometry_kind"] == "polygon_mask"
    assert len(proposal["polygon_json"]) == 4
    assert proposal["confidence"] == pytest.approx(0.94)

    accepted = client.post(
        f"/api/v1/prediction-proposals/{proposal['id']}/accept",
        json={"label_class_id": label_class_id},
    )
    assert accepted.status_code == 200, accepted.text
    payload = accepted.json()
    assert payload["annotation"] is None
    assert payload["mask_annotation"]["geometry_kind"] == "polygon"
    assert payload["mask_annotation"]["source_type"] == "accepted_prediction"
    assert payload["proposal"]["accepted_mask_annotation_id"] == payload["mask_annotation"]["id"]

    session_response = client.get(f"/api/v1/images/{image_id}/annotations")
    assert session_response.status_code == 200, session_response.text
    session_payload = session_response.json()
    assert len(session_payload["mask_annotations"]) == 1
    assert session_payload["annotations"] == []
    assert session_payload["image"]["annotation_revision"] == 1

    with app.state.session_factory() as session:
        events = session.query(MaskAnnotationEvent).filter_by(image_id=image_id).all()
        assert len(events) == 1
        assert events[0].event_type == "created"
        assert events[0].after_json["source_type"] == "accepted_prediction"


def test_ultralytics_provider_capability_reports_instance_segmentation() -> None:
    capabilities = segmentation_capability_matrix(
        "ultralytics",
        ProviderCapabilityMatrix(image_detection=True, training=True),
    )
    assert capabilities.image_detection is True
    assert capabilities.image_instance_segmentation is True
    assert capabilities.training is True
    assert capabilities.export is True


def test_training_provider_lists_detection_and_segment_architectures(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SegmentationTrainingService,
        "_cached_ultralytics_detect_architectures",
        lambda self: [
            TrainingProviderArchitectureResponse(
                architecture_id="yolo11n.yaml",
                display_name="yolo11n",
                task="detect",
                source="11/yolo11n.yaml",
            )
        ],
    )
    monkeypatch.setattr(
        SegmentationTrainingService,
        "_cached_ultralytics_segment_architectures",
        lambda self: [
            TrainingProviderArchitectureResponse(
                architecture_id="yolo11n-seg.yaml",
                display_name="yolo11n-seg",
                task="segment",
                source="11/yolo11n-seg.yaml",
            )
        ],
    )
    response = client.get("/api/v1/training/providers")
    assert response.status_code == 200, response.text
    provider = response.json()[0]
    assert provider["supported_tasks"] == ["detect", "segment"]
    assert {item["task"] for item in provider["architectures"]} == {
        "detect",
        "segment",
    }


def test_segmentation_catalog_exposes_installed_scratch_architecture(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Segmentation catalog")
    monkeypatch.setattr(
        "reefvision.services.segmentation_catalog.installed_ultralytics_segmentation_architectures",
        lambda: {"yolo11n-seg.yaml"},
    )
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        catalog = SegmentationModelCatalogService(
            session,
            app.state.settings,
        ).list_project_catalog(project["id"], workflow="training", task="segment")
    entries = [item for item in catalog.models if item.task == "segment"]
    assert entries
    scratch = next(item for item in entries if item.architecture_reference == "yolo11n-seg.yaml")
    assert scratch.selection_kind == "builtin_architecture"
    assert scratch.installation_state == "Available"
    assert entries[0].expected_files == []


class FakeSession(AbstractContextManager["FakeSession"]):
    def __init__(self, task: str) -> None:
        self.job = SimpleNamespace(
            job_type="training",
            status="queued",
            request_json={"training_run_id": "run-1"},
        )
        self.run = SimpleNamespace(task=task)

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def get(self, model_type: type[Any], object_id: str) -> Any:
        if model_type is Job:
            return self.job
        if model_type is TrainingRun:
            return self.run
        return None


class FakeFactory:
    def __init__(self, task: str) -> None:
        self.task = task

    def __call__(self) -> FakeSession:
        return FakeSession(self.task)


def test_training_dispatch_preserves_detection_and_routes_segmentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        dispatch_module,
        "process_training_job",
        lambda settings, factory, job_id: calls.append("detect") or True,
    )
    monkeypatch.setattr(
        dispatch_module,
        "process_segmentation_training_job",
        lambda settings, factory, job_id: calls.append("segment") or True,
    )
    settings = cast(Any, object())

    assert dispatch_module.process_task_aware_training_job(
        settings,
        cast(Any, FakeFactory("detect")),
        "job-1",
    )
    assert dispatch_module.process_task_aware_training_job(
        settings,
        cast(Any, FakeFactory("segment")),
        "job-2",
    )
    assert calls == ["detect", "segment"]


class OutOfBoundsSegmentationProvider(FakeSegmentationProvider):
    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[SegmentationPrediction]:
        assert image_path.is_file()
        return [
            SegmentationPrediction(
                label="soft coral",
                class_index=0,
                confidence=0.94,
                box=PixelBox(x_min=8, y_min=6, x_max=36, y_max=30),
                polygon=[
                    [8.0, 6.0],
                    [81.0, 8.0],
                    [33.0, 30.0],
                    [10.0, 28.0],
                ],
            )
        ]


class MixedValiditySegmentationProvider(FakeSegmentationProvider):
    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[SegmentationPrediction]:
        valid = super().predict(image_path, settings)[0]
        self_intersecting = SegmentationPrediction(
            label="soft coral",
            class_index=0,
            confidence=0.91,
            box=PixelBox(x_min=8, y_min=6, x_max=36, y_max=30),
            polygon=[
                [8.0, 6.0],
                [36.0, 30.0],
                [36.0, 6.0],
                [8.0, 30.0],
            ],
        )
        return [valid, self_intersecting]


class MixedInvalidBoxSegmentationProvider(FakeSegmentationProvider):
    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[SegmentationPrediction]:
        valid = super().predict(image_path, settings)[0]
        invalid_box = SegmentationPrediction(
            label="soft coral",
            class_index=0,
            confidence=0.91,
            box=PixelBox(x_min=8, y_min=6, x_max=81, y_max=30),
            polygon=[
                [8.0, 6.0],
                [36.0, 8.0],
                [33.0, 30.0],
                [10.0, 28.0],
            ],
        )
        return [valid, invalid_box]


class MixedInvalidConfidenceSegmentationProvider(FakeSegmentationProvider):
    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[SegmentationPrediction]:
        valid = super().predict(image_path, settings)[0]
        invalid_confidence = SegmentationPrediction(
            label="soft coral",
            class_index=0,
            confidence=1.1,
            box=PixelBox(x_min=8, y_min=6, x_max=36, y_max=30),
            polygon=[
                [8.0, 6.0],
                [36.0, 8.0],
                [33.0, 30.0],
                [10.0, 28.0],
            ],
        )
        return [valid, invalid_confidence]


def test_segmentation_inference_retains_valid_predictions_when_one_is_invalid(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Partially valid segmentation output")
    report = import_one(client, project["id"], size=(80, 60))
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]
    model = _seed_segmenter(client, project["id"], label_class_id)

    monkeypatch.setattr(
        inference_module,
        "segmentation_provider_for_name",
        lambda provider_name: MixedValiditySegmentationProvider(),
    )

    queued = client.post(
        f"/api/v1/projects/{project['id']}/inference-jobs",
        json={"model_id": model.id, "image_ids": [image_id], "device": "cpu"},
    )
    assert queued.status_code == 200, queued.text
    job = queued.json()

    app = cast(FastAPI, client.app)
    assert inference_module.process_inference_job(
        app.state.settings,
        app.state.session_factory,
        job["id"],
    )

    completed_job = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert completed_job["status"] == "succeeded"
    assert completed_job["result_json"]["proposal_count"] == 1
    assert completed_job["result_json"]["invalid_prediction_count"] == 1
    assert "self-intersect" in completed_job["result_json"]["invalid_prediction_errors"][0]
    proposals = client.get(f"/api/v1/images/{image_id}/prediction-proposals").json()["items"]
    assert len(proposals) == 1
    assert proposals[0]["confidence"] == pytest.approx(0.94)


@pytest.mark.parametrize(
    ("provider_type", "error_fragments"),
    [
        (MixedInvalidBoxSegmentationProvider, ("box", "inside the source image")),
        (
            MixedInvalidConfidenceSegmentationProvider,
            ("confidence", "between 0 and 1"),
        ),
    ],
)
def test_segmentation_inference_fails_when_mixed_output_has_invalid_common_field(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    provider_type: type[FakeSegmentationProvider],
    error_fragments: tuple[str, str],
) -> None:
    project = create_project(client, "Invalid mixed segmentation field")
    report = import_one(client, project["id"], size=(80, 60))
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]
    model = _seed_segmenter(client, project["id"], label_class_id)

    monkeypatch.setattr(
        inference_module,
        "segmentation_provider_for_name",
        lambda provider_name: provider_type(),
    )

    queued = client.post(
        f"/api/v1/projects/{project['id']}/inference-jobs",
        json={"model_id": model.id, "image_ids": [image_id], "device": "cpu"},
    )
    assert queued.status_code == 200, queued.text
    job = queued.json()

    app = cast(FastAPI, client.app)
    assert (
        inference_module.process_inference_job(
            app.state.settings,
            app.state.session_factory,
            job["id"],
        )
        is False
    )

    failed_job = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert failed_job["status"] == "failed"
    assert error_fragments[0] in failed_job["error_message"].lower()
    assert error_fragments[1] in failed_job["error_message"]
    proposals = client.get(f"/api/v1/images/{image_id}/prediction-proposals").json()["items"]
    assert proposals == []


def test_invalid_segmentation_output_fails_before_proposal_persistence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Invalid segmentation output")
    report = import_one(client, project["id"], size=(80, 60))
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]
    model = _seed_segmenter(client, project["id"], label_class_id)

    monkeypatch.setattr(
        inference_module,
        "segmentation_provider_for_name",
        lambda provider_name: OutOfBoundsSegmentationProvider(),
    )

    queued = client.post(
        f"/api/v1/projects/{project['id']}/inference-jobs",
        json={"model_id": model.id, "image_ids": [image_id], "device": "cpu"},
    )
    assert queued.status_code == 200, queued.text
    job = queued.json()

    app = cast(FastAPI, client.app)
    assert (
        inference_module.process_inference_job(
            app.state.settings,
            app.state.session_factory,
            job["id"],
        )
        is False
    )

    failed_job = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert failed_job["status"] == "failed"
    assert "polygon" in failed_job["error_message"].lower()
    assert "inside the source image" in failed_job["error_message"]
    proposals = client.get(f"/api/v1/images/{image_id}/prediction-proposals").json()["items"]
    assert proposals == []

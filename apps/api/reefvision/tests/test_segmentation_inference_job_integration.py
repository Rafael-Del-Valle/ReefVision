from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import reefvision.jobs.inference as inference_module
from reefvision.db.models import (
    Job,
    MaskAnnotation,
    ModelRegistration,
    PredictionProposal,
    Project,
)
from reefvision.main import create_app
from reefvision.ml.providers import DetectionPrediction, DetectionSettings, PixelBox
from reefvision.ml.segmentation import SegmentationPrediction
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project, import_one


class StubSegmentationProvider:
    provider_name = "ultralytics"
    provider_version = "integration-test"

    def __init__(self, batches: list[list[SegmentationPrediction]]) -> None:
        self.batches = batches
        self.call_index = 0

    def load_model(self, model_path: Path, device: str) -> None:
        assert model_path.is_file()
        assert device == "cpu"

    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[SegmentationPrediction]:
        assert image_path.is_file()
        assert settings.device == "cpu"
        batch = self.batches[self.call_index]
        self.call_index += 1
        return batch

    def unload_model(self) -> None:
        return None


class StubDetectionProvider:
    provider_name = "ultralytics"
    provider_version = "integration-test"

    def __init__(self, predictions: list[DetectionPrediction]) -> None:
        self.predictions = predictions

    def load_model(self, model_path: Path, device: str) -> None:
        assert model_path.is_file()
        assert device == "cpu"

    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[DetectionPrediction]:
        assert image_path.is_file()
        assert settings.device == "cpu"
        return self.predictions

    def unload_model(self) -> None:
        return None


def _mask_png(
    *,
    size: tuple[int, int] = (80, 60),
    bounds: tuple[int, int, int, int] = (40, 18, 70, 50),
) -> bytes:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(bounds, fill=255)
    encoded = BytesIO()
    mask.save(encoded, format="PNG")
    return encoded.getvalue()


def _seed_model(
    client: TestClient,
    *,
    project_id: str,
    task: str,
    label_mapping: dict[str, str],
) -> tuple[str, str]:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        project = session.get(Project, project_id)
        assert project is not None
        filename = f"integration-{task}.pt"
        managed_path = f"{project.storage_root}/models/{filename}"
        checkpoint = resolve_managed_project_path(app.state.settings, managed_path)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b"integration-checkpoint")
        model = ModelRegistration(
            project_id=project_id,
            purpose="segmenter" if task == "segment" else "detector",
            display_name=f"Integration {task}",
            source_filename=filename,
            managed_path=managed_path,
            sha256=("a" if task == "segment" else "b") * 64,
            file_size_bytes=checkpoint.stat().st_size,
            framework="ultralytics",
            task=task,
            provider_name="ultralytics",
            provider_version="integration-test",
            class_map_json={
                "labels": list(label_mapping),
                "mapping": label_mapping,
            },
            input_size_json={"imgsz": 640},
            metadata_json={
                "source_training_run_id": "training-run-integration",
                "source_dataset_version_id": "dataset-version-integration",
                "source_dataset_manifest_sha256": "c" * 64,
                "source_split_manifest_sha256": "d" * 64,
            },
        )
        session.add(model)
        session.commit()
        return model.id, project.storage_root


def _queue_job(
    client: TestClient,
    *,
    project_id: str,
    model_id: str,
    image_ids: list[str],
) -> str:
    response = client.post(
        f"/api/v1/projects/{project_id}/inference-jobs",
        json={"model_id": model_id, "image_ids": image_ids, "device": "cpu"},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def test_segment_job_persists_mixed_instances_and_survives_restart(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Mixed segmentation job")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    first_class, second_class = project["label_classes"][:2]
    first_label = str(first_class["name"])
    second_label = str(second_class["name"])
    model_id, storage_root = _seed_model(
        client,
        project_id=project["id"],
        task="segment",
        label_mapping={
            first_label: first_class["id"],
            second_label: second_class["id"],
        },
    )
    polygon = [[3.0, 4.0], [30.0, 5.0], [28.0, 27.0], [5.0, 25.0]]
    provider = StubSegmentationProvider(
        [
            [
                SegmentationPrediction(
                    label=first_label,
                    class_index=0,
                    confidence=0.93,
                    box=PixelBox(x_min=3, y_min=4, x_max=30, y_max=28),
                    polygon=polygon,
                ),
                SegmentationPrediction(
                    label=second_label,
                    class_index=1,
                    confidence=0.81,
                    box=PixelBox(x_min=39, y_min=17, x_max=72, y_max=52),
                    mask_png_bytes=_mask_png(),
                ),
            ]
        ]
    )
    monkeypatch.setattr(
        inference_module,
        "segmentation_provider_for_name",
        lambda _provider_name: provider,
    )

    job_id = _queue_job(
        client,
        project_id=project["id"],
        model_id=model_id,
        image_ids=[image_id],
    )
    app = cast(FastAPI, client.app)
    assert inference_module.process_inference_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    response = client.get(f"/api/v1/images/{image_id}/prediction-proposals")
    assert response.status_code == 200, response.text
    proposals = sorted(response.json()["items"], key=lambda item: item["predicted_index"])
    assert len(proposals) == 2
    polygon_proposal, raster_proposal = proposals

    assert polygon_proposal["model_id"] == model_id
    assert polygon_proposal["inference_job_id"] == job_id
    assert polygon_proposal["label_class_id"] == first_class["id"]
    assert polygon_proposal["predicted_label"] == first_label
    assert polygon_proposal["predicted_index"] == 0
    assert polygon_proposal["confidence"] == pytest.approx(0.93)
    assert polygon_proposal["geometry_kind"] == "polygon_mask"
    assert polygon_proposal["polygon_json"] == polygon
    assert polygon_proposal["mask_path"] is None
    assert (
        polygon_proposal["x_min"],
        polygon_proposal["y_min"],
        polygon_proposal["x_max"],
        polygon_proposal["y_max"],
    ) == pytest.approx((3.0, 4.0, 30.0, 28.0))

    assert raster_proposal["model_id"] == model_id
    assert raster_proposal["inference_job_id"] == job_id
    assert raster_proposal["label_class_id"] == second_class["id"]
    assert raster_proposal["predicted_label"] == second_label
    assert raster_proposal["predicted_index"] == 1
    assert raster_proposal["confidence"] == pytest.approx(0.81)
    assert raster_proposal["geometry_kind"] == "raster_mask"
    assert raster_proposal["polygon_json"] is None
    assert raster_proposal["mask_content_sha256"]
    assert (
        raster_proposal["x_min"],
        raster_proposal["y_min"],
        raster_proposal["x_max"],
        raster_proposal["y_max"],
    ) == pytest.approx((39.0, 17.0, 72.0, 52.0))
    for proposal in proposals:
        assert proposal["provenance_json"]["source_training_run_id"] == ("training-run-integration")
        assert proposal["provenance_json"]["source_dataset_version_id"] == (
            "dataset-version-integration"
        )

    mask_path = str(raster_proposal["mask_path"])
    normalized_mask_path = Path(mask_path)
    assert not normalized_mask_path.is_absolute()
    assert ".." not in normalized_mask_path.parts
    assert mask_path.startswith(f"{storage_root}/prediction-masks/")
    managed_mask = resolve_managed_project_path(app.state.settings, mask_path)
    assert managed_mask.is_file()

    preview = client.get(f"/api/v1/prediction-proposals/{raster_proposal['id']}/mask")
    assert preview.status_code == 200, preview.text
    with Image.open(BytesIO(preview.content)) as preview_mask:
        assert preview_mask.size == (80, 60)
        assert preview_mask.convert("L").getbbox() is not None

    accepted = client.post(
        f"/api/v1/prediction-proposals/{raster_proposal['id']}/accept",
        json={"label_class_id": second_class["id"]},
    )
    assert accepted.status_code == 200, accepted.text
    accepted_mask = accepted.json()["mask_annotation"]
    accepted_mask_id = accepted_mask["id"]
    assert accepted_mask["source_type"] == "accepted_prediction"
    assert accepted_mask["provenance_json"]["source_model_id"] == model_id
    assert accepted_mask["provenance_json"]["source_prediction_id"] == raster_proposal["id"]
    assert accepted_mask["provenance_json"]["source_run_id"] == job_id
    assert accepted_mask["provenance_json"]["original_predicted_index"] == 1
    assert (
        accepted_mask["provenance_json"]["source_proposal_provenance"]["source_training_run_id"]
        == "training-run-integration"
    )

    restarted_app = create_app(app.state.settings)
    try:
        with TestClient(restarted_app) as restarted_client:
            restarted_preview = restarted_client.get(
                f"/api/v1/prediction-proposals/{raster_proposal['id']}/mask"
            )
            assert restarted_preview.status_code == 200, restarted_preview.text
            assert restarted_preview.content == preview.content

            retried = restarted_client.post(
                f"/api/v1/prediction-proposals/{raster_proposal['id']}/accept",
                json={"label_class_id": second_class["id"]},
            )
            assert retried.status_code == 200, retried.text
            assert retried.json()["mask_annotation"]["id"] == accepted_mask_id

            annotations = restarted_client.get(f"/api/v1/images/{image_id}/annotations")
            assert annotations.status_code == 200, annotations.text
            assert [item["id"] for item in annotations.json()["mask_annotations"]] == [
                accepted_mask_id
            ]

        with restarted_app.state.session_factory() as session:
            masks = session.query(MaskAnnotation).filter_by(image_id=image_id).all()
            assert [item.id for item in masks] == [accepted_mask_id]
            persisted = session.get(PredictionProposal, raster_proposal["id"])
            assert persisted is not None
            assert persisted.accepted_mask_annotation_id == accepted_mask_id
    finally:
        restarted_app.state.engine.dispose()


def test_failed_segment_job_removes_partial_rows_and_raster_artifacts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Failing segmentation job")
    first_image_id = import_one(
        client,
        project["id"],
        filename="first.png",
        relative_path="failure/first.png",
    )["successful"][0]["image_id"]
    second_image_id = import_one(
        client,
        project["id"],
        filename="second.png",
        relative_path="failure/second.png",
        size=(81, 60),
    )["successful"][0]["image_id"]
    label_class = project["label_classes"][0]
    label = str(label_class["name"])
    model_id, storage_root = _seed_model(
        client,
        project_id=project["id"],
        task="segment",
        label_mapping={label: label_class["id"]},
    )
    provider = StubSegmentationProvider(
        [
            [
                SegmentationPrediction(
                    label=label,
                    class_index=0,
                    confidence=0.9,
                    box=PixelBox(x_min=5, y_min=5, x_max=30, y_max=30),
                    mask_png_bytes=_mask_png(bounds=(5, 5, 29, 29)),
                )
            ],
            [
                SegmentationPrediction(
                    label=label,
                    class_index=0,
                    confidence=0.8,
                    box=PixelBox(x_min=35, y_min=15, x_max=65, y_max=45),
                    mask_png_bytes=_mask_png(
                        size=(81, 60),
                        bounds=(35, 15, 64, 44),
                    ),
                ),
                SegmentationPrediction(
                    label=label,
                    class_index=0,
                    confidence=0.7,
                    box=PixelBox(x_min=10, y_min=10, x_max=20, y_max=20),
                ),
            ],
        ]
    )
    monkeypatch.setattr(
        inference_module,
        "segmentation_provider_for_name",
        lambda _provider_name: provider,
    )

    job_id = _queue_job(
        client,
        project_id=project["id"],
        model_id=model_id,
        image_ids=[first_image_id, second_image_id],
    )
    app = cast(FastAPI, client.app)
    assert not inference_module.process_inference_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.result_json["error_type"] == "ValidationError"
        assert "without reviewable polygon or raster-mask geometry" in str(job.error_message)
        proposals = session.query(PredictionProposal).filter_by(inference_job_id=job_id).all()
        assert proposals == []

    mask_root = resolve_managed_project_path(
        app.state.settings,
        f"{storage_root}/prediction-masks",
    )
    if mask_root.exists():
        assert [path for path in mask_root.rglob("*") if path.is_file()] == []


def test_detection_job_still_persists_only_bounding_box_geometry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Detection regression job")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    label_class = project["label_classes"][0]
    label = str(label_class["name"])
    model_id, storage_root = _seed_model(
        client,
        project_id=project["id"],
        task="detect",
        label_mapping={label: label_class["id"]},
    )
    provider = StubDetectionProvider(
        [
            DetectionPrediction(
                label=label,
                class_index=0,
                confidence=0.87,
                box=PixelBox(x_min=6, y_min=7, x_max=33, y_max=31),
            )
        ]
    )
    monkeypatch.setattr(
        inference_module,
        "detection_provider_for_name",
        lambda _provider_name: provider,
    )

    job_id = _queue_job(
        client,
        project_id=project["id"],
        model_id=model_id,
        image_ids=[image_id],
    )
    app = cast(FastAPI, client.app)
    assert inference_module.process_inference_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )

    response = client.get(f"/api/v1/images/{image_id}/prediction-proposals")
    assert response.status_code == 200, response.text
    proposals: list[dict[str, Any]] = response.json()["items"]
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["model_id"] == model_id
    assert proposal["inference_job_id"] == job_id
    assert proposal["label_class_id"] == label_class["id"]
    assert proposal["predicted_label"] == label
    assert proposal["predicted_index"] == 0
    assert proposal["confidence"] == pytest.approx(0.87)
    assert proposal["geometry_kind"] == "bounding_box"
    assert proposal["polygon_json"] is None
    assert proposal["mask_path"] is None
    assert proposal["mask_content_sha256"] is None
    assert (
        proposal["x_min"],
        proposal["y_min"],
        proposal["x_max"],
        proposal["y_max"],
    ) == pytest.approx((6.0, 7.0, 33.0, 31.0))

    mask_root = resolve_managed_project_path(
        app.state.settings,
        f"{storage_root}/prediction-masks",
    )
    assert not mask_root.exists()

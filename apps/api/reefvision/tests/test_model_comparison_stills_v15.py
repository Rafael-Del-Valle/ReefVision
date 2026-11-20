from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import func, select

from reefvision.db.models import (
    DatasetVersionItem,
    Job,
    ModelRegistration,
    PredictionProposal,
    TrainingRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import DetectionPrediction, PixelBox
from reefvision.ml.segmentation import SegmentationPrediction
from reefvision.services.model_comparison_stills_v15 import compare_image_models
from reefvision.storage.models import hash_model_file
from reefvision.tests.test_dataset_versions import import_image, update_image
from reefvision.tests.test_mask_annotations import _mask_payload

REFERENCE = [(1, 1), (8, 1), (8, 8), (1, 8)]


def _dataset(client: TestClient) -> tuple[str, str, dict[str, str], dict[str, Any]]:
    project = client.post(
        "/api/v1/projects", json={"name": "Independent reef imagery", "template": "blank"}
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    base = f"/api/v1/projects/{project_id}"
    cls = client.post(
        f"{base}/classes", json={"name": "Coral", "class_index": 0, "display_color": "#52dd85"}
    )
    assert cls.status_code == 201, cls.text
    class_id = cls.json()["id"]
    images = {}
    assignments = []
    for index, (name, split, group) in enumerate(
        [
            ("train", "train", "training-tank"),
            ("validation", "validation", "training-val-tank"),
            ("first", "test", "held-out-tank-a"),
            ("second", "test", "held-out-tank-a"),
            ("blank", "test", "held-out-tank-b"),
            ("excluded", "test", "held-out-tank-b"),
        ]
    ):
        image_id = import_image(
            client,
            project_id,
            filename=f"{name}.png",
            relative_path=f"{name}.png",
            color=(30, 60, index),
        )["successful"][0]["image_id"]
        images[name] = image_id
        annotated = client.put(
            f"/api/v1/images/{image_id}/annotations",
            json={
                "base_revision": 0,
                "annotation_status": "reviewed",
                "annotations": [
                    {
                        "id": str(uuid4()),
                        "label_class_id": class_id,
                        "x_min": 1,
                        "y_min": 1,
                        "x_max": 8,
                        "y_max": 8,
                    }
                ]
                if name in {"first", "second"}
                else [],
                "mask_annotations": [_mask_payload(str(uuid4()), class_id, REFERENCE)]
                if name in {"first", "second"}
                else [],
            },
        )
        assert annotated.status_code == 200, annotated.text
        update_image(
            client,
            image_id,
            group_key=group,
            annotation_status="excluded" if name == "excluded" else "reviewed",
        )
        assignments.append({"image_id": image_id, "split": split})
    frozen = client.post(
        f"{base}/dataset-versions",
        json={
            "name": "Frozen grouped holdout",
            "split_method": "manual",
            "manual_assignments": assignments,
            "eligible_annotation_statuses": ["reviewed", "excluded"],
        },
    )
    assert frozen.status_code == 201, frozen.text
    return project_id, class_id, images, frozen.json()


def _register(
    client: TestClient, project: str, version: dict[str, Any], class_id: str, task: str, name: str
) -> ModelRegistration:
    app = cast(FastAPI, client.app)
    checkpoint = app.state.settings.resolved_data_dir / f"{name}.pt"
    checkpoint.write_bytes(name.encode())
    digest, size = hash_model_file(checkpoint)
    with app.state.session_factory() as session:
        training = TrainingRun(
            project_id=project,
            dataset_version_id=version["id"],
            dataset_manifest_sha256=version["manifest_sha256"],
            split_manifest_sha256="9" * 64,
            task=task,
            provider_id="ultralytics",
            architecture="fixture",
            status="completed",
            initial_checkpoint_source="scratch",
            device="cpu",
            precision="fp32",
            run_name=name,
        )
        session.add(training)
        session.flush()
        model = ModelRegistration(
            project_id=project,
            purpose="detector" if task == "detect" else "segmenter",
            display_name=name,
            source_filename=checkpoint.name,
            managed_path=checkpoint.name,
            sha256=digest,
            file_size_bytes=size,
            framework="fixture",
            task=task,
            provider_name="nnunet" if task == "semantic_segment" else "ultralytics",
            provider_version="fixture",
            class_map_json={"labels": ["coral"], "mapping": {"coral": class_id}},
            metadata_json={
                "source_training_run_id": training.id,
                "source_dataset_version_id": version["id"],
                "source_dataset_manifest_sha256": version["manifest_sha256"],
                "source_split_manifest_sha256": training.split_manifest_sha256,
                **(
                    {"classes": [{"class_index": 0, "pixel_value": 1, "class_name": "coral"}]}
                    if task == "semantic_segment"
                    else {}
                ),
            },
        )
        session.add(model)
        session.commit()
        session.refresh(model)
        session.expunge(model)
    return model


def _unverified_pin(model: ModelRegistration) -> dict[str, Any]:
    return {
        "model_id": model.id,
        "checkpoint_sha256": model.sha256,
        "runtime_selection_id": str(uuid4()),
        "runtime_selection_sha256": "1" * 64,
        "device": "cpu",
        "confidence_threshold": 0.25,
        "iou_threshold": 0.5,
    }


def _confirm_runtime(client: TestClient, project: str, model: ModelRegistration) -> dict[str, Any]:
    path = f"/api/v1/projects/{project}/model-runtime-selections"
    draft = {
        "model_id": model.id,
        "device": "cpu",
        "runtime_id": "nnunetv2" if model.task == "semantic_segment" else "pytorch",
    }
    preview = client.post(path + "/preview", json=draft)
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        path, json={"draft": draft, "reviewed_sha256": preview.json()["content_sha256"]}
    )
    assert confirmed.status_code == 201, confirmed.text
    pin = confirmed.json()
    return {
        "model_id": model.id,
        "checkpoint_sha256": model.sha256,
        "runtime_selection_id": pin["id"],
        "runtime_selection_sha256": pin["content_sha256"],
        **pin["snapshot"]["settings"],
    }


class PairedDetector:
    provider_version = "fixture"

    def load_model(self, model_path: Path, device: str) -> None:
        self.perfect = model_path.read_bytes() == b"left"

    def predict(self, image_path: Path, settings: object) -> list[DetectionPrediction]:
        with Image.open(image_path) as image:
            pixel = image.convert("RGB").getpixel((0, 0))
        if pixel == (30, 60, 4):
            return (
                []
                if self.perfect
                else [DetectionPrediction("coral", 0, 0.9, PixelBox(10, 10, 17, 17))]
            )
        if self.perfect:
            return [DetectionPrediction("coral", 0, 0.9, PixelBox(1, 1, 8, 8))]
        return [DetectionPrediction("coral", 0, 0.9, PixelBox(2, 1, 9, 8))]

    def unload_model(self) -> None:
        pass


class PairedSegmenter:
    provider_version = "fixture"

    def __init__(self) -> None:
        self.detector = PairedDetector()

    def load_model(self, model_path: Path, device: str) -> None:
        self.detector.load_model(model_path, device)

    def predict(self, image_path: Path, settings: object) -> list[SegmentationPrediction]:
        rows = self.detector.predict(image_path, settings)
        return [
            SegmentationPrediction(
                row.label,
                row.class_index,
                row.confidence,
                row.box,
                [
                    [row.box.x_min, row.box.y_min],
                    [row.box.x_max, row.box.y_min],
                    [row.box.x_max, row.box.y_max],
                    [row.box.x_min, row.box.y_max],
                ],
            )
            for row in rows
        ]

    def unload_model(self) -> None:
        self.detector.unload_model()


class RasterSegmenter:
    def predict(self, model_path: Path, image_path: Path, *, device: str) -> Path:
        with Image.open(image_path) as image:
            pixel = image.convert("RGB").getpixel((0, 0))
            shape = Image.new("L", image.size, 0)
        if pixel != (30, 60, 4):
            ImageDraw.Draw(shape).rectangle((2, 1, 9, 8), fill=1)
        path = model_path.parent / f"fixture-{uuid4()}.png"
        shape.save(path)
        return path


@pytest.fixture
def reviewed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("reefvision.services.model_runtime")
    monkeypatch.setattr(
        "reefvision.services.model_runtime.resolve_reviewed_runtime",
        lambda *args, **kwargs: ("fixture-provider", "fixture-runtime"),
    )
    monkeypatch.setattr(
        "reefvision.jobs.inference.detection_provider_for_name", lambda _: PairedDetector()
    )
    monkeypatch.setattr(
        "reefvision.jobs.inference.segmentation_provider_for_name", lambda _: PairedSegmenter()
    )
    monkeypatch.setattr(
        "reefvision.jobs.inference.semantic_provider_for_name", lambda _: RasterSegmenter()
    )


@pytest.mark.parametrize(
    "task,registration,expected_status",
    [
        ("detector", "detect", "held_out"),
        ("detector", "detect", "exploratory"),
        ("mask", "segment", "held_out"),
    ],
)
def test_two_confirmed_still_models_score_the_same_frozen_test_groups(
    client: TestClient, reviewed_runtime: None, task: str, registration: str, expected_status: str
) -> None:
    app = cast(FastAPI, client.app)
    project, class_id, images, version = _dataset(client)
    models = [
        _register(client, project, version, class_id, registration, name)
        for name in ("left", "right")
    ]
    if expected_status == "exploratory":
        with app.state.session_factory() as session:
            opaque = session.get(ModelRegistration, models[1].id)
            opaque.metadata_json = {}
            session.commit()
    selections = [_confirm_runtime(client, project, model) for model in models]
    annotation_url = f"/api/v1/images/{images['first']}/annotations"
    current = client.get(annotation_url).json()
    saved = client.put(
        annotation_url,
        json={
            "base_revision": current["image"]["annotation_revision"],
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": class_id,
                    "x_min": 9,
                    "y_min": 9,
                    "x_max": 15,
                    "y_max": 15,
                }
            ],
            "mask_annotations": [
                _mask_payload(str(uuid4()), class_id, [(9, 9), (15, 9), (15, 15), (9, 15)])
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    with app.state.session_factory() as session:
        report = compare_image_models(
            session,
            app.state.settings,
            project,
            task,
            {"dataset_version_id": version["id"]},
            selections,
        )
        assert (
            session.scalar(select(func.count()).select_from(Job).where(Job.job_type == "inference"))
            == 2
        )
        proposals = session.scalars(select(PredictionProposal)).all()
        assert proposals and all(row.review_status == "evaluation_only" for row in proposals)
        assert all(row.image_id not in {images["train"], images["excluded"]} for row in proposals)
        assert all(
            row.provenance_json["runtime_selection_id"]
            in {pin["runtime_selection_id"] for pin in selections}
            for row in proposals
        )
    assert report["reference_id"] == version["id"]
    assert report["reference_sha256"] == version["manifest_sha256"]
    assert report["evaluation_status"] == expected_status
    assert {row["status"] for row in report["lineage"]} == {"held_out", expected_status}
    assert {group["group_id"] for group in report["groups"]} == {
        "held-out-tank-a",
        "held-out-tank-b",
    }
    observations = {
        row["media_id"]: row for group in report["groups"] for row in group["observations"]
    }
    assert "excluded" in observations[images["excluded"]]["exclusion"]
    first = {
        row["name"]: (row["left"], row["right"]) for row in observations[images["first"]]["metrics"]
    }
    blank = {
        row["name"]: (row["left"], row["right"]) for row in observations[images["blank"]]["metrics"]
    }
    if task == "detector":
        assert first["matched_box_iou"] == pytest.approx((1, 0.75))
        assert first["matched_center_error"] == (0, 1)
        assert blank["false_detections"] == (0, 1)
        assert blank["absolute_count_error"] == (0, 1)
    else:
        assert first["mask_iou"] == pytest.approx((1, 7 / 9))
        assert first["mask_dice"] == pytest.approx((1, 7 / 8))
        assert blank["false_instances"] == (0, 1)


def test_semantic_and_instance_masks_share_pixel_metrics_without_instance_claims(
    client: TestClient,
    reviewed_runtime: None,
) -> None:
    app = cast(FastAPI, client.app)
    project, class_id, images, version = _dataset(client)
    models = [
        _register(client, project, version, class_id, task, name)
        for task, name in (
            ("segment", "left"),
            ("semantic_segment", "right"),
        )
    ]
    selections = [_confirm_runtime(client, project, model) for model in models]
    with app.state.session_factory() as session:
        report = compare_image_models(
            session,
            app.state.settings,
            project,
            "mask",
            {"dataset_version_id": version["id"]},
            selections,
        )
        assert "raster_mask" in set(session.scalars(select(PredictionProposal.geometry_kind)))
    first = next(
        row
        for group in report["groups"]
        for row in group["observations"]
        if row["media_id"] == images["first"]
    )
    metrics = {row["name"]: (row["left"], row["right"]) for row in first["metrics"]}
    assert metrics == {
        "mask_iou": pytest.approx((1, 7 / 9)),
        "mask_dice": pytest.approx((1, 7 / 8)),
    }


@pytest.mark.parametrize("reason", ["segmentation_model_selection", "class_map", "item_manifest"])
def test_rejects_unfit_reference_before_launching_inference(
    client: TestClient,
    reason: str,
) -> None:
    app = cast(FastAPI, client.app)
    project, cls, images, version = _dataset(client)
    first, second = [
        _register(client, project, version, cls, "segment", name) for name in ("left", "right")
    ]
    with app.state.session_factory() as session:
        if reason == "segmentation_model_selection":
            session.add(
                Job(
                    project_id=project,
                    job_type="segmentation_learning_evaluation",
                    status="succeeded",
                    request_json={
                        "candidate_model_id": first.id,
                        "dataset_version_id": version["id"],
                        "split": "test",
                    },
                )
            )
            expected = "overlap"
        elif reason == "class_map":
            row = session.get(ModelRegistration, second.id)
            row.class_map_json = {"labels": ["other"], "mapping": {"other": str(uuid4())}}
            expected = "class"
        else:
            item = session.scalar(
                select(DatasetVersionItem).where(DatasetVersionItem.image_id == images["first"])
            )
            item.group_key = "training-tank"
            expected = "manifest"
        session.commit()
        with pytest.raises(ValidationError, match=expected):
            compare_image_models(
                session,
                app.state.settings,
                project,
                "mask",
                {"dataset_version_id": version["id"]},
                [_unverified_pin(first), _unverified_pin(second)],
            )
        assert (
            session.scalar(select(func.count()).select_from(Job).where(Job.job_type == "inference"))
            == 0
        )

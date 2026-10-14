from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from reefvision.db.models import Annotation, DatasetVersion, Job, MaskAnnotation, TrainingRun
from reefvision.schemas.project_learning import LearningConfig
from reefvision.schemas.training import TrainingProviderArchitectureResponse
from reefvision.services.project_learning import ProjectLearningService
from reefvision.services.segmentation_training import SegmentationTrainingService
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_dataset_versions import import_image, save_annotations, update_image
from reefvision.tests.test_training_workspace import _patch_training_foundation


def seed(client: TestClient, *, count: int = 6, groups: int = 3) -> dict[str, Any]:
    project = create_project(client, "Learning study")
    project["image_ids"] = []
    for i in range(count):
        report = import_image(
            client,
            project["id"],
            filename=f"{i}.png",
            relative_path=f"learning/{i}.png",
            color=(i, 60, 120),
        )
        image_id = report["successful"][0]["image_id"]
        project["image_ids"].append(image_id)
        updated = update_image(
            client, image_id, group_key=f"colony-{i % groups}", annotation_status="reviewed"
        )
        save_annotations(
            client,
            image_id,
            base_revision=int(updated["annotation_revision"]),
            annotation_status="reviewed",
            annotations=[
                {
                    "id": str(uuid4()),
                    "label_class_id": label["id"],
                    "x_min": 2 + j * 8,
                    "y_min": 2,
                    "x_max": 8 + j * 8,
                    "y_max": 12,
                }
                for j, label in enumerate(project["label_classes"])
            ],
        )
    return project


def config() -> LearningConfig:
    return LearningConfig(
        minimum_images=4,
        minimum_objects_per_class=4,
        validation_fraction=0.34,
        epochs=2,
        batch=2,
        imgsz=64,
    )


def test_empty_learning_has_actionable_readiness(client: TestClient) -> None:
    project = create_project(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        report = ProjectLearningService(session, app.state.settings).status(project["id"], config())
        assert not report.ready
        assert report.eligible_object_count == 0
        assert any("reviewed" in reason for reason in report.blockers)
        assert session.scalar(select(func.count()).select_from(DatasetVersion)) == 0


def test_learning_queues_frozen_group_safe_dataset_and_prevents_duplicate_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_training_foundation(monkeypatch)
    project = seed(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        service = ProjectLearningService(session, app.state.settings)
        report = service.status(project["id"], config())
        assert report.ready, report.blockers
        result = service.improve(project["id"], config())
        assert result.run is not None and result.run.status == "queued"
        assert result.dataset_version is not None
        frozen = service.datasets.get_version_items(result.dataset_version.id)
        assert sum(item.annotation_count for item in frozen) == 36
        for group in {item.group_key for item in frozen}:
            assert len({item.split for item in frozen if item.group_key == group}) == 1
        assert {item.split for item in frozen} == {"train", "validation"}
        assert all(len(item.snapshot_sha256) == 64 for item in frozen)
        again = service.improve(project["id"], config())
        assert again.run is None and not again.readiness.ready
        assert session.scalar(select(func.count()).select_from(TrainingRun)) == 1
        assert (
            session.scalar(select(func.count()).select_from(Job).where(Job.job_type == "training"))
            == 1
        )
        assert result.run.initial_checkpoint_source == "scratch"
        assert result.run.evaluation_config["project_learning"]["automatic_promotion"] is False


def test_single_colony_cannot_be_training_and_validation(client: TestClient) -> None:
    project = seed(client, groups=1)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        report = ProjectLearningService(session, app.state.settings).status(project["id"], config())
        assert not report.ready
        assert any("validation" in reason for reason in report.blockers)


def test_pending_and_unreviewed_masks_never_count_as_learning_truth(client: TestClient) -> None:
    project = seed(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        for image_id in project["image_ids"]:
            session.add(
                MaskAnnotation(
                    image_id=image_id,
                    label_class_id=project["label_classes"][0]["id"],
                    geometry_kind="polygon",
                    status="pending",
                    polygon_json=[[1, 1], [8, 1], [8, 8]],
                )
            )
        session.commit()
        report = ProjectLearningService(session, app.state.settings).status(
            project["id"], config().model_copy(update={"task": "segment"})
        )
        assert not report.ready
        assert report.eligible_object_count == 0
    update_image(
        client, project["image_ids"][0], group_key="colony-0", annotation_status="in_progress"
    )
    with app.state.session_factory() as session:
        report = ProjectLearningService(session, app.state.settings).status(project["id"], config())
        assert report.reviewed_image_count == 5
        assert report.eligible_object_count == 30


def test_training_preflight_failure_rolls_back_snapshot_and_draft(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_training_foundation(monkeypatch)
    project = seed(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        result = ProjectLearningService(session, app.state.settings).improve(
            project["id"], config().model_copy(update={"architecture": "missing.yaml"})
        )
        assert result.run is None
        assert result.preflight is not None and result.preflight.status == "blocked"
        assert session.scalar(select(func.count()).select_from(DatasetVersion)) == 0
        assert session.scalar(select(func.count()).select_from(TrainingRun)) == 0


def test_next_learning_cycle_preserves_holdout_and_old_annotation_snapshot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_training_foundation(monkeypatch)
    project = seed(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        service = ProjectLearningService(session, app.state.settings)
        first = service.improve(project["id"], config())
        assert first.run is not None and first.dataset_version is not None
        old_items = service.datasets.get_version_items(first.dataset_version.id)
        original_assignments = {item.image_id: item.split for item in old_items}
        old_hash = first.dataset_version.manifest_sha256
        old_geometry = old_items[0].annotation_snapshot_json[0]["x_min"]
        service.training.cancel_run(first.run.id)
        annotation = session.get(Annotation, old_items[0].annotation_snapshot_json[0]["id"])
        assert annotation is not None
        annotation.x_min += 1
        annotation.revision += 1
        session.commit()
        second = service.improve(project["id"], config().model_copy(update={"seed": 777}))
        assert second.dataset_version is not None and second.run is not None
        new_items = service.datasets.get_version_items(second.dataset_version.id)
        assert {item.image_id: item.split for item in new_items} == original_assignments
        assert second.dataset_version.parent_version_id == first.dataset_version.id
        assert service.datasets.get_version(first.dataset_version.id).manifest_sha256 == old_hash
        assert (
            service.datasets.get_version_items(first.dataset_version.id)[
                0
            ].annotation_snapshot_json[0]["x_min"]
            == old_geometry
        )
        assert second.dataset_version.manifest_sha256 != old_hash


def test_cancellation_in_progress_still_blocks_new_training(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_training_foundation(monkeypatch)
    project = seed(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        service = ProjectLearningService(session, app.state.settings)
        result = service.improve(project["id"], config())
        assert result.run is not None
        run = session.get(TrainingRun, result.run.id)
        assert run is not None
        run.status = "cancel_requested"
        session.commit()
        assert not service.status(project["id"], config()).ready


def test_learning_api_rejects_download_and_automatic_promotion_options(client: TestClient) -> None:
    project = create_project(client)
    route = f"/api/v1/projects/{project['id']}/learning"
    result = client.post(f"{route}/status", json={})
    assert result.status_code == 200, result.text
    assert not result.json()["ready"]
    blocked = client.post(f"{route}/improve", json={})
    assert blocked.status_code == 200 and blocked.json()["run"] is None
    assert client.post(f"{route}/improve", json={"pretrained": True}).status_code == 422
    assert client.post(f"{route}/improve", json={"automatic_promotion": True}).status_code == 422


def test_verified_rasters_block_polygon_learning_before_snapshot(client: TestClient) -> None:
    project = seed(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            MaskAnnotation(
                image_id=project["image_ids"][0],
                label_class_id=project["label_classes"][0]["id"],
                geometry_kind="raster_mask",
                status="verified",
            )
        )
        session.commit()
        result = ProjectLearningService(session, app.state.settings).improve(
            project["id"], config().model_copy(update={"task": "segment"})
        )
        assert result.run is None
        assert any("Raster masks" in item for item in result.readiness.blockers)
        assert session.scalar(select(func.count()).select_from(DatasetVersion)) == 0


def test_polygon_learning_queues_existing_segmentation_worker(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_training_foundation(monkeypatch)
    from reefvision.services import training

    monkeypatch.setattr(
        "reefvision.services.segmentation_training.provider_preflight", training.provider_preflight
    )
    monkeypatch.setattr(
        "reefvision.services.segmentation_training.validate_ultralytics_training_configuration",
        lambda **kwargs: SimpleNamespace(warnings=[]),
    )
    monkeypatch.setattr(
        SegmentationTrainingService,
        "_cached_ultralytics_segment_architectures",
        lambda self: [
            TrainingProviderArchitectureResponse(
                architecture_id="yolo11-seg.yaml",
                display_name="YOLO11",
                task="segment",
                source="11/yolo11-seg.yaml",
            )
        ],
    )
    project = seed(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        for image_id in project["image_ids"]:
            for label in project["label_classes"]:
                session.add(
                    MaskAnnotation(
                        image_id=image_id,
                        label_class_id=label["id"],
                        geometry_kind="polygon",
                        status="verified",
                        polygon_json=[[1, 1], [8, 1], [8, 8]],
                        x_min=1,
                        y_min=1,
                        x_max=8,
                        y_max=8,
                        area_pixels=24,
                    )
                )
        session.commit()
        service = ProjectLearningService(session, app.state.settings)
        result = service.improve(project["id"], config().model_copy(update={"task": "segment"}))
        assert result.run is not None, result.model_dump()
        assert result.run.task == "segment" and result.run.status == "queued"
        assert result.dataset_version is not None
        assert result.dataset_version.mask_annotation_count == 36
        job = session.get(Job, result.run.job_id)
        assert job is not None and job.job_type == "training"
        assert job.request_json["training_run_id"] == result.run.id

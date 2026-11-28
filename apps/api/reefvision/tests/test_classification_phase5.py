from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs import classification_inference as inference_module
from reefvision.jobs import classification_training as training_module
from reefvision.main import create_app
from reefvision.ml.classification import ClassificationScore, ClassificationTrainingResult
from reefvision.storage.backups import create_sqlite_snapshot, resolve_database_path
from reefvision.storage.projects import filesystem_io_path
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_dataset_versions import (
    create_version,
    import_image,
    save_annotations,
    update_image,
)


class FakeClassificationProvider:
    provider_id = "ultralytics"

    @property
    def provider_version(self) -> str:
        return "test-provider"

    def train(
        self,
        dataset_root: Path,
        run_root: Path,
        *,
        architecture: str,
        epochs: int,
        image_size: int,
        batch: int,
        device: str,
    ) -> ClassificationTrainingResult:
        assert dataset_root.is_dir()
        assert architecture == "fake-cls.pt"
        assert epochs == 1
        assert image_size == 64
        assert batch == 2
        assert device == "cpu"
        class_names = sorted(
            {
                class_directory.name
                for split in ("train", "val", "test")
                for class_directory in (dataset_root / split).glob("*")
                if class_directory.is_dir()
            }
        )
        assert len(class_names) == 2
        checkpoint = run_root / "weights" / "best.pt"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(json.dumps(class_names), encoding="utf-8")
        return ClassificationTrainingResult(
            checkpoint_path=checkpoint,
            metrics={"metrics/accuracy_top1": 0.75, "metrics/accuracy_top5": 1.0},
            provider_version=self.provider_version,
            run_root=run_root,
        )

    def predict(
        self,
        checkpoint_path: Path,
        image_path: Path,
        *,
        top_k: int,
        device: str,
    ) -> list[ClassificationScore]:
        class_names = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert image_path.is_file()
        assert top_k == 2
        assert device == "cpu"
        return [
            ClassificationScore(class_name=class_names[0], confidence=0.8, rank=1),
            ClassificationScore(class_name=class_names[1], confidence=0.2, rank=2),
        ]


def _seed_project(client: TestClient) -> tuple[dict[str, object], list[str], str]:
    project = create_project(client, "Phase 5 classification")
    classes = cast(list[dict[str, object]], project["label_classes"])
    image_ids: list[str] = []
    for index, class_record in enumerate(classes[:2]):
        report = import_image(
            client,
            str(project["id"]),
            filename=f"classification-{index}.png",
            relative_path=f"classification/classification-{index}.png",
            color=(50 + index * 30, 90, 130),
        )
        image_id = str(report["successful"][0]["image_id"])
        image_ids.append(image_id)
        class_id = str(class_record["id"])
        saved = save_annotations(
            client,
            image_id,
            base_revision=0,
            annotation_status="reviewed",
            annotations=[
                {
                    "id": f"92a178ad-98bb-45a1-8d2c-c0b07584a1a{index}",
                    "label_class_id": class_id,
                    "x_min": 10,
                    "y_min": 10,
                    "x_max": 50,
                    "y_max": 45,
                }
            ],
        )
        assert saved["image"]["annotation_status"] == "reviewed"
        update_image(
            client,
            image_id,
            group_key=f"classification-group-{index}",
            annotation_status="reviewed",
        )
        labels = client.put(
            f"/api/v1/images/{image_id}/classification-labels",
            json={"label_set": "species", "label_class_ids": [class_id]},
        )
        assert labels.status_code == 200, labels.text
    version = create_version(client, str(project["id"]), name="Classification source")
    return project, image_ids, str(version["id"])


def test_image_and_crop_classification_datasets_are_immutable(client: TestClient) -> None:
    project, image_ids, version_id = _seed_project(client)
    image_dataset = client.post(
        f"/api/v1/projects/{project['id']}/classification-datasets",
        json={
            "dataset_version_id": version_id,
            "mode": "image",
            "label_set": "species",
        },
    )
    assert image_dataset.status_code == 201, image_dataset.text
    image_payload = image_dataset.json()
    assert image_payload["sample_count"] == 2
    assert image_payload["manifest_json"]["mode"] == "image"
    samples = image_payload["manifest_json"]["samples"]
    assert all(sample["crop_bounds"] is None for sample in samples)

    crop_dataset = client.post(
        f"/api/v1/projects/{project['id']}/classification-datasets",
        json={
            "dataset_version_id": version_id,
            "mode": "box_crop",
            "label_set": "species",
            "minimum_crop_pixels": 8,
        },
    )
    assert crop_dataset.status_code == 201, crop_dataset.text
    crop_payload = crop_dataset.json()
    assert crop_payload["sample_count"] == 2
    assert all(
        sample["crop_bounds"] == [10, 10, 50, 45]
        for sample in crop_payload["manifest_json"]["samples"]
    )

    removed = client.put(
        f"/api/v1/images/{image_ids[0]}/classification-labels",
        json={"label_set": "species", "label_class_ids": []},
    )
    assert removed.status_code == 200, removed.text
    stored = client.get(f"/api/v1/classification-datasets/{image_payload['id']}")
    assert stored.status_code == 200, stored.text
    assert stored.json()["manifest_sha256"] == image_payload["manifest_sha256"]


def test_long_profile_classification_archives_reopen_and_deduplicate(
    client: TestClient, test_settings: Settings, tmp_path: Path
) -> None:
    project, _image_ids, version_id = _seed_project(client)
    profile = tmp_path / "relocated-profile"
    while len(str(profile)) < 165:
        profile /= "field-station-profile"
    shutil.copytree(
        filesystem_io_path(test_settings.resolved_data_dir / "projects"),
        filesystem_io_path(profile / "projects"),
    )
    database = profile / "test.db"
    create_sqlite_snapshot(resolve_database_path(test_settings), database)
    settings = test_settings.model_copy(
        update={"data_dir": profile, "database_url": f"sqlite:///{database.as_posix()}"}
    )
    endpoint = f"/api/v1/projects/{project['id']}/classification-datasets"
    request = {"dataset_version_id": version_id, "mode": "image", "label_set": "species"}

    app = create_app(settings)
    with TestClient(app) as relocated:
        created = relocated.post(endpoint, json=request)
        assert created.status_code == 201, created.text
        dataset = created.json()
        duplicate = relocated.post(endpoint, json=request)
        assert duplicate.status_code == 201, duplicate.text
        assert duplicate.json()["id"] == dataset["id"]
    app.state.engine.dispose()

    output = profile / dataset["output_path"]
    archive = profile / dataset["archive_path"]
    assert len(str(archive)) >= 260
    assert not Path(dataset["output_path"]).is_absolute()
    assert not Path(dataset["archive_path"]).is_absolute()
    assert {path.name for path in filesystem_io_path(output.parent).iterdir()} == {
        output.name,
        archive.name,
    }
    manifest_name = "reefvision-classification-manifest.json"
    assert (
        json.loads(filesystem_io_path(output / manifest_name).read_bytes())
        == dataset["manifest_json"]
    )
    reopened_app = create_app(settings)
    with TestClient(reopened_app) as reopened:
        downloaded = reopened.get(f"/api/v1/classification-datasets/{dataset['id']}/download")
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.content == filesystem_io_path(archive).read_bytes()
        with zipfile.ZipFile(io.BytesIO(downloaded.content)) as package:
            assert json.loads(package.read(manifest_name)) == dataset["manifest_json"]
            samples = [sample["sample_path"] for sample in dataset["manifest_json"]["samples"]]
            assert len(samples) == 2
            assert set(package.namelist()) == {manifest_name, *samples}
            for sample in samples:
                assert package.read(sample) == filesystem_io_path(output / sample).read_bytes()
    reopened_app.state.engine.dispose()


def test_classification_training_inference_and_review(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, image_ids, version_id = _seed_project(client)
    dataset = client.post(
        f"/api/v1/projects/{project['id']}/classification-datasets",
        json={
            "dataset_version_id": version_id,
            "mode": "image",
            "label_set": "species",
        },
    )
    assert dataset.status_code == 201, dataset.text
    monkeypatch.setattr(
        training_module,
        "classification_provider_for_name",
        lambda _name: FakeClassificationProvider(),
    )
    training = client.post(
        f"/api/v1/projects/{project['id']}/classification-training-jobs",
        json={
            "classification_dataset_id": dataset.json()["id"],
            "architecture": "fake-cls.pt",
            "run_name": "species classifier",
            "epochs": 1,
            "image_size": 64,
            "batch": 2,
            "device": "cpu",
        },
    )
    assert training.status_code == 200, training.text
    app = cast(FastAPI, client.app)
    assert training_module.process_classification_training_job(
        app.state.settings,
        app.state.session_factory,
        training.json()["id"],
    )
    training_job = client.get(f"/api/v1/jobs/{training.json()['id']}")
    assert training_job.status_code == 200, training_job.text
    model_id = training_job.json()["result_json"]["model_id"]
    models = client.get(f"/api/v1/projects/{project['id']}/models?purpose=classifier")
    assert models.status_code == 200, models.text
    assert models.json()[0]["id"] == model_id
    assert models.json()[0]["task"] == "classify"

    monkeypatch.setattr(
        inference_module,
        "classification_provider_for_name",
        lambda _name: FakeClassificationProvider(),
    )
    inference = client.post(
        f"/api/v1/projects/{project['id']}/classification-inference-jobs",
        json={
            "model_id": model_id,
            "image_ids": [image_ids[0]],
            "label_set": "species",
            "top_k": 2,
            "device": "cpu",
        },
    )
    assert inference.status_code == 200, inference.text
    assert inference_module.process_classification_inference_job(
        app.state.settings,
        app.state.session_factory,
        inference.json()["id"],
    )
    predictions = client.get(
        f"/api/v1/projects/{project['id']}/classification-predictions",
        params={"image_id": image_ids[0], "status": "pending"},
    )
    assert predictions.status_code == 200, predictions.text
    pending = predictions.json()
    assert len(pending) == 2
    assert [item["rank"] for item in pending] == [1, 2]

    accepted = client.put(
        f"/api/v1/classification-predictions/{pending[0]['id']}/review",
        json={"action": "accept"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    labels = client.get(
        f"/api/v1/images/{image_ids[0]}/classification-labels",
        params={"label_set": "species"},
    )
    assert labels.status_code == 200, labels.text
    accepted_label = next(
        item for item in labels.json() if item["source_prediction_id"] == pending[0]["id"]
    )
    assert accepted_label["source_model_id"] == model_id
    assert accepted_label["source_type"] == "accepted_prediction"

    rejected = client.put(
        f"/api/v1/classification-predictions/{pending[1]['id']}/review",
        json={"action": "reject"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

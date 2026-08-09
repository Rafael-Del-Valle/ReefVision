from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.models import (
    ClassificationDataset,
    DatasetVersion,
    ImageAsset,
    LabelClass,
)
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project, import_one

MANIFEST_FILENAME = "reefvision-classification-manifest.json"


def _seed_classification_dataset(
    client: TestClient,
    test_settings: Settings,
    *,
    project_id: str,
    image_id: str,
    label_class_id: str,
) -> tuple[str, bytes, str]:
    app = cast(FastAPI, client.app)
    dataset_id = str(uuid4())
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        label_class = session.get(LabelClass, label_class_id)
        assert image is not None
        assert label_class is not None
        version_manifest = {
            "project_id": project_id,
            "image_ids": [image_id],
            "purpose": "classification-exchange-test",
        }
        version = DatasetVersion(
            project_id=project_id,
            version_number=1,
            name="Classification source version",
            notes=None,
            parent_version_id=None,
            status="complete",
            requested_split_method="random",
            resolved_split_method="random",
            eligible_annotation_statuses_json=["annotated"],
            requested_ratios_json=None,
            achieved_ratios_json=None,
            split_seed=42,
            reuse_parent_assignments=False,
            missing_group_key_count=0,
            warnings_json=[],
            class_map_json=[],
            manifest_json=version_manifest,
            manifest_sha256=canonical_json_sha256(version_manifest),
            image_count=1,
            annotation_count=0,
            mask_annotation_count=0,
            created_by="test",
            reefvision_version="test",
            schema_version="dataset-0001",
            error_message=None,
            completed_at=datetime.now(UTC),
        )
        session.add(version)
        session.flush()

        folder = f"{label_class.class_index:04d}_{label_class.name.lower().replace(' ', '_')}"
        sample_path = f"train/{folder}/{image_id}.png"
        manifest = {
            "schema_version": "classification-0001",
            "project_id": project_id,
            "dataset_version_id": version.id,
            "dataset_manifest_sha256": version.manifest_sha256,
            "mode": "image",
            "label_set": "default",
            "minimum_crop_pixels": 8,
            "class_counts": {label_class_id: 1},
            "class_folders": {
                folder: {
                    "label_class_id": label_class_id,
                    "class_index": label_class.class_index,
                    "class_name": label_class.name,
                }
            },
            "samples": [
                {
                    "sample_path": sample_path,
                    "split": "train",
                    "image_id": image_id,
                    "image_sha256": image.sha256,
                    "label_class_id": label_class_id,
                    "class_name": label_class.name,
                    "class_index": label_class.class_index,
                    "geometry_kind": "image",
                    "source_annotation_id": None,
                    "crop_box": None,
                }
            ],
        }
        output_relative = f"projects/{project_id}/classification/datasets/{dataset_id}"
        archive_relative = f"projects/{project_id}/classification/datasets/{dataset_id}.zip"
        output_root = resolve_managed_project_path(test_settings, output_relative)
        archive_path = resolve_managed_project_path(test_settings, archive_relative)
        sample_file = output_root / sample_path
        sample_file.parent.mkdir(parents=True, exist_ok=True)
        sample_image = Image.new("RGB", (20, 16), (100, 120, 140))
        sample_image.save(sample_file, format="PNG")
        sample_bytes = sample_file.read_bytes()
        (output_root / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(output_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(output_root).as_posix())

        record = ClassificationDataset(
            id=dataset_id,
            project_id=project_id,
            dataset_version_id=version.id,
            name="Exchange classification dataset",
            mode="image",
            label_set="default",
            status="complete",
            output_path=output_relative,
            archive_path=archive_relative,
            manifest_json=manifest,
            manifest_sha256=canonical_json_sha256(manifest),
            sample_count=1,
            class_count=1,
            created_by="test",
            completed_at=datetime.now(UTC),
        )
        session.add(record)
        session.commit()
        return dataset_id, sample_bytes, version.id


def test_project_exchange_restores_classification_dataset_archive_and_directory(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Classification exchange source")
    imported = import_one(
        client,
        str(project["id"]),
        filename="classification-source.png",
        relative_path="classification/source.png",
        size=(80, 60),
    )
    source_image_id = str(imported["successful"][0]["image_id"])
    source_class_id = str(project["label_classes"][0]["id"])
    source_dataset_id, sample_bytes, source_version_id = _seed_classification_dataset(
        client,
        test_settings,
        project_id=str(project["id"]),
        image_id=source_image_id,
        label_class_id=source_class_id,
    )

    created = client.post(
        f"/api/v1/projects/{project['id']}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": False,
            "include_generated_artifacts": True,
            "notes": "classification materialization round trip",
        },
    )
    assert created.status_code == 202, created.text
    created_payload = created.json()
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        test_settings,
        app.state.session_factory,
        created_payload["job_id"],
    )
    package = client.get(
        f"/api/v1/exchange-packages/{created_payload['package']['id']}"
    ).json()
    assert package["status"] == "complete"
    assert any(
        item["kind"] == "classification_dataset_archive"
        and item["record_id"] == source_dataset_id
        for item in package["manifest_json"]["media"]
    )
    source_exchange = resolve_managed_project_path(
        test_settings,
        str(package["archive_path"]),
    ).read_bytes()

    response = client.post(
        "/api/v1/exchange-packages/import",
        data={"project_name": "Classification exchange restored"},
        files={
            "file": (
                "classification-roundtrip.reefvision.zip",
                source_exchange,
                "application/zip",
            )
        },
    )
    assert response.status_code == 201, response.text
    restored_project_id = str(response.json()["project_id"])
    assert restored_project_id != project["id"]

    with app.state.session_factory() as session:
        restored_dataset = session.scalar(
            select(ClassificationDataset).where(
                ClassificationDataset.project_id == restored_project_id
            )
        )
        restored_image = session.scalar(
            select(ImageAsset).where(ImageAsset.project_id == restored_project_id)
        )
        restored_class = session.scalar(
            select(LabelClass).where(LabelClass.project_id == restored_project_id)
        )
        assert restored_dataset is not None
        assert restored_image is not None
        assert restored_class is not None
        assert restored_dataset.id != source_dataset_id
        assert restored_dataset.dataset_version_id != source_version_id
        assert restored_dataset.manifest_sha256 == canonical_json_sha256(
            restored_dataset.manifest_json
        )

        manifest = dict(restored_dataset.manifest_json)
        assert manifest["project_id"] == restored_project_id
        assert manifest["dataset_version_id"] == restored_dataset.dataset_version_id
        assert list(manifest["class_counts"]) == [restored_class.id]
        sample = manifest["samples"][0]
        assert sample["image_id"] == restored_image.id
        assert sample["label_class_id"] == restored_class.id
        folder_metadata = next(iter(manifest["class_folders"].values()))
        assert folder_metadata["label_class_id"] == restored_class.id

        output_root = resolve_managed_project_path(
            test_settings,
            restored_dataset.output_path,
        )
        archive_path = resolve_managed_project_path(
            test_settings,
            restored_dataset.archive_path,
        )
        assert output_root.is_dir()
        assert archive_path.is_file()
        restored_sample = output_root / str(sample["sample_path"])
        assert restored_sample.is_file()
        assert restored_sample.read_bytes() == sample_bytes
        disk_manifest = json.loads((output_root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        assert disk_manifest == restored_dataset.manifest_json
        with zipfile.ZipFile(archive_path, "r") as rebuilt:
            archive_manifest = json.loads(rebuilt.read(MANIFEST_FILENAME))
            assert archive_manifest == restored_dataset.manifest_json
            assert rebuilt.read(str(sample["sample_path"])) == sample_bytes

    with app.state.session_factory() as session:
        source_dataset = session.get(ClassificationDataset, source_dataset_id)
        assert source_dataset is not None
        source_output = resolve_managed_project_path(test_settings, source_dataset.output_path)
        source_archive = resolve_managed_project_path(test_settings, source_dataset.archive_path)
        assert source_output.is_dir()
        assert source_archive.is_file()

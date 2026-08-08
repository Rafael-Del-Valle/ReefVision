"""Materialize immutable image and crop classification datasets."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ClassificationDataset,
    DatasetVersion,
    DatasetVersionItem,
    ImageAsset,
    ImageLabel,
    Project,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.classification import (
    ClassificationDatasetCreateRequest,
    ClassificationDatasetResponse,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

_SPLIT_DIR = {"train": "train", "validation": "val", "test": "test"}


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    return normalized or "class"


def _class_info(snapshot: dict[str, Any]) -> tuple[str, int, str]:
    label_class_id = str(snapshot.get("label_class_id", snapshot.get("id", "")))
    class_name = str(snapshot.get("class_name", snapshot.get("name", "")))
    if not label_class_id or not class_name or "class_index" not in snapshot:
        raise ValidationError("Classification class metadata is incomplete")
    return label_class_id, int(snapshot["class_index"]), class_name


def _class_folder(snapshot: dict[str, Any]) -> str:
    _label_class_id, class_index, class_name = _class_info(snapshot)
    return f"{class_index:04d}_{_slug(class_name)}"


def _bounds(snapshot: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    x_min = max(0, min(width, int(float(snapshot["x_min"]))))
    y_min = max(0, min(height, int(float(snapshot["y_min"]))))
    x_max = max(0, min(width, int(float(snapshot["x_max"]) + 0.999999)))
    y_max = max(0, min(height, int(float(snapshot["y_max"]) + 0.999999)))
    return x_min, y_min, x_max, y_max


class ClassificationDatasetService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _version(self, project_id: str, version_id: str) -> DatasetVersion:
        version = self.session.get(DatasetVersion, version_id)
        if version is None or version.project_id != project_id:
            raise NotFoundError("Dataset version not found in this project")
        if version.status != "complete":
            raise ValidationError("Classification datasets require a complete dataset version")
        return version

    def list_datasets(self, project_id: str) -> list[ClassificationDatasetResponse]:
        self._project(project_id)
        statement = (
            select(ClassificationDataset)
            .where(ClassificationDataset.project_id == project_id)
            .order_by(ClassificationDataset.created_at.desc(), ClassificationDataset.id)
        )
        return [
            ClassificationDatasetResponse.model_validate(item)
            for item in self.session.scalars(statement)
        ]

    def get_dataset(self, dataset_id: str) -> ClassificationDatasetResponse:
        dataset = self.session.get(ClassificationDataset, dataset_id)
        if dataset is None:
            raise NotFoundError("Classification dataset not found")
        return ClassificationDatasetResponse.model_validate(dataset)

    def archive_path(self, dataset_id: str) -> Path:
        dataset = self.session.get(ClassificationDataset, dataset_id)
        if dataset is None:
            raise NotFoundError("Classification dataset not found")
        path = resolve_managed_project_path(self.settings, dataset.archive_path)
        if not path.is_file():
            raise NotFoundError("Classification dataset archive is missing")
        return path

    def _labels_for_images(
        self,
        image_ids: list[str],
        label_set: str,
    ) -> dict[str, list[ImageLabel]]:
        result: dict[str, list[ImageLabel]] = defaultdict(list)
        if not image_ids:
            return result
        statement = (
            select(ImageLabel)
            .where(
                ImageLabel.image_id.in_(image_ids),
                ImageLabel.label_set == label_set,
                ImageLabel.status == "verified",
                ImageLabel.deleted_at.is_(None),
            )
            .order_by(ImageLabel.image_id, ImageLabel.created_at, ImageLabel.id)
        )
        for label in self.session.scalars(statement):
            result[label.image_id].append(label)
        return result

    def create_dataset(
        self,
        project_id: str,
        payload: ClassificationDatasetCreateRequest,
    ) -> ClassificationDatasetResponse:
        project = self._project(project_id)
        version = self._version(project_id, payload.dataset_version_id)
        items = list(
            self.session.scalars(
                select(DatasetVersionItem)
                .where(DatasetVersionItem.dataset_version_id == version.id)
                .order_by(DatasetVersionItem.split, DatasetVersionItem.image_id)
            )
        )
        if not items:
            raise ValidationError("Dataset version does not contain images")
        image_ids = [item.image_id for item in items]
        images = {
            image.id: image
            for image in self.session.scalars(
                select(ImageAsset).where(ImageAsset.id.in_(image_ids))
            )
        }
        image_labels = self._labels_for_images(image_ids, payload.label_set)
        class_map = {
            str(entry["id"]): entry
            for entry in version.class_map_json
            if isinstance(entry, dict) and entry.get("id")
        }

        dataset_id = str(uuid4())
        relative_root = f"{project.storage_root}/classification/datasets/{dataset_id}"
        relative_archive = f"{project.storage_root}/classification/datasets/{dataset_id}.zip"
        output_root = resolve_managed_project_path(self.settings, relative_root)
        archive_path = resolve_managed_project_path(self.settings, relative_archive)
        shutil.rmtree(output_root, ignore_errors=True)
        archive_path.unlink(missing_ok=True)
        output_root.mkdir(parents=True)

        samples: list[dict[str, Any]] = []
        class_counts: dict[str, int] = defaultdict(int)
        class_folders: dict[str, dict[str, object]] = {}
        try:
            for item in items:
                split = _SPLIT_DIR.get(item.split)
                if split is None:
                    continue
                image = images.get(item.image_id)
                if image is None or image.sha256 != item.image_sha256:
                    raise ValidationError(
                        "Classification source image no longer matches its snapshot"
                    )
                source = resolve_managed_project_path(self.settings, image.managed_path)
                if not source.is_file():
                    raise ValidationError("Classification source image is missing")
                try:
                    with Image.open(source) as opened:
                        rgb = opened.convert("RGB")
                        sample_specs: list[
                            tuple[dict[str, Any], dict[str, Any] | None, str]
                        ]
                        if payload.mode == "image":
                            labels = image_labels.get(item.image_id, [])
                            if len(labels) != 1:
                                raise ValidationError(
                                    "Whole-image classification requires exactly one "
                                    "verified label "
                                    f"in label set '{payload.label_set}' "
                                    f"for {item.original_filename}"
                                )
                            class_snapshot = class_map.get(labels[0].label_class_id)
                            if class_snapshot is None:
                                raise ValidationError(
                                    "Image label class is absent from the dataset class map"
                                )
                            sample_specs = [(class_snapshot, None, f"{item.image_id}.jpg")]
                        else:
                            source_snapshots = (
                                item.annotation_snapshot_json
                                if payload.mode == "box_crop"
                                else item.mask_annotation_snapshot_json
                            )
                            sample_specs = [
                                (snapshot, snapshot, f"{item.image_id}-{index:05d}.jpg")
                                for index, snapshot in enumerate(source_snapshots)
                            ]

                        for class_snapshot, geometry, filename in sample_specs:
                            class_id, class_index, class_name = _class_info(class_snapshot)
                            class_folder = _class_folder(class_snapshot)
                            class_folders[class_folder] = {
                                "label_class_id": class_id,
                                "class_index": class_index,
                                "class_name": class_name,
                            }
                            destination = output_root / split / class_folder / filename
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            if geometry is None:
                                sample_image = rgb
                                crop_bounds: list[int] | None = None
                            else:
                                bounds = _bounds(geometry, rgb.width, rgb.height)
                                x_min, y_min, x_max, y_max = bounds
                                if (
                                    x_max - x_min < payload.minimum_crop_pixels
                                    or y_max - y_min < payload.minimum_crop_pixels
                                ):
                                    continue
                                sample_image = rgb.crop(bounds)
                                crop_bounds = list(bounds)
                            sample_image.save(destination, format="JPEG", quality=95)
                            relative_sample = destination.relative_to(output_root).as_posix()
                            class_counts[class_id] += 1
                            samples.append(
                                {
                                    "sample_path": relative_sample,
                                    "split": split,
                                    "image_id": item.image_id,
                                    "image_sha256": item.image_sha256,
                                    "label_class_id": class_id,
                                    "class_index": class_index,
                                    "class_name": class_name,
                                    "crop_bounds": crop_bounds,
                                    "source_snapshot_sha256": item.snapshot_sha256,
                                }
                            )
                except (OSError, UnidentifiedImageError) as exc:
                    raise ValidationError(
                        f"Classification source image could not be read: {item.original_filename}"
                    ) from exc

            if not samples:
                raise ValidationError("Classification dataset did not produce any eligible samples")
            manifest = {
                "schema_version": "classification-0001",
                "project_id": project_id,
                "dataset_version_id": version.id,
                "dataset_manifest_sha256": version.manifest_sha256,
                "mode": payload.mode,
                "label_set": payload.label_set,
                "minimum_crop_pixels": payload.minimum_crop_pixels,
                "class_counts": dict(sorted(class_counts.items())),
                "class_folders": dict(sorted(class_folders.items())),
                "samples": samples,
            }
            manifest_sha256 = canonical_json_sha256(manifest)
            (output_root / "reefvision-classification-manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(output_root.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(output_root).as_posix())

            existing = self.session.scalar(
                select(ClassificationDataset).where(
                    ClassificationDataset.project_id == project_id,
                    ClassificationDataset.manifest_sha256 == manifest_sha256,
                )
            )
            if existing is not None:
                shutil.rmtree(output_root, ignore_errors=True)
                archive_path.unlink(missing_ok=True)
                return ClassificationDatasetResponse.model_validate(existing)
            record = ClassificationDataset(
                id=dataset_id,
                project_id=project_id,
                dataset_version_id=version.id,
                mode=payload.mode,
                label_set=payload.label_set,
                status="complete",
                manifest_json=manifest,
                manifest_sha256=manifest_sha256,
                output_path=relative_root,
                archive_path=relative_archive,
                sample_count=len(samples),
            )
            self.session.add(record)
            self.session.commit()
            self.session.refresh(record)
            return ClassificationDatasetResponse.model_validate(record)
        except Exception:
            self.session.rollback()
            shutil.rmtree(output_root, ignore_errors=True)
            archive_path.unlink(missing_ok=True)
            raise

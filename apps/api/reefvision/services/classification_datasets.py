"""Create immutable classification datasets from reviewed independent assignments."""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    ClassificationAssignment,
    ClassificationDatasetSample,
    ClassificationDatasetSnapshot,
    ClassificationLabelSet,
    ImageAsset,
    LabelClass,
    MaskAnnotation,
    Project,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.classification_datasets import (
    ClassificationDatasetCreateRequest,
    ClassificationDatasetDetailResponse,
    ClassificationDatasetSampleResponse,
    ClassificationDatasetSnapshotResponse,
)
from reefvision.storage.datasets import canonical_json_sha256

_SPLITS = ("train", "validation", "test")
_SUPPORTED_TARGETS = {"image", "mask", "fragment"}


class ClassificationDatasetService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _label_set(self, project_id: str, label_set_id: str) -> ClassificationLabelSet:
        label_set = self.session.get(ClassificationLabelSet, label_set_id)
        if label_set is None or label_set.project_id != project_id:
            raise NotFoundError("Classification label set not found in this project")
        if label_set.target_kind not in _SUPPORTED_TARGETS:
            raise ValidationError(
                "Dedicated classification datasets currently support image, mask, "
                "and fragment targets"
            )
        return label_set

    @staticmethod
    def _ratios(request: ClassificationDatasetCreateRequest) -> dict[str, float]:
        raw = request.ratios.model_dump()
        total = sum(float(raw[split]) for split in _SPLITS)
        return {split: float(raw[split]) / total for split in _SPLITS}

    @staticmethod
    def _split_groups(
        group_sizes: dict[str, int],
        *,
        ratios: dict[str, float],
        seed: int,
    ) -> dict[str, str]:
        total = sum(group_sizes.values())
        targets = {split: total * ratios[split] for split in _SPLITS}
        counts = dict.fromkeys(_SPLITS, 0)
        keys = sorted(group_sizes)
        random.Random(seed).shuffle(keys)
        assignments: dict[str, str] = {}
        for group_key in keys:
            size = group_sizes[group_key]
            selected = min(
                _SPLITS,
                key=lambda split: (
                    sum(
                        abs(
                            counts[candidate]
                            + (size if candidate == split else 0)
                            - targets[candidate]
                        )
                        for candidate in _SPLITS
                    ),
                    counts[split] / targets[split] if targets[split] else counts[split],
                    _SPLITS.index(split),
                ),
            )
            assignments[group_key] = selected
            counts[selected] += size
        return assignments

    @staticmethod
    def _mask_geometry(mask: MaskAnnotation) -> dict[str, Any]:
        return {
            "geometry_kind": mask.geometry_kind,
            "mask_path": mask.mask_path,
            "polygon_json": mask.polygon_json,
            "bounds": [mask.x_min, mask.y_min, mask.x_max, mask.y_max],
            "area_pixels": mask.area_pixels,
            "revision": mask.revision,
            "status": mask.status,
            "provenance_json": mask.provenance_json or {},
        }

    def create(
        self,
        project_id: str,
        request: ClassificationDatasetCreateRequest,
    ) -> ClassificationDatasetDetailResponse:
        self._project(project_id)
        label_set = self._label_set(project_id, request.label_set_id)
        assignments = list(
            self.session.scalars(
                select(ClassificationAssignment)
                .where(
                    ClassificationAssignment.project_id == project_id,
                    ClassificationAssignment.label_set_id == label_set.id,
                    ClassificationAssignment.status == "accepted",
                    ClassificationAssignment.target_kind == label_set.target_kind,
                )
                .order_by(
                    ClassificationAssignment.target_key,
                    ClassificationAssignment.created_at,
                    ClassificationAssignment.id,
                )
            )
        )
        if not assignments:
            raise ValidationError("No accepted assignments are available for this label set")

        images = {
            image.id: image
            for image in self.session.scalars(
                select(ImageAsset).where(
                    ImageAsset.project_id == project_id,
                    ImageAsset.id.in_({item.image_id for item in assignments}),
                )
            )
        }
        class_ids = sorted({item.label_class_id for item in assignments})
        classes = {
            item.id: item
            for item in self.session.scalars(
                select(LabelClass).where(
                    LabelClass.project_id == project_id,
                    LabelClass.id.in_(class_ids),
                )
            )
        }
        if set(class_ids) != set(classes):
            raise ValidationError("One or more accepted assignments reference missing classes")

        grouped: dict[str, list[ClassificationAssignment]] = defaultdict(list)
        for assignment in assignments:
            grouped[assignment.target_key].append(assignment)

        prepared: list[dict[str, Any]] = []
        warnings: list[str] = []
        for target_key, target_assignments in grouped.items():
            image_ids = {item.image_id for item in target_assignments}
            if len(image_ids) != 1:
                raise ValidationError("A classification target spans multiple source images")
            image = images.get(next(iter(image_ids)))
            if image is None:
                raise ValidationError("A classification target references a missing image")
            labels = sorted({item.label_class_id for item in target_assignments})
            if label_set.cardinality == "single" and len(labels) != 1:
                raise ValidationError(
                    f"Single-label target {target_key} has {len(labels)} accepted classes"
                )
            mask: MaskAnnotation | None = None
            geometry: dict[str, Any] = {}
            target_revision: int | None = None
            target_checksum = image.sha256
            fragment_key: str | None = None
            mask_id = next(
                (item.mask_annotation_id for item in target_assignments if item.mask_annotation_id),
                None,
            )
            if label_set.target_kind in {"mask", "fragment"}:
                if not mask_id:
                    raise ValidationError(f"Target {target_key} is missing its source mask")
                mask = self.session.get(MaskAnnotation, mask_id)
                if mask is None or mask.image_id != image.id or mask.deleted_at is not None:
                    raise ValidationError(f"Target {target_key} references an unavailable mask")
                if request.require_verified_masks and mask.status != "verified":
                    raise ValidationError(f"Target {target_key} is not backed by a verified mask")
                geometry = self._mask_geometry(mask)
                target_revision = mask.revision
                target_checksum = canonical_json_sha256(geometry)
                fragment_key = next(
                    (item.fragment_key for item in target_assignments if item.fragment_key),
                    None,
                )
            group_key = image.group_key or f"image:{image.id}"
            assignment_revisions = {item.id: item.revision for item in target_assignments}
            sample_payload = {
                "target_kind": label_set.target_kind,
                "target_key": target_key,
                "image_id": image.id,
                "image_sha256": image.sha256,
                "mask_annotation_id": mask.id if mask else None,
                "fragment_key": fragment_key,
                "label_class_ids": labels,
                "assignment_ids": [item.id for item in target_assignments],
                "assignment_revisions": assignment_revisions,
                "target_revision": target_revision,
                "target_checksum": target_checksum,
                "geometry": geometry,
            }
            prepared.append(
                {
                    "target_key": target_key,
                    "image": image,
                    "mask": mask,
                    "fragment_key": fragment_key,
                    "labels": labels,
                    "assignments": target_assignments,
                    "assignment_revisions": assignment_revisions,
                    "group_key": group_key,
                    "target_revision": target_revision,
                    "target_checksum": target_checksum,
                    "geometry": geometry,
                    "sample_sha256": canonical_json_sha256(sample_payload),
                }
            )

        ratios = self._ratios(request)
        group_sizes: dict[str, int] = defaultdict(int)
        for item in prepared:
            group_sizes[item["group_key"]] += 1
        group_splits = self._split_groups(
            dict(group_sizes),
            ratios=ratios,
            seed=request.split_seed,
        )
        split_counts = dict.fromkeys(_SPLITS, 0)
        for item in prepared:
            split_counts[group_splits[item["group_key"]]] += 1
        achieved = {split: split_counts[split] / len(prepared) for split in _SPLITS}
        for split in _SPLITS:
            if ratios[split] > 0 and split_counts[split] == 0:
                warnings.append(
                    f"The {split} split is empty because the available group-safe "
                    "targets are limited."
                )

        class_map = [
            {
                "id": item.id,
                "class_index": item.class_index,
                "name": item.name,
                "scientific_name": item.scientific_name,
                "state_name": item.state_name,
            }
            for item in sorted(classes.values(), key=lambda value: (value.class_index, value.id))
        ]
        manifest_samples = [
            {
                "target_key": item["target_key"],
                "target_kind": label_set.target_kind,
                "image_id": item["image"].id,
                "image_sha256": item["image"].sha256,
                "mask_annotation_id": item["mask"].id if item["mask"] else None,
                "fragment_key": item["fragment_key"],
                "group_key": item["group_key"],
                "split": group_splits[item["group_key"]],
                "label_class_ids": item["labels"],
                "sample_sha256": item["sample_sha256"],
                "target_revision": item["target_revision"],
                "target_checksum": item["target_checksum"],
            }
            for item in sorted(prepared, key=lambda value: value["target_key"])
        ]
        manifest = {
            "schema": "reefvision-classification-dataset-v1",
            "project_id": project_id,
            "name": request.name.strip(),
            "label_set": {
                "id": label_set.id,
                "key": label_set.key,
                "name": label_set.name,
                "target_kind": label_set.target_kind,
                "cardinality": label_set.cardinality,
                "allowed_class_ids": list(label_set.allowed_class_ids_json or []),
            },
            "split_seed": request.split_seed,
            "requested_ratios": ratios,
            "achieved_ratios": achieved,
            "class_map": class_map,
            "samples": manifest_samples,
            "warnings": warnings,
        }
        snapshot = ClassificationDatasetSnapshot(
            project_id=project_id,
            label_set_id=label_set.id,
            name=request.name.strip(),
            notes=request.notes.strip() if request.notes else None,
            status="complete",
            target_kind=label_set.target_kind,
            cardinality=label_set.cardinality,
            split_seed=request.split_seed,
            requested_ratios_json=ratios,
            achieved_ratios_json=achieved,
            class_map_json=class_map,
            manifest_json=manifest,
            manifest_sha256=canonical_json_sha256(manifest),
            sample_count=len(prepared),
            target_count=len(prepared),
            class_count=len(class_map),
            warnings_json=warnings,
            created_by=request.created_by,
            completed_at=datetime.now(UTC),
        )
        self.session.add(snapshot)
        self.session.flush()
        samples: list[ClassificationDatasetSample] = []
        for item in prepared:
            sample = ClassificationDatasetSample(
                snapshot_id=snapshot.id,
                target_kind=label_set.target_kind,
                target_key=item["target_key"],
                image_id=item["image"].id,
                mask_annotation_id=item["mask"].id if item["mask"] else None,
                fragment_key=item["fragment_key"],
                split=group_splits[item["group_key"]],
                group_key=item["group_key"],
                label_class_ids_json=item["labels"],
                assignment_ids_json=[value.id for value in item["assignments"]],
                assignment_revisions_json=item["assignment_revisions"],
                source_image_sha256=item["image"].sha256,
                source_image_managed_path=item["image"].managed_path,
                source_image_width_px=item["image"].width_px,
                source_image_height_px=item["image"].height_px,
                target_revision=item["target_revision"],
                target_checksum=item["target_checksum"],
                geometry_json=item["geometry"],
                provenance_json={
                    "label_set_revision_at_snapshot": label_set.updated_at.isoformat(),
                    "require_verified_masks": request.require_verified_masks,
                },
                sample_sha256=item["sample_sha256"],
            )
            self.session.add(sample)
            samples.append(sample)
        self.session.commit()
        self.session.refresh(snapshot)
        for sample in samples:
            self.session.refresh(sample)
        return ClassificationDatasetDetailResponse(
            snapshot=ClassificationDatasetSnapshotResponse.model_validate(snapshot),
            manifest=manifest,
            samples=[ClassificationDatasetSampleResponse.model_validate(item) for item in samples],
        )

    def list(self, project_id: str) -> list[ClassificationDatasetSnapshotResponse]:
        self._project(project_id)
        records = list(
            self.session.scalars(
                select(ClassificationDatasetSnapshot)
                .where(ClassificationDatasetSnapshot.project_id == project_id)
                .order_by(
                    ClassificationDatasetSnapshot.created_at.desc(),
                    ClassificationDatasetSnapshot.id,
                )
            )
        )
        return [ClassificationDatasetSnapshotResponse.model_validate(item) for item in records]

    def get(self, snapshot_id: str) -> ClassificationDatasetDetailResponse:
        snapshot = self.session.get(ClassificationDatasetSnapshot, snapshot_id)
        if snapshot is None:
            raise NotFoundError("Classification dataset snapshot not found")
        samples = list(
            self.session.scalars(
                select(ClassificationDatasetSample)
                .where(ClassificationDatasetSample.snapshot_id == snapshot.id)
                .order_by(
                    ClassificationDatasetSample.split,
                    ClassificationDatasetSample.group_key,
                    ClassificationDatasetSample.target_key,
                )
            )
        )
        return ClassificationDatasetDetailResponse(
            snapshot=ClassificationDatasetSnapshotResponse.model_validate(snapshot),
            manifest=dict(snapshot.manifest_json or {}),
            samples=[ClassificationDatasetSampleResponse.model_validate(item) for item in samples],
        )

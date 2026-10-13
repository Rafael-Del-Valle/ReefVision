"""Read-only, audited holdout preparation for future segmentation evaluation.

No model inference, score persistence, activation or rollback is done here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import DatasetVersion, DatasetVersionItem
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.domain.segmentation_holdout import (
    SegmentationHoldout,
    validate_segmentation_holdout,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.learning_evaluation import verify_learning_content


class SegmentationHoldoutService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def prepare(
        self,
        project_id: str,
        dataset_version_id: str,
        *,
        split: str,
        minimum_images: int = 1,
        minimum_masks: int = 1,
    ) -> SegmentationHoldout:
        version = self.session.get(DatasetVersion, dataset_version_id)
        if version is None or version.project_id != project_id:
            raise NotFoundError("Segmentation dataset version not found in project")
        if version.status != "complete":
            raise ValidationError("Segmentation evaluation requires a complete immutable version")
        if canonical_json_sha256(version.manifest_json) != version.manifest_sha256:
            raise ValidationError("Segmentation dataset manifest checksum has changed")
        manifest_items = version.manifest_json.get("items")
        if not isinstance(manifest_items, list):
            raise ValidationError("Segmentation manifest is missing snapshot items")
        manifest_index = {
            item.get("image_id"): item for item in manifest_items if isinstance(item, dict)
        }
        if len(manifest_index) != len(manifest_items):
            raise ValidationError("Segmentation manifest has duplicate or malformed images")
        items = list(
            self.session.scalars(
                select(DatasetVersionItem).where(
                    DatasetVersionItem.dataset_version_id == dataset_version_id
                )
            )
        )
        if len(items) != len(manifest_items):
            raise ValidationError("Immutable segmentation item list has changed")
        for item in items:
            snapshot = manifest_index.get(item.image_id)
            if not isinstance(snapshot, dict):
                raise ValidationError("Segmentation snapshot is absent from manifest")
            snapshot_content = {
                key: value for key, value in snapshot.items() if key != "snapshot_sha256"
            }
            if (
                snapshot.get("snapshot_sha256") != item.snapshot_sha256
                or canonical_json_sha256(snapshot_content) != item.snapshot_sha256
                or snapshot.get("mask_annotations") != item.mask_annotation_snapshot_json
                or snapshot.get("annotations") != item.annotation_snapshot_json
                or snapshot.get("image_sha256") != item.image_sha256
                or snapshot.get("width_px") != item.width_px
                or snapshot.get("height_px") != item.height_px
                or snapshot.get("split") != item.split
                or snapshot.get("group_key") != item.group_key
                or snapshot.get("annotation_status") != item.image_annotation_status
                or snapshot.get("mask_annotation_count") != item.mask_annotation_count
            ):
                raise ValidationError("Segmentation snapshot no longer matches immutable manifest")
        class_ids = {
            entry["id"]
            for entry in version.class_map_json
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }
        try:
            return validate_segmentation_holdout(
                items,
                split=split,
                minimum_images=minimum_images,
                minimum_masks=minimum_masks,
                known_class_ids=class_ids,
                verify_raster=lambda path, sha: verify_learning_content(self.settings, path, sha),
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

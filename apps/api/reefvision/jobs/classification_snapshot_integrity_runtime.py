"""Strengthen snapshot classifier materialization without treating storage moves as data drift."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import ClassificationDatasetSample, ImageAsset
from reefvision.jobs import classification_snapshot_training as snapshot_training
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

_ORIGINAL_MATERIALIZE = snapshot_training._materialize_snapshot_dataset


def _current_verified_source_path(
    sample: ClassificationDatasetSample,
    image: ImageAsset,
) -> Path:
    """Use the current managed path only after proving source identity is unchanged."""

    if image.sha256.casefold() != sample.source_image_sha256.casefold():
        raise RuntimeError(
            f"Source image changed after classification snapshot creation: {sample.image_id}"
        )
    if (
        image.width_px != sample.source_image_width_px
        or image.height_px != sample.source_image_height_px
    ):
        raise RuntimeError(
            f"Source image dimensions changed after classification snapshot creation: {sample.image_id}"
        )
    if canonical_json_sha256(snapshot_training._sample_payload(sample)) != sample.sample_sha256:
        raise RuntimeError(
            f"Classification snapshot sample integrity check failed: {sample.target_key}"
        )
    # The immutable snapshot records the source identity, not an eternal filesystem address.
    # A managed project can be relocated while retaining exactly the same source bytes.
    return Path(image.managed_path)


def _strict_materialize(
    settings: Any,
    session: Session,
    *,
    snapshot: Any,
    samples: list[ClassificationDatasetSample],
    project: Any,
    run: Any,
) -> dict[str, Any]:
    image_ids = sorted({sample.image_id for sample in samples})
    images = {
        image.id: image
        for image in session.scalars(
            select(ImageAsset).where(
                ImageAsset.project_id == project.id,
                ImageAsset.id.in_(image_ids),
            )
        )
    }
    if len(images) != len(image_ids):
        raise RuntimeError(
            "A classification snapshot source image no longer exists in this project"
        )
    for image in images.values():
        source_path = resolve_managed_project_path(settings, image.managed_path)
        if not source_path.is_file():
            raise FileNotFoundError(
                f"Managed source image is missing for classification: {image.id}"
            )
        physical_sha256 = snapshot_training._file_sha256(source_path)
        if physical_sha256.casefold() != image.sha256.casefold():
            raise RuntimeError(
                f"Managed source image bytes no longer match their recorded checksum: {image.id}"
            )

    return _ORIGINAL_MATERIALIZE(
        settings,
        session,
        snapshot=snapshot,
        samples=samples,
        project=project,
        run=run,
    )


def install_snapshot_integrity_runtime() -> None:
    snapshot_training._validate_source_image = _current_verified_source_path
    snapshot_training._materialize_snapshot_dataset = _strict_materialize


install_snapshot_integrity_runtime()

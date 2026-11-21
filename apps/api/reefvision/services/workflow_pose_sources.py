"""Read and verify local source bindings for saved pose workflows."""

from typing import Any

from sqlalchemy.orm import Session

from reefvision.db.models import PoseTrainingDataset
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_sha256


def resolve_frozen_pose_dataset(
    session: Session, *, project_id: str, payload: dict[str, Any], role: str
) -> PoseTrainingDataset:
    if payload.get("project_id") not in (None, project_id):
        raise ValidationError(f"Pose {role} dataset belongs to another project")
    dataset_id = payload.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValidationError(f"Pose {role} dataset artifact is missing dataset_id")
    dataset = session.get(PoseTrainingDataset, dataset_id)
    if dataset is None or dataset.project_id != project_id:
        raise ValidationError(f"Pose {role} dataset does not belong to this project")
    if dataset.status != "complete":
        raise ValidationError(f"Pose {role} dataset must be complete")
    advertised_manifest = payload.get("manifest_sha256")
    if advertised_manifest not in (None, "") and (
        advertised_manifest != dataset.manifest_sha256
        or canonical_json_sha256(dataset.manifest_json) != dataset.manifest_sha256
    ):
        raise ValidationError(f"Pose {role} dataset manifest no longer matches persisted truth")
    return dataset


def verify_video_source_pin(expected: object, actual: str) -> None:
    if expected not in (None, "") and expected != actual:
        raise ValidationError("Pinned checksum no longer matches the selected original video")

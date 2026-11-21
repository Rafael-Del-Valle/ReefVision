"""Read and verify local source bindings for saved pose workflows."""

from typing import Any

from pydantic import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.engine import ScalarResult
from sqlalchemy.orm import Session

from reefvision.db.models import PoseTrainingDataset, PoseTrainingDatasetItem, VideoAsset
from reefvision.domain.errors import ValidationError
from reefvision.schemas.temporal_reefpose import ReefPoseSourceGrouping
from reefvision.services.temporal_reefpose_sources import _group_tokens, _reviewed_group_tokens
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


def _recording_keys(dataset: PoseTrainingDataset) -> set[str]:
    return {
        str(item[field])
        for item in dataset.manifest_json.get("items", [])
        for field in ("video_id", "video_sha256")
        if isinstance(item, dict) and item.get(field)
    }


def _frozen_group_keys(session: Session, dataset: PoseTrainingDataset) -> set[str]:
    provenance: ScalarResult[dict[str, Any]] = session.scalars(
        select(PoseTrainingDatasetItem.acquisition_provenance_json).where(
            PoseTrainingDatasetItem.dataset_id == dataset.id
        )
    )
    groups: set[str] = set()
    for item in provenance:
        groups.update(_group_tokens(item))
        try:
            declaration = ReefPoseSourceGrouping.model_validate(item.get("source_grouping"))
        except SchemaError:
            continue
        groups.update(declaration.split_tokens())
        groups.update(_reviewed_group_tokens(item.get("source_grouping_study")))
    return groups


def verify_pose_dataset_separation(
    session: Session, training: PoseTrainingDataset, validation: PoseTrainingDataset
) -> None:
    if training.id == validation.id:
        raise ValidationError("Pose validation must use a separate frozen dataset")
    if (
        training.pose_schema_id,
        training.pose_schema_revision,
        training.pose_schema_content_hash,
    ) != (
        validation.pose_schema_id,
        validation.pose_schema_revision,
        validation.pose_schema_content_hash,
    ):
        raise ValidationError("Pose validation must use the same frozen anatomy revision")
    if _recording_keys(training) & _recording_keys(validation):
        raise ValidationError(
            "Training and validation share a recording or original video checksum"
        )
    if _frozen_group_keys(session, training) & _frozen_group_keys(session, validation):
        raise ValidationError("Training and validation share a recorded acquisition group")


def verify_reserved_pose_video(
    session: Session, video: VideoAsset, datasets: tuple[PoseTrainingDataset, PoseTrainingDataset]
) -> None:
    metadata = video.metadata_json or {}
    groups = set(_group_tokens(metadata))
    try:
        grouping = ReefPoseSourceGrouping.model_validate(metadata.get("source_grouping"))
    except SchemaError:
        pass
    else:
        groups.update(grouping.split_tokens())
    for dataset in datasets:
        if {video.id, video.sha256} & _recording_keys(dataset):
            raise ValidationError("The held-out recording appears in training or validation")
        if groups & _frozen_group_keys(session, dataset):
            raise ValidationError("The held-out recording shares a recorded acquisition group")

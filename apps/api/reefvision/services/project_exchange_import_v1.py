"""ReefVision 1.0 import extensions for complete portable project state."""

from __future__ import annotations

import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ActiveLearningRound,
    AnnotationEvent,
    BehaviorBoutRevision,
    BehaviorClassifierModel,
    BehaviorEthogramRevision,
    BehaviorPrediction,
    BehaviorStateDefinition,
    ClassOperation,
    ClassVisibilityPreference,
    DatasetVersion,
    ExportRecord,
    GeoReferencedObservation,
    MaskAnnotationEvent,
    Project,
    ProjectClassVisibilityDefault,
    ProjectExchangePackage,
    ReviewQueue,
    ReviewQueueItem,
    SkeletonAnalysisRevision,
    TrainingDraft,
    VideoAsset,
    VideoTrack,
)
from reefvision.db.models.pose_active_learning import (
    PoseActiveLearningCandidate,
    PoseActiveLearningRound,
)
from reefvision.db.models.pose_schema import (
    PoseLandmarkSchema,
    PoseLandmarkSchemaRevision,
    PoseModelSchemaBinding,
)
from reefvision.db.models.pose_tracking import (
    PoseLandmarkAssociationCandidate,
    PoseLandmarkAssociationDecision,
    PoseLandmarkCorrection,
    PoseLandmarkIdentityBreak,
    PoseLandmarkObservation,
    PoseLandmarkTrack,
)
from reefvision.db.models.pose_training_dataset import (
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
)
from reefvision.schemas.project_exchange import ProjectExchangeImportResponse
from reefvision.services import project_exchange_import as base_import
from reefvision.services.pose_active_learning import (
    PoseActiveLearningService,
)
from reefvision.services.pose_training_datasets import (
    ITEM_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path


def _insert_after(section_name: str, after: str) -> None:
    if section_name in base_import.SECTION_ORDER:
        return
    index = base_import.SECTION_ORDER.index(after)
    base_import.SECTION_ORDER.insert(index + 1, section_name)


def _register_v1_sections() -> None:
    base_import.SECTION_MODELS.update(
        {
            "training_drafts": TrainingDraft,
            "annotation_events": AnnotationEvent,
            "mask_annotation_events": MaskAnnotationEvent,
            "project_class_visibility_defaults": ProjectClassVisibilityDefault,
            "class_visibility_preferences": ClassVisibilityPreference,
            "class_operations": ClassOperation,
            "exports": ExportRecord,
            "georeferenced_observations": GeoReferencedObservation,
            "pose_landmark_schemas": PoseLandmarkSchema,
            "pose_landmark_schema_revisions": PoseLandmarkSchemaRevision,
            "pose_model_schema_bindings": PoseModelSchemaBinding,
            "pose_landmark_tracks": PoseLandmarkTrack,
            "pose_landmark_observations": PoseLandmarkObservation,
            "pose_landmark_association_decisions": PoseLandmarkAssociationDecision,
            "pose_landmark_association_candidates": PoseLandmarkAssociationCandidate,
            "pose_active_learning_rounds": PoseActiveLearningRound,
            "pose_landmark_corrections": PoseLandmarkCorrection,
            "pose_landmark_identity_breaks": PoseLandmarkIdentityBreak,
            "pose_active_learning_candidates": PoseActiveLearningCandidate,
            "pose_training_datasets": PoseTrainingDataset,
            "pose_training_dataset_items": PoseTrainingDatasetItem,
            "behavior_ethogram_revisions": BehaviorEthogramRevision,
            "behavior_state_definitions": BehaviorStateDefinition,
            "behavior_classifier_models": BehaviorClassifierModel,
            "behavior_predictions": BehaviorPrediction,
            "behavior_bout_revisions": BehaviorBoutRevision,
            "skeleton_analysis_revisions": SkeletonAnalysisRevision,
        }
    )

    _insert_after(
        "project_class_visibility_defaults",
        "label_classes",
    )
    _insert_after(
        "class_visibility_preferences",
        "project_class_visibility_defaults",
    )
    _insert_after(
        "class_operations",
        "class_visibility_preferences",
    )
    _insert_after("training_drafts", "models")
    _insert_after("exports", "dataset_version_items")
    _insert_after("annotation_events", "annotations")
    _insert_after("mask_annotation_events", "mask_annotations")
    _insert_after(
        "skeleton_analysis_revisions",
        "mask_annotation_events",
    )
    _insert_after(
        "georeferenced_observations",
        "video_tracks",
    )

    _insert_after("pose_landmark_schemas", "models")
    _insert_after(
        "pose_landmark_schema_revisions",
        "pose_landmark_schemas",
    )
    _insert_after(
        "pose_model_schema_bindings",
        "pose_landmark_schema_revisions",
    )

    _insert_after(
        "pose_landmark_tracks",
        "video_tracks",
    )
    _insert_after(
        "pose_landmark_observations",
        "pose_landmark_tracks",
    )
    _insert_after(
        "pose_landmark_association_decisions",
        "pose_landmark_observations",
    )
    _insert_after(
        "pose_landmark_association_candidates",
        "pose_landmark_association_decisions",
    )
    _insert_after(
        "pose_landmark_corrections",
        "pose_landmark_association_candidates",
    )
    _insert_after(
        "pose_landmark_identity_breaks",
        "pose_landmark_corrections",
    )
    _insert_after(
        "pose_active_learning_rounds",
        "pose_landmark_identity_breaks",
    )
    _insert_after(
        "pose_active_learning_candidates",
        "pose_active_learning_rounds",
    )
    _insert_after(
        "pose_training_datasets",
        "pose_active_learning_candidates",
    )
    _insert_after(
        "pose_training_dataset_items",
        "pose_training_datasets",
    )

    _insert_after(
        "behavior_ethogram_revisions",
        "video_tracks",
    )
    _insert_after(
        "behavior_state_definitions",
        "behavior_ethogram_revisions",
    )
    _insert_after(
        "behavior_classifier_models",
        "behavior_state_definitions",
    )
    _insert_after(
        "behavior_predictions",
        "behavior_classifier_models",
    )
    _insert_after(
        "behavior_bout_revisions",
        "behavior_predictions",
    )


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _restore_telemetry_sidecars(
    source: BinaryIO,
    *,
    project: Project,
    session: Session,
    settings: Settings,
    manifest: dict[str, object],
) -> int:
    """Restore portable SRT/AirData sources and rewrite imported metadata paths."""

    raw_descriptors = manifest.get(
        "telemetry_sidecars",
        [],
    )

    if not isinstance(raw_descriptors, list):
        raise ValueError("Telemetry sidecar inventory must be a list")

    descriptors: dict[
        tuple[str, str],
        dict[str, Any],
    ] = {}

    for index, value in enumerate(raw_descriptors):
        if not isinstance(value, dict):
            raise ValueError(f"Telemetry sidecar descriptor {index} is invalid")

        metadata_key = value.get("metadata_key")
        source_path = value.get("source_path")

        if metadata_key not in {
            "telemetry",
            "airdata_telemetry",
        }:
            raise ValueError(f"Telemetry sidecar metadata key is invalid: {index}")

        if not isinstance(source_path, str) or not source_path:
            raise ValueError(f"Telemetry sidecar source path is invalid: {index}")

        descriptors[
            (
                str(metadata_key),
                source_path,
            )
        ] = value

    if not descriptors:
        return 0

    copied = 0

    videos = list(session.scalars(select(VideoAsset).where(VideoAsset.project_id == project.id)))

    source.seek(0)

    with zipfile.ZipFile(source, "r") as archive:
        for video in videos:
            metadata = dict(video.metadata_json or {})
            changed = False

            for metadata_key in (
                "telemetry",
                "airdata_telemetry",
            ):
                raw_metadata = metadata.get(metadata_key)

                if not isinstance(
                    raw_metadata,
                    dict,
                ):
                    continue

                old_source = raw_metadata.get("source_path")

                if not isinstance(
                    old_source,
                    str,
                ):
                    continue

                descriptor = descriptors.get(
                    (
                        metadata_key,
                        old_source,
                    )
                )

                if descriptor is None:
                    continue

                archive_member = str(descriptor.get("path", ""))
                restore_relative = str(
                    descriptor.get(
                        "source_relative_path",
                        "",
                    )
                )

                if not _safe_relative_path(restore_relative):
                    raise ValueError("Telemetry sidecar restore path is unsafe")

                destination_relative = f"{project.storage_root}/{restore_relative}"

                destination = resolve_managed_project_path(
                    settings,
                    destination_relative,
                )

                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                with (
                    archive.open(
                        archive_member,
                        "r",
                    ) as input_stream,
                    destination.open("wb") as output_stream,
                ):
                    shutil.copyfileobj(
                        input_stream,
                        output_stream,
                    )

                updated = dict(raw_metadata)
                updated["source_path"] = destination_relative
                updated["path_kind"] = "managed"

                metadata[metadata_key] = updated

                changed = True
                copied += 1

            if changed:
                video.metadata_json = metadata

    session.flush()

    return copied


def _restore_generated_artifacts(
    source: BinaryIO,
    *,
    project: Project,
    settings: Settings,
    manifest: dict[str, object],
) -> int:
    raw_descriptors = manifest.get("generated_artifacts", [])
    if not isinstance(raw_descriptors, list):
        raise ValueError("Generated artifact inventory must be a list")

    copied = 0
    source.seek(0)
    with zipfile.ZipFile(source, "r") as archive:
        for index, descriptor_value in enumerate(raw_descriptors):
            if not isinstance(descriptor_value, dict):
                raise ValueError(f"Generated artifact descriptor {index} is invalid")
            member = str(descriptor_value.get("path", ""))
            source_relative_path = str(descriptor_value.get("source_relative_path", ""))
            if not _safe_relative_path(member) or not _safe_relative_path(source_relative_path):
                raise ValueError(f"Generated artifact path {index} is unsafe")
            destination_relative = f"{project.storage_root.rstrip('/')}/{source_relative_path}"
            destination = resolve_managed_project_path(settings, destination_relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with (
                archive.open(member, "r") as archive_stream,
                destination.open("wb") as output_stream,
            ):
                shutil.copyfileobj(archive_stream, output_stream)
            copied += 1
    return copied


def _operation_checksum(operation: ClassOperation) -> str:
    plan: dict[str, Any] = dict(operation.plan_json or {})

    def records(key: str) -> list[dict[str, object]]:
        raw = plan.get(key, [])
        if not isinstance(raw, list):
            return []
        return [
            {
                "key": str(item.get("key", "")),
                "record_ids": list(item.get("record_ids", [])),
            }
            for item in raw
            if isinstance(item, dict)
        ]

    raw_impacts = plan.get("compatibility_impacts", [])
    impacts = (
        [
            {
                "key": str(item.get("key", "")),
                "status": str(item.get("status", "")),
                "record_ids": list(item.get("record_ids", [])),
            }
            for item in raw_impacts
            if isinstance(item, dict)
        ]
        if isinstance(raw_impacts, list)
        else []
    )
    payload = {
        "operation_type": operation.operation_type,
        "project_id": operation.project_id,
        "source_class_id": operation.source_class_id,
        "target_class_id": operation.target_class_id,
        "mutable_records": records("mutable_records"),
        "protected_records": records("protected_records"),
        "blocking_records": records("blocking_records"),
        "compatibility_impacts": impacts,
        "warnings": list(plan.get("warnings", [])),
        "blockers": list(plan.get("blockers", [])),
    }
    return canonical_json_sha256(payload)


def _refresh_class_operation_checksums(session: Session, project_id: str) -> None:
    operations = list(
        session.scalars(select(ClassOperation).where(ClassOperation.project_id == project_id))
    )
    for operation in operations:
        operation.preview_checksum = _operation_checksum(operation)
    session.flush()


def _refresh_review_queue_checksums(session: Session, project_id: str) -> None:
    queues = list(session.scalars(select(ReviewQueue).where(ReviewQueue.project_id == project_id)))
    items = list(
        session.scalars(select(ReviewQueueItem).where(ReviewQueueItem.project_id == project_id))
    )
    items_by_queue: dict[str, list[ReviewQueueItem]] = {}
    for item in items:
        items_by_queue.setdefault(item.review_queue_id, []).append(item)

    for queue in queues:
        queue_items = sorted(
            items_by_queue.get(queue.id, []),
            key=lambda item: (item.rank_position, item.image_id, item.id),
        )
        source_item_checksums = {item.id: item.input_checksum for item in queue_items}
        source_queue_checksums = dict(queue.input_checksums_json or {})
        configuration = dict(queue.configuration_json or {})
        configuration["exchange_import"] = {
            "checksum_schema": "review-queue-item-exchange-import-0001",
            "source_queue_input_checksums": source_queue_checksums,
            "source_item_checksums_by_imported_item_id": source_item_checksums,
        }
        queue.configuration_json = configuration

        for item in queue_items:
            item.input_checksum = canonical_json_sha256(
                {
                    "schema_version": "review-queue-item-exchange-import-0001",
                    "review_queue_id": item.review_queue_id,
                    "project_id": item.project_id,
                    "dataset_version_id": item.dataset_version_id,
                    "image_id": item.image_id,
                    "split": item.split,
                    "score": item.score,
                    "rank_position": item.rank_position,
                    "highest_qc_severity": item.highest_qc_severity,
                    "label_class_ids": item.label_class_ids_json,
                    "model_ids": item.model_ids_json,
                    "related_issue_ids": item.related_issue_ids_json,
                    "signal_values": item.signal_values_json,
                    "normalized_signals": item.normalized_signals_json,
                    "weights": item.weights_json,
                    "score_breakdown": item.score_breakdown_json,
                }
            )

        queue.input_checksums_json = {
            "queue_scope_sha256": canonical_json_sha256(
                {
                    "image_ids": sorted(item.image_id for item in queue_items),
                    "scores": {item.image_id: item.score for item in queue_items},
                    "source_quality_control_run_id": queue.source_quality_control_run_id,
                }
            ),
            "item_count": len(queue_items),
        }
    session.flush()


def _refresh_active_learning_checksums(session: Session, project_id: str) -> None:
    rounds = list(
        session.scalars(
            select(ActiveLearningRound).where(ActiveLearningRound.project_id == project_id)
        )
    )
    queue_items = list(
        session.scalars(select(ReviewQueueItem).where(ReviewQueueItem.project_id == project_id))
    )
    items_by_id = {item.id: item for item in queue_items}

    for round_record in rounds:
        source_selection_sha256 = round_record.selection_sha256
        manifest = dict(round_record.selection_manifest_json or {})
        raw_items = manifest.get("items", [])
        refreshed_items: list[dict[str, Any]] = []
        if isinstance(raw_items, list):
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                item = dict(raw_item)
                queue_item_id = item.get("queue_item_id")
                queue_item = (
                    items_by_id.get(queue_item_id) if isinstance(queue_item_id, str) else None
                )
                if queue_item is not None:
                    item["input_checksum"] = queue_item.input_checksum
                refreshed_items.append(item)
        manifest["items"] = refreshed_items
        round_record.selection_manifest_json = manifest

        stable_items = [
            {
                "image_id": item.get("image_id"),
                "rank_position": item.get("rank_position"),
                "score": item.get("score"),
                "input_checksum": item.get("input_checksum"),
            }
            for item in refreshed_items
        ]
        weights = manifest.get("weights")
        if not isinstance(weights, dict):
            strategy_config = dict(round_record.strategy_config_json or {})
            raw_weights = strategy_config.get("weights", {})
            weights = raw_weights if isinstance(raw_weights, dict) else {}
        identity_payload = {
            "schema_version": "active-learning-identity-0001",
            "project_id": round_record.project_id,
            "dataset_version_id": round_record.dataset_version_id,
            "strategy": round_record.strategy,
            "model_ids": round_record.model_ids_json,
            "requested_size": round_record.requested_size,
            "queue_formula_id": manifest.get("queue_formula_id"),
            "queue_formula_version": manifest.get("queue_formula_version"),
            "weights": weights,
            "items": stable_items,
        }
        round_record.selection_sha256 = canonical_json_sha256(identity_payload)

        strategy_config = dict(round_record.strategy_config_json or {})
        strategy_config["exchange_import"] = {
            "source_selection_sha256": source_selection_sha256,
            "selection_checksum_schema": "active-learning-identity-0001",
        }
        round_record.strategy_config_json = strategy_config

        feedback_summary = dict(round_record.feedback_summary_json or {})
        feedback_dataset_id = feedback_summary.get("feedback_dataset_version_id")
        if isinstance(feedback_dataset_id, str):
            feedback_dataset = session.get(DatasetVersion, feedback_dataset_id)
            if feedback_dataset is not None:
                feedback_summary["feedback_manifest_sha256"] = feedback_dataset.manifest_sha256
        round_record.feedback_summary_json = feedback_summary
    session.flush()


def _mark_imported_georeferencing_stale(
    session: Session,
    project_id: str,
) -> None:
    """Retain imported coordinates while invalidating source configuration freshness."""

    observations = list(
        session.scalars(
            select(GeoReferencedObservation).where(
                GeoReferencedObservation.project_id == project_id
            )
        )
    )

    if not observations:
        return

    stale_at = datetime.now(UTC)

    for observation in observations:
        # The source configuration hash is retained as provenance, but cannot
        # represent the imported project's current configuration because
        # project/video/track identities are remapped during exchange import.
        observation.is_stale = True
        observation.stale_reason = "exchange_import_id_remap"
        observation.stale_at = stale_at

        payload = dict(observation.payload_json or {})

        # The scalar DB linkage is authoritative after ID remapping. Keep the
        # canonical payload internally consistent so later detail reads and
        # explicit recomputation operate on imported identities only.
        payload.update(
            {
                "id": observation.id,
                "project_id": observation.project_id,
                "video_asset_id": observation.video_id,
                "track_id": observation.track_id,
                "detection_id": observation.detection_id,
            }
        )

        observation.payload_json = payload

    session.flush()


def _refresh_pose_training_exchange_integrity(
    session: Session,
    project_id: str,
) -> None:
    """Rebuild pose AL/training hashes after deterministic exchange ID remapping."""

    rounds = list(
        session.scalars(
            select(PoseActiveLearningRound).where(PoseActiveLearningRound.project_id == project_id)
        )
    )

    if not rounds:
        return

    round_ids = [item.id for item in rounds]

    candidates = list(
        session.scalars(
            select(PoseActiveLearningCandidate).where(
                PoseActiveLearningCandidate.round_id.in_(round_ids)
            )
        )
    )

    candidates_by_round: dict[
        str,
        list[PoseActiveLearningCandidate],
    ] = {}

    for candidate in candidates:
        candidates_by_round.setdefault(
            candidate.round_id,
            [],
        ).append(candidate)

        candidate.provenance_sha256 = canonical_json_sha256(dict(candidate.provenance_json or {}))

        if candidate.review_status != "verified":
            continue

        track = session.get(
            VideoTrack,
            candidate.video_track_id,
        )

        if track is None:
            raise RuntimeError("Imported verified pose candidate lost its video track")

        keyframe = next(
            (
                dict(item)
                for item in track.keyframes_json
                if int(
                    item.get(
                        "frame",
                        -1,
                    )
                )
                == candidate.focus_frame
            ),
            None,
        )

        if keyframe is None:
            raise RuntimeError("Imported verified pose candidate lost its canonical frame")

        verified_payload = {
            "schema_version": ("pose-active-learning-verified-pose-0001"),
            "video_track_id": track.id,
            "track_revision": track.revision,
            "focus_frame": candidate.focus_frame,
            "pose_schema_id": candidate.pose_schema_id,
            "pose_schema_revision": (candidate.pose_schema_revision),
            "pose_observations": list(keyframe.get("pose_observations") or []),
            "keypoints": list(keyframe.get("keypoints") or []),
        }

        candidate.verified_pose_sha256 = canonical_json_sha256(verified_payload)

        if candidate.correction_id is not None:
            correction = session.get(
                PoseLandmarkCorrection,
                candidate.correction_id,
            )

            if correction is None:
                raise RuntimeError("Imported verified pose candidate lost its scientist correction")

            correction.parent_video_track_id = track.id
            correction.target_id = candidate.id

            before = dict(correction.before_json or {})

            before.update(
                {
                    "candidate_id": candidate.id,
                    "source_track_revision": (candidate.source_track_revision),
                    "candidate_provenance_sha256": (candidate.provenance_sha256),
                    "acquisition_score": (candidate.acquisition_score),
                    "score_components": dict(candidate.score_components_json or {}),
                    "reason_codes": list(candidate.reason_codes_json or []),
                }
            )

            after = dict(correction.after_json or {})

            after.update(
                {
                    "verified_track_revision": (candidate.verified_track_revision),
                    "verified_pose_sha256": (candidate.verified_pose_sha256),
                    "pose_schema_id": (candidate.pose_schema_id),
                    "pose_schema_revision": (candidate.pose_schema_revision),
                }
            )

            correction.before_json = before
            correction.after_json = after

    session.flush()

    for round_record in rounds:
        round_candidates = candidates_by_round.get(
            round_record.id,
            [],
        )

        candidate_by_key = {
            (
                item.video_track_id,
                item.focus_frame,
            ): item
            for item in round_candidates
        }

        manifest = dict(round_record.selection_manifest_json or {})

        raw_items = manifest.get(
            "items",
            [],
        )

        refreshed_items: list[dict[str, Any]] = []

        if isinstance(
            raw_items,
            list,
        ):
            for raw_item in raw_items:
                if not isinstance(
                    raw_item,
                    dict,
                ):
                    continue

                manifest_item = dict(raw_item)

                video_track_id = manifest_item.get("video_track_id")
                focus_frame = manifest_item.get("focus_frame")

                manifest_candidate = (
                    candidate_by_key.get(
                        (
                            video_track_id,
                            focus_frame,
                        )
                    )
                    if (
                        isinstance(
                            video_track_id,
                            str,
                        )
                        and isinstance(
                            focus_frame,
                            int,
                        )
                        and not isinstance(
                            focus_frame,
                            bool,
                        )
                    )
                    else None
                )

                if manifest_candidate is not None:
                    manifest_item["provenance_sha256"] = manifest_candidate.provenance_sha256

                refreshed_items.append(manifest_item)

        manifest["items"] = refreshed_items
        manifest["project_id"] = round_record.project_id
        manifest["video_id"] = round_record.video_id
        manifest["model_ids"] = list(round_record.model_ids_json or [])

        round_record.selection_manifest_json = manifest

        identity_manifest = dict(manifest)

        identity_manifest["schema_version"] = "pose-active-learning-selection-identity-0001"

        round_record.selection_sha256 = canonical_json_sha256(identity_manifest)

    session.flush()

    datasets = list(
        session.scalars(
            select(PoseTrainingDataset).where(PoseTrainingDataset.project_id == project_id)
        )
    )

    for dataset in datasets:
        source_round_record = session.get(
            PoseActiveLearningRound,
            dataset.source_round_id,
        )

        if source_round_record is None:
            raise RuntimeError("Imported pose training dataset lost its Active Learning round")

        retraining_manifest = (
            PoseActiveLearningService(session)
            .export_manifest(source_round_record.id)
            .model_dump(mode="json")
        )

        dataset.source_selection_sha256 = source_round_record.selection_sha256

        dataset.source_retraining_manifest_sha256 = canonical_json_sha256(retraining_manifest)

        items = list(
            session.scalars(
                select(PoseTrainingDatasetItem)
                .where(PoseTrainingDatasetItem.dataset_id == dataset.id)
                .order_by(
                    PoseTrainingDatasetItem.video_id,
                    PoseTrainingDatasetItem.video_track_id,
                    PoseTrainingDatasetItem.frame_index,
                    PoseTrainingDatasetItem.id,
                )
            )
        )

        if len(items) != dataset.item_count:
            raise RuntimeError(
                "Imported pose training dataset item count does not match its frozen record"
            )

        summaries: list[dict[str, Any]] = []

        for dataset_item in items:
            dataset_candidate = session.get(
                PoseActiveLearningCandidate,
                dataset_item.candidate_id,
            )

            if dataset_candidate is None:
                raise RuntimeError("Imported frozen pose item lost its Active Learning candidate")

            track = session.get(
                VideoTrack,
                dataset_item.video_track_id,
            )

            if track is None:
                raise RuntimeError("Imported frozen pose item lost its video track")

            video = session.get(
                VideoAsset,
                dataset_item.video_id,
            )

            if video is None:
                raise RuntimeError("Imported frozen pose item lost its video")

            if dataset_candidate.verified_pose_sha256 is None:
                raise RuntimeError(
                    "Imported frozen pose item candidate is missing its verified pose checksum"
                )

            dataset_item.verified_pose_sha256 = dataset_candidate.verified_pose_sha256

            dataset_item.acquisition_provenance_json = dict(dataset_candidate.provenance_json or {})

            review = dict(dataset_item.review_provenance_json or {})

            review["correction_id"] = dataset_candidate.correction_id

            review["target_id"] = dataset_candidate.id

            review["reviewed_by"] = dataset_candidate.reviewed_by

            if dataset_candidate.reviewed_at is not None:
                review["reviewed_at"] = dataset_candidate.reviewed_at.isoformat()

            review_before = review.get("before")

            if isinstance(
                review_before,
                dict,
            ):
                review_before = dict(review_before)
                review_before["candidate_id"] = dataset_candidate.id
                review_before["candidate_provenance_sha256"] = dataset_candidate.provenance_sha256
                review["before"] = review_before

            review_after = review.get("after")

            if isinstance(
                review_after,
                dict,
            ):
                review_after = dict(review_after)
                review_after["verified_pose_sha256"] = dataset_candidate.verified_pose_sha256
                review_after["pose_schema_id"] = dataset_candidate.pose_schema_id
                review_after["pose_schema_revision"] = dataset_candidate.pose_schema_revision
                review["after"] = review_after

            dataset_item.review_provenance_json = review

            item_payload = {
                "schema_version": (ITEM_SCHEMA_VERSION),
                "dataset_id": dataset.id,
                "candidate_id": dataset_candidate.id,
                "project_id": dataset.project_id,
                "source_round_id": (dataset.source_round_id),
                "video": {
                    "video_id": video.id,
                    "sha256": video.sha256,
                    "revision": (dataset_item.video_revision),
                    "original_filename": (video.original_filename),
                    "width_px": (video.width_px),
                    "height_px": (video.height_px),
                    "frame_count": (video.frame_count),
                    "fps": video.fps,
                },
                "video_track_id": track.id,
                "label_class_id": (dataset_item.label_class_id),
                "verified_track_revision": (dataset_item.verified_track_revision),
                "pose_schema": {
                    "schema_version": ("pose-landmarks-0001"),
                    "schema_id": (dataset_item.pose_schema_id),
                    "schema_revision": (dataset_item.pose_schema_revision),
                    "content_hash": (dataset_item.pose_schema_content_hash),
                },
                "verified_pose_sha256": (dataset_item.verified_pose_sha256),
                "canonical_pose": dict(dataset_item.canonical_pose_json or {}),
                "source_models": list(dataset_item.source_models_json or []),
                "source_job_ids": list(dataset_item.source_job_ids_json or []),
                "acquisition_provenance": dict(dataset_item.acquisition_provenance_json or {}),
                "candidate_provenance_sha256": (dataset_candidate.provenance_sha256),
                "review_provenance": dict(dataset_item.review_provenance_json or {}),
            }

            dataset_item.item_sha256 = canonical_json_sha256(item_payload)

            summaries.append(
                {
                    "item_id": dataset_item.id,
                    "item_sha256": (dataset_item.item_sha256),
                    "candidate_id": (dataset_candidate.id),
                    "video_id": (video.id),
                    "video_sha256": (video.sha256),
                    "video_track_id": (track.id),
                    "frame_index": (dataset_item.frame_index),
                    "verified_track_revision": (dataset_item.verified_track_revision),
                    "verified_pose_sha256": (dataset_item.verified_pose_sha256),
                    "pose_schema_id": (dataset_item.pose_schema_id),
                    "pose_schema_revision": (dataset_item.pose_schema_revision),
                    "pose_schema_content_hash": (dataset_item.pose_schema_content_hash),
                    "candidate_provenance_sha256": (dataset_candidate.provenance_sha256),
                    "correction_id": (dataset_candidate.correction_id),
                }
            )

        dataset.manifest_json = {
            "schema_version": (MANIFEST_SCHEMA_VERSION),
            "dataset_id": dataset.id,
            "project_id": (dataset.project_id),
            "source_round_id": (source_round_record.id),
            "source_selection_sha256": (dataset.source_selection_sha256),
            "source_retraining_manifest_sha256": (dataset.source_retraining_manifest_sha256),
            "pose_schema": {
                "schema_id": (dataset.pose_schema_id),
                "schema_revision": (dataset.pose_schema_revision),
                "content_hash": (dataset.pose_schema_content_hash),
            },
            "truth_policy": ("scientist_verified_only"),
            "skipped_candidates_included": False,
            "pending_candidates_included": False,
            "item_count": len(items),
            "items": summaries,
        }

        dataset.manifest_sha256 = canonical_json_sha256(dataset.manifest_json)

    session.flush()


def import_project_exchange_v1(
    source: BinaryIO,
    session: Session,
    settings: Settings,
    *,
    project_name: str | None = None,
) -> ProjectExchangeImportResponse:
    """Import the complete 1.0 portable record inventory into a new project."""

    _register_v1_sections()
    copied_generated = 0

    def finalize(project: Project, package: ProjectExchangePackage) -> None:
        nonlocal copied_generated
        _mark_imported_georeferencing_stale(session, project.id)
        _refresh_class_operation_checksums(session, project.id)
        _refresh_review_queue_checksums(session, project.id)
        _refresh_active_learning_checksums(session, project.id)
        _refresh_pose_training_exchange_integrity(session, project.id)
        # Validate canonical ownership/run lineage after remapping, before commit.
        from reefvision.db.models import ScientificRecord
        from reefvision.schemas.scientific_data import ScientificRecordCreate
        from reefvision.services.scientific_data import ScientificDataService

        science = ScientificDataService(session)
        for row in session.scalars(
            select(ScientificRecord).where(ScientificRecord.project_id == project.id)
        ):
            item = ScientificRecordCreate.model_validate(
                {
                    key: value
                    for key, value in row.payload_json.items()
                    if key in ScientificRecordCreate.model_fields
                }
            )
            science.validate_subject(project.id, item.subject, item.pixel)
            science.response(row)
        copied_telemetry = _restore_telemetry_sidecars(
            source,
            project=project,
            session=session,
            settings=settings,
            manifest=dict(package.manifest_json),
        )
        copied_generated = _restore_generated_artifacts(
            source, project=project, settings=settings, manifest=dict(package.manifest_json)
        )
        package.options_json = {
            **dict(package.options_json or {}),
            "copied_generated_artifact_count": copied_generated,
            "copied_telemetry_sidecar_count": copied_telemetry,
        }

    result = base_import.import_project_exchange(
        source, session, settings, project_name=project_name, finalize=finalize
    )
    result.copied_generated_artifact_count = copied_generated
    return result

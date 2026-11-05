"""Immutable pose-training dataset materialization and native packaging."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    ModelRegistration,
    PoseActiveLearningCandidate,
    PoseActiveLearningRound,
    PoseLandmarkCorrection,
    PoseLandmarkSchema,
    PoseLandmarkSchemaRevision,
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
    VideoAsset,
    VideoTrack,
)
from reefvision.domain.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from reefvision.schemas.pose_training_datasets import (
    PoseTrainingDatasetCreateRequest,
    PoseTrainingDatasetItemResponse,
    PoseTrainingDatasetManifestResponse,
    PoseTrainingDatasetResponse,
)
from reefvision.services.pose_active_learning import (
    PoseActiveLearningService,
)
from reefvision.storage.datasets import canonical_json_sha256

DATASET_SCHEMA_VERSION = "pose-training-dataset-0001"
MANIFEST_SCHEMA_VERSION = "pose-training-dataset-manifest-0001"
ITEM_SCHEMA_VERSION = "pose-training-dataset-item-0001"
PACKAGE_MANIFEST_FILENAME = "reefvision-pose-training-manifest.json"
PACKAGE_ITEMS_FILENAME = "items.jsonl"
PACKAGE_CHECKSUMS_FILENAME = "SHA256SUMS"


def frozen_pose_item_evidence_sha256(item: PoseTrainingDatasetItem) -> str:
    """Fingerprint frozen review and model provenance beyond landmark geometry."""
    return canonical_json_sha256(
        {
            "video_revision": item.video_revision,
            "label_class_id": item.label_class_id,
            "source_models": item.source_models_json,
            "source_job_ids": item.source_job_ids_json,
            "review_provenance": item.review_provenance_json,
        }
    )


def frozen_pose_item_fingerprints_match(
    session: Session,
    dataset: PoseTrainingDataset,
) -> bool:
    """Compare signed item summaries with independently persisted frozen items."""
    manifest = dataset.manifest_json
    if (
        dataset.schema_version != DATASET_SCHEMA_VERSION
        or not isinstance(manifest, dict)
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or not isinstance(manifest.get("items"), list)
    ):
        return False

    rows = session.scalars(
        select(PoseTrainingDatasetItem).where(PoseTrainingDatasetItem.dataset_id == dataset.id)
    ).all()
    # A re-signed, emptied dataset is not scientist-verified training truth.
    # Freezing requires at least one verified item, even if the row count,
    # manifest, and checksum have all been changed to agree on zero.
    if (
        not isinstance(dataset.item_count, int)
        or isinstance(dataset.item_count, bool)
        or dataset.item_count < 1
        or len(rows) != dataset.item_count
    ):
        return False

    # A frozen candidate may contribute only one verified training item.
    # Duplicate candidate rows can otherwise overweight one human review even
    # when every individual item and the re-signed manifest appear valid.
    if len({row.candidate_id for row in rows}) != len(rows):
        return False

    # A matching manifest and item_sha256 column cannot prove that the
    # persisted canonical landmarks are still the scientist-verified pose.
    # Recompute the original verification fingerprint from frozen row data.
    for row in rows:
        # Every verified item must retain the frozen dataset's single landmark
        # schema identity, even if its summary and manifest are re-signed.
        if (
            row.pose_schema_id != dataset.pose_schema_id
            or row.pose_schema_revision != dataset.pose_schema_revision
            or row.pose_schema_content_hash != dataset.pose_schema_content_hash
        ):
            return False
        # Frozen human-review evidence must remain a valid verification record.
        # Otherwise a corrupted JSON value could raise an AttributeError
        # instead of rejecting the dataset before export or workflow execution.
        review = row.review_provenance_json
        # Persisted model/job lineage is part of frozen scientific evidence.
        # Reject malformed JSON collections even if a manifest is re-signed.
        if (
            not isinstance(row.source_models_json, list)
            or any(
                not isinstance(model, dict)
                or not isinstance(model.get("model_id"), str)
                or not model["model_id"].strip()
                or model["model_id"] != model["model_id"].strip()
                for model in row.source_models_json
            )
            or not isinstance(row.source_job_ids_json, list)
            or any(
                not isinstance(job_id, str) or not job_id.strip() or job_id != job_id.strip()
                for job_id in row.source_job_ids_json
            )
        ):
            return False
        # Duplicate source identifiers make lineage ambiguous for downstream
        # training and scientific audit, even when the manifest is re-signed.
        if len({model["model_id"] for model in row.source_models_json}) != len(
            row.source_models_json
        ) or len(set(row.source_job_ids_json)) != len(row.source_job_ids_json):
            return False
        if (
            not isinstance(row.acquisition_provenance_json, dict)
            or not isinstance(review, dict)
            or review.get("action") != "verify_active_learning_pose"
            or review.get("target_type") != "pose_active_learning_candidate"
            or review.get("target_id") != row.candidate_id
            or not isinstance(review.get("correction_id"), str)
            or not review["correction_id"].strip()
            # Re-signing a manifest cannot turn an unattributed or conflicting
            # review into scientist-verified training truth.
            or not isinstance(review.get("actor"), str)
            or not review["actor"].strip()
            or review["actor"] != review["actor"].strip()
            or review.get("reviewed_by") != review["actor"]
            or not isinstance(review.get("reviewed_at"), str)
            or not review["reviewed_at"].strip()
        ):
            return False
        # The correction's before/after snapshots are scientific audit
        # evidence, not just arbitrary metadata. A re-signed manifest must
        # not silently substitute the pose, schema, or acquisition lineage.
        before = review.get("before")
        after = review.get("after")
        # The acquisition record is independently frozen, but its original
        # source identities must still agree with the persisted verified item.
        # Otherwise a re-signed manifest and review digest could substitute a
        # different video, track, frame, or schema without changing the pose.
        acquisition = row.acquisition_provenance_json
        if (
            acquisition.get("schema_version") != "pose-active-learning-provenance-0001"
            or acquisition.get("project_id") != dataset.project_id
            or acquisition.get("video_id") != row.video_id
            or not isinstance(row.video_sha256, str)
            or not row.video_sha256.strip()
            or acquisition.get("video_sha256") != row.video_sha256
            or acquisition.get("video_track_id") != row.video_track_id
            or type(acquisition.get("focus_frame")) is not int
            or acquisition["focus_frame"] != row.frame_index
            or acquisition.get("pose_schema_id") != row.pose_schema_id
            or acquisition.get("pose_schema_revision") != row.pose_schema_revision
        ):
            return False
        source_provenance_sha = canonical_json_sha256(acquisition)
        if (
            not isinstance(before, dict)
            or before.get("candidate_id") != row.candidate_id
            or before.get("candidate_provenance_sha256") != source_provenance_sha
            or not isinstance(after, dict)
            or after.get("verified_track_revision") != row.verified_track_revision
            or after.get("verified_pose_sha256") != row.verified_pose_sha256
            or after.get("pose_schema_id") != row.pose_schema_id
            or after.get("pose_schema_revision") != row.pose_schema_revision
        ):
            return False

        # Both timestamps originate from datetime.isoformat() when the
        # scientist verifies a pose. A date-only string is accepted by
        # datetime.fromisoformat(), but is not a verification timestamp.
        # Preserve existing timezone-naive historical records while rejecting
        # malformed or missing correction/review time evidence.
        for field in ("reviewed_at", "correction_created_at"):
            timestamp = review.get(field)
            if not isinstance(timestamp, str) or len(timestamp) < 19 or timestamp[10] != "T":
                return False
            try:
                datetime.fromisoformat(timestamp)
            except ValueError:
                return False

        canonical_pose = row.canonical_pose_json
        if (
            not isinstance(canonical_pose, dict)
            or canonical_pose.get("schema_version") != "reefvision-canonical-pose-frame-0001"
            or type(canonical_pose.get("frame_index")) is not int
            or canonical_pose["frame_index"] != row.frame_index
        ):
            return False
        # A matching recomputed hash cannot make an empty, re-signed pose
        # scientifically valid. Freezing requires at least one verified
        # landmark; enforce that invariant on every later read and export.
        observations = canonical_pose.get("pose_observations")
        keypoints = canonical_pose.get("keypoints")
        if (
            not isinstance(observations, list)
            or not isinstance(keypoints, list)
            or (not observations and not keypoints)
        ):
            return False
        verified_payload = {
            "schema_version": "pose-active-learning-verified-pose-0001",
            "video_track_id": row.video_track_id,
            "track_revision": row.verified_track_revision,
            "focus_frame": row.frame_index,
            "pose_schema_id": row.pose_schema_id,
            "pose_schema_revision": row.pose_schema_revision,
            "pose_observations": canonical_pose.get("pose_observations"),
            "keypoints": canonical_pose.get("keypoints"),
        }
        if canonical_json_sha256(verified_payload) != row.verified_pose_sha256:
            return False

    # Fingerprints alone do not bind the manifest's source identities to
    # persisted items: a re-signed summary could otherwise swap candidate,
    # video, track, frame, or schema lineage without changing item_sha256.
    expected = {
        row.id: {
            "item_sha256": row.item_sha256,
            "candidate_id": row.candidate_id,
            "video_id": row.video_id,
            "video_sha256": row.video_sha256,
            "video_track_id": row.video_track_id,
            "frame_index": row.frame_index,
            "verified_track_revision": row.verified_track_revision,
            "verified_pose_sha256": row.verified_pose_sha256,
            "pose_schema_id": row.pose_schema_id,
            "pose_schema_revision": row.pose_schema_revision,
            "pose_schema_content_hash": row.pose_schema_content_hash,
            # The source candidate hash must remain bound to the frozen
            # acquisition provenance, even if the manifest is re-signed.
            "candidate_provenance_sha256": canonical_json_sha256(row.acquisition_provenance_json),
            "correction_id": (row.review_provenance_json or {}).get("correction_id"),
        }
        for row in rows
    }
    observed: dict[str, dict[str, Any]] = {}
    rows_by_id = {row.id: row for row in rows}
    for summary in manifest["items"]:
        if not isinstance(summary, dict) or not isinstance(summary.get("item_id"), str):
            return False
        item_id = summary["item_id"]
        if item_id in observed:
            return False
        # New frozen manifests bind the *entire* canonical frame, including
        # crop bbox and confidence omitted from the verified-landmark digest.
        # Legacy manifests without this additive field remain readable.
        if "canonical_pose_sha256" in summary:
            manifest_row = rows_by_id.get(item_id)
            if manifest_row is None or summary["canonical_pose_sha256"] != canonical_json_sha256(
                manifest_row.canonical_pose_json
            ):
                return False
        # Newly frozen manifests also bind model provenance, review actor,
        # and source job identities. Legacy manifests remain readable.
        if "frozen_evidence_sha256" in summary:
            manifest_row = rows_by_id.get(item_id)
            if manifest_row is None or summary[
                "frozen_evidence_sha256"
            ] != frozen_pose_item_evidence_sha256(manifest_row):
                return False
        observed[item_id] = {field: summary.get(field) for field in expected.get(item_id, {})}
    return observed == expected


class PoseTrainingDatasetService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _dataset(
        self,
        dataset_id: str,
    ) -> PoseTrainingDataset:
        dataset = self.session.get(
            PoseTrainingDataset,
            dataset_id,
        )
        if dataset is None:
            raise NotFoundError("Pose training dataset not found")
        return dataset

    def _round(
        self,
        round_id: str,
    ) -> PoseActiveLearningRound:
        round_record = self.session.get(
            PoseActiveLearningRound,
            round_id,
        )
        if round_record is None:
            raise NotFoundError("Pose Active Learning round not found")
        return round_record

    def list_datasets(
        self,
        project_id: str,
    ) -> list[PoseTrainingDatasetResponse]:
        rows = self.session.scalars(
            select(PoseTrainingDataset)
            .where(PoseTrainingDataset.project_id == project_id)
            .order_by(
                PoseTrainingDataset.created_at.desc(),
                PoseTrainingDataset.id,
            )
        )
        # Listing is also a scientific-data read path: never advertise a
        # corrupted frozen dataset as complete when direct retrieval rejects it.
        datasets = list(rows)
        for dataset in datasets:
            self.manifest(dataset.id)
        return [PoseTrainingDatasetResponse.model_validate(row) for row in datasets]

    def get_dataset(
        self,
        dataset_id: str,
    ) -> PoseTrainingDatasetResponse:
        # A direct dataset lookup must not advertise altered frozen science
        # as complete when item retrieval and native export reject it.
        self.manifest(dataset_id)
        return PoseTrainingDatasetResponse.model_validate(self._dataset(dataset_id))

    def items(
        self,
        dataset_id: str,
    ) -> list[PoseTrainingDatasetItemResponse]:
        # Never expose altered frozen landmarks or provenance through the
        # item-list API when manifest retrieval and native export reject them.
        self.manifest(dataset_id)
        rows = self.session.scalars(
            select(PoseTrainingDatasetItem)
            .where(PoseTrainingDatasetItem.dataset_id == dataset_id)
            .order_by(
                PoseTrainingDatasetItem.video_id,
                PoseTrainingDatasetItem.video_track_id,
                PoseTrainingDatasetItem.frame_index,
                PoseTrainingDatasetItem.id,
            )
        )
        return [PoseTrainingDatasetItemResponse.model_validate(row) for row in rows]

    def manifest(
        self,
        dataset_id: str,
    ) -> PoseTrainingDatasetManifestResponse:
        dataset = self._dataset(dataset_id)
        if not isinstance(dataset.manifest_json, dict):
            raise ConflictError("Pose training dataset manifest must be a JSON object")
        if canonical_json_sha256(dataset.manifest_json) != dataset.manifest_sha256:
            raise ConflictError(
                "Pose training dataset manifest checksum no longer matches frozen content"
            )
        # Retrieval must enforce the same frozen metadata and verification
        # policy as native export and Workflow Builder execution. A re-signed
        # checksum alone does not make changed source lineage trustworthy.
        manifest = dataset.manifest_json
        pose_schema = manifest.get("pose_schema")
        if (
            dataset.status != "complete"
            or dataset.schema_version != DATASET_SCHEMA_VERSION
            or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
            or manifest.get("dataset_id") != dataset.id
            or manifest.get("project_id") != dataset.project_id
            or manifest.get("source_round_id") != dataset.source_round_id
            or manifest.get("source_selection_sha256") != dataset.source_selection_sha256
            or manifest.get("source_retraining_manifest_sha256")
            != dataset.source_retraining_manifest_sha256
            or not isinstance(pose_schema, dict)
            or pose_schema.get("schema_id") != dataset.pose_schema_id
            or pose_schema.get("schema_revision") != dataset.pose_schema_revision
            or pose_schema.get("content_hash") != dataset.pose_schema_content_hash
        ):
            raise ConflictError(
                "Pose training dataset manifest lineage no longer matches frozen truth"
            )
        if (
            manifest.get("truth_policy") != "scientist_verified_only"
            or manifest.get("skipped_candidates_included") is not False
            or manifest.get("pending_candidates_included") is not False
        ):
            raise ConflictError(
                "Pose training dataset manifest must contain only scientist-verified items"
            )
        if (
            not isinstance(manifest.get("items"), list)
            or type(manifest.get("item_count")) is not int
            or manifest.get("item_count") != dataset.item_count
            or len(manifest["items"]) != dataset.item_count
        ):
            raise ConflictError(
                "Pose training dataset manifest item count no longer matches frozen truth"
            )
        # A valid manifest checksum alone cannot authenticate the persisted
        # scientist-verified poses or their frozen source identities.
        if not frozen_pose_item_fingerprints_match(self.session, dataset):
            raise ConflictError(
                "Pose training dataset item lineage no longer matches persisted verified items"
            )
        return PoseTrainingDatasetManifestResponse(
            dataset_id=dataset.id,
            manifest_sha256=dataset.manifest_sha256,
            manifest_json=dict(dataset.manifest_json),
        )

    def _schema_snapshot(
        self,
        *,
        project_id: str,
        candidate: PoseActiveLearningCandidate,
    ) -> dict[str, Any]:
        schema = self.session.get(
            PoseLandmarkSchema,
            candidate.pose_schema_id,
        )
        if schema is None:
            raise ConflictError("Verified pose references a missing landmark schema")
        if schema.project_id != project_id:
            raise ConflictError("Verified pose schema belongs to another project")

        revision = self.session.scalar(
            select(PoseLandmarkSchemaRevision).where(
                PoseLandmarkSchemaRevision.schema_id == candidate.pose_schema_id,
                PoseLandmarkSchemaRevision.revision == candidate.pose_schema_revision,
            )
        )
        if revision is None:
            raise ConflictError("Verified pose schema revision no longer exists")

        # A damaged persisted schema must not be silently converted from a
        # mapping into a list of keys when freezing verified training truth.
        if not isinstance(revision.groups_json, list) or not isinstance(
            revision.expanded_labels_json, list
        ):
            raise ConflictError("Verified pose schema revision has malformed label collections")

        return {
            "schema_version": revision.schema_version,
            "schema_id": revision.schema_id,
            "schema_revision": revision.revision,
            "name": schema.name,
            "groups": list(revision.groups_json),
            "expanded_labels": list(revision.expanded_labels_json),
            "keypoint_count": revision.keypoint_count,
            "allows_repeated_labels": (revision.allows_repeated_labels),
            "content_hash": revision.content_hash,
        }

    def _model_snapshots(
        self,
        *,
        project_id: str,
        model_ids: list[str],
    ) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []

        for model_id in sorted(set(model_ids)):
            model = self.session.get(
                ModelRegistration,
                model_id,
            )
            if model is None:
                raise ConflictError("A source pose model registration no longer exists")
            if model.project_id != project_id:
                raise ConflictError("A source pose model belongs to another project")
            # Model metadata is persisted JSON and may have been damaged by a
            # legacy import. Never silently coerce a list (or raise a 500)
            # while freezing immutable source-model provenance.
            if not isinstance(model.metadata_json, dict):
                raise ConflictError("Source pose model metadata must be a JSON object")

            snapshots.append(
                {
                    "model_id": model.id,
                    "display_name": model.display_name,
                    "purpose": model.purpose,
                    "framework": model.framework,
                    "task": model.task,
                    "provider_name": model.provider_name,
                    "provider_version": model.provider_version,
                    "checkpoint_sha256": model.sha256,
                    "source_filename": model.source_filename,
                    "metadata": dict(model.metadata_json or {}),
                }
            )

        return snapshots

    def _review_snapshot(
        self,
        candidate: PoseActiveLearningCandidate,
    ) -> dict[str, Any]:
        if candidate.correction_id is None:
            raise ConflictError("Verified pose candidate is missing its review correction")

        correction = self.session.get(
            PoseLandmarkCorrection,
            candidate.correction_id,
        )
        if correction is None:
            raise ConflictError("Verified pose review correction no longer exists")

        if (
            correction.action != "verify_active_learning_pose"
            or correction.target_type != "pose_active_learning_candidate"
            or correction.target_id != candidate.id
        ):
            raise ConflictError("Verified pose correction does not match the candidate")
        # The review correction and candidate are independent audit records.
        # Freeze must reject mismatched attribution before creating a dataset
        # that would fail its own scientist-verification checks on first read.
        if (
            not isinstance(correction.actor, str)
            or not correction.actor.strip()
            or correction.actor != correction.actor.strip()
            or correction.actor != candidate.reviewed_by
            or not isinstance(candidate.reviewed_at, datetime)
            or not isinstance(correction.created_at, datetime)
        ):
            raise ConflictError("Verified pose scientist review attribution changed")

        # The correction is an independent scientist-review audit record.
        # Check its saved before/after evidence *before* freezing, otherwise
        # an altered correction can produce an unreadable "complete" dataset.
        before = correction.before_json
        after = correction.after_json
        if (
            not isinstance(before, dict)
            or before.get("candidate_id") != candidate.id
            or before.get("source_track_revision") != candidate.source_track_revision
            or before.get("candidate_provenance_sha256") != candidate.provenance_sha256
            or before.get("acquisition_score") != candidate.acquisition_score
            or before.get("score_components") != candidate.score_components_json
            or before.get("reason_codes") != candidate.reason_codes_json
            or not isinstance(after, dict)
            or after.get("verified_track_revision") != candidate.verified_track_revision
            or after.get("verified_pose_sha256") != candidate.verified_pose_sha256
            or after.get("pose_schema_id") != candidate.pose_schema_id
            or after.get("pose_schema_revision") != candidate.pose_schema_revision
        ):
            raise ConflictError("Verified pose scientist correction evidence changed")

        return {
            "correction_id": correction.id,
            "action": correction.action,
            "target_type": correction.target_type,
            "target_id": correction.target_id,
            "reason_code": correction.reason_code,
            "note": correction.note,
            "actor": correction.actor,
            "before": dict(correction.before_json or {}),
            "after": dict(correction.after_json or {}),
            "reviewed_by": candidate.reviewed_by,
            "reviewed_at": (
                candidate.reviewed_at.isoformat() if candidate.reviewed_at is not None else None
            ),
            "correction_created_at": (correction.created_at.isoformat()),
        }

    @staticmethod
    def _keyframe(
        track: VideoTrack,
        frame_index: int,
    ) -> dict[str, Any]:
        # Multiple entries for the same frame make the verified pose ambiguous:
        # choosing the first silently depends on JSON ordering.
        keyframes = track.keyframes_json
        if not isinstance(keyframes, list):
            raise ConflictError("Canonical pose track keyframes must be a list")
        matches = [
            item
            for item in keyframes
            if isinstance(item, dict)
            and type(item.get("frame")) is int
            and item["frame"] == frame_index
        ]
        if len(matches) != 1:
            raise ConflictError(
                "Verified pose frame must occur exactly once on the canonical track"
            )
        return dict(matches[0])

    def _item_snapshot(
        self,
        *,
        dataset_id: str,
        project_id: str,
        round_record: PoseActiveLearningRound,
        candidate: PoseActiveLearningCandidate,
    ) -> tuple[
        PoseTrainingDatasetItem,
        dict[str, Any],
    ]:
        if candidate.review_status != "verified":
            raise ValidationError(
                "Only scientist-verified pose candidates may enter training datasets"
            )
        if candidate.verified_track_revision is None or candidate.verified_pose_sha256 is None:
            raise ConflictError("Verified pose candidate is missing its verification fingerprint")

        track = self.session.get(
            VideoTrack,
            candidate.video_track_id,
        )
        if track is None or track.deleted_at is not None:
            raise ConflictError("Verified canonical pose track no longer exists")

        if track.revision != candidate.verified_track_revision:
            raise ConflictError(
                "Canonical pose track changed after scientist "
                "verification. Re-review the pose before freezing "
                "a training dataset."
            )

        video = self.session.get(
            VideoAsset,
            track.video_id,
        )
        if video is None:
            raise ConflictError("Verified pose source video no longer exists")
        if video.project_id != project_id:
            raise ConflictError("Verified pose source video belongs to another project")
        if video.id != round_record.video_id:
            raise ConflictError(
                "Verified pose source video does not match the Active Learning round"
            )

        # Persisted acquisition provenance must be an object. Coercing a
        # malformed JSON list can either raise an uncontrolled exception or
        # silently reinterpret key/value pairs as verified source evidence.
        if not isinstance(candidate.provenance_json, dict):
            raise ConflictError("Pose acquisition provenance must be a JSON object")
        provenance = dict(candidate.provenance_json)
        # A verified pose must not freeze with acquisition metadata changed
        # after selection while its original candidate fingerprint remains.
        if canonical_json_sha256(provenance) != candidate.provenance_sha256:
            raise ConflictError("Pose acquisition provenance changed after selection")
        # The candidate fingerprint can be re-signed after a metadata edit.
        # Validate acquisition identities before freezing, rather than
        # persisting a dataset that fails its own manifest on first read.
        if (
            provenance.get("schema_version") != "pose-active-learning-provenance-0001"
            or provenance.get("project_id") != project_id
            or provenance.get("video_id") != video.id
            or provenance.get("video_track_id") != track.id
            or type(provenance.get("focus_frame")) is not int
            or provenance["focus_frame"] != candidate.focus_frame
            or provenance.get("pose_schema_id") != candidate.pose_schema_id
            or provenance.get("pose_schema_revision") != candidate.pose_schema_revision
        ):
            raise ConflictError("Pose acquisition provenance does not match verified source")
        source_video_sha = provenance.get("video_sha256")
        # Missing or empty source checksums are not valid frozen evidence.
        # Reject them before persisting a dataset that later fails its own
        # manifest lineage validation on the first read.
        if (
            not isinstance(source_video_sha, str)
            or not source_video_sha.strip()
            or source_video_sha != video.sha256
        ):
            raise ConflictError("Source video checksum changed after acquisition")

        keyframe = self._keyframe(
            track,
            candidate.focus_frame,
        )

        # Malformed persisted landmark collections must fail as a controlled
        # scientific conflict, not coerce dictionary keys or raise TypeError.
        raw_observations = keyframe.get("pose_observations")
        raw_keypoints = keyframe.get("keypoints")
        if (raw_observations is not None and not isinstance(raw_observations, list)) or (
            raw_keypoints is not None and not isinstance(raw_keypoints, list)
        ):
            raise ConflictError("Verified canonical pose landmarks must be lists")
        pose_observations = list(raw_observations or [])
        keypoints = list(raw_keypoints or [])

        if not pose_observations and not keypoints:
            raise ConflictError("Verified canonical pose contains no landmarks")

        verified_payload = {
            "schema_version": ("pose-active-learning-verified-pose-0001"),
            "video_track_id": track.id,
            "track_revision": track.revision,
            "focus_frame": candidate.focus_frame,
            "pose_schema_id": candidate.pose_schema_id,
            "pose_schema_revision": (candidate.pose_schema_revision),
            "pose_observations": pose_observations,
            "keypoints": keypoints,
        }

        recomputed_verified_sha = canonical_json_sha256(verified_payload)

        if recomputed_verified_sha != candidate.verified_pose_sha256:
            raise ConflictError(
                "Canonical pose no longer matches the scientist-verified pose fingerprint"
            )

        schema = self._schema_snapshot(
            project_id=project_id,
            candidate=candidate,
        )
        source_model_ids = candidate.source_model_ids_json
        if source_model_ids is None:
            source_model_ids = []
        if not isinstance(source_model_ids, list) or any(
            not isinstance(model_id, str) or not model_id.strip() for model_id in source_model_ids
        ):
            raise ConflictError("Verified pose source model IDs must be a list of nonempty strings")
        source_models = self._model_snapshots(
            project_id=project_id,
            model_ids=source_model_ids,
        )
        source_job_ids = candidate.source_job_ids_json
        if source_job_ids is None:
            source_job_ids = []
        if not isinstance(source_job_ids, list) or any(
            not isinstance(job_id, str) or not job_id.strip() for job_id in source_job_ids
        ):
            raise ConflictError("Verified pose source job IDs must be a list of nonempty strings")
        review = self._review_snapshot(candidate)

        raw_bbox = keyframe.get("bbox")
        if raw_bbox is not None and not isinstance(raw_bbox, list):
            raise ConflictError("Verified canonical pose bbox must be a list")

        canonical_pose = {
            "schema_version": ("reefvision-canonical-pose-frame-0001"),
            "frame_index": candidate.focus_frame,
            "bbox": list(raw_bbox or []),
            "confidence": keyframe.get("confidence"),
            "pose_observations": pose_observations,
            "keypoints": keypoints,
        }

        item_payload = {
            "schema_version": ITEM_SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "candidate_id": candidate.id,
            "project_id": project_id,
            "source_round_id": round_record.id,
            "video": {
                "video_id": video.id,
                "sha256": video.sha256,
                "revision": video.revision,
                "original_filename": (video.original_filename),
                "width_px": video.width_px,
                "height_px": video.height_px,
                "frame_count": video.frame_count,
                "fps": video.fps,
            },
            "video_track_id": track.id,
            "label_class_id": track.label_class_id,
            "verified_track_revision": track.revision,
            "pose_schema": schema,
            "verified_pose_sha256": (candidate.verified_pose_sha256),
            "canonical_pose": canonical_pose,
            "source_models": source_models,
            "source_job_ids": list(source_job_ids),
            "acquisition_provenance": provenance,
            "candidate_provenance_sha256": (candidate.provenance_sha256),
            "review_provenance": review,
        }

        item_sha256 = canonical_json_sha256(item_payload)

        item_id = str(uuid4())

        item = PoseTrainingDatasetItem(
            id=item_id,
            dataset_id=dataset_id,
            candidate_id=candidate.id,
            video_id=video.id,
            video_sha256=video.sha256,
            video_revision=video.revision,
            video_track_id=track.id,
            label_class_id=track.label_class_id,
            frame_index=candidate.focus_frame,
            verified_track_revision=track.revision,
            pose_schema_id=candidate.pose_schema_id,
            pose_schema_revision=(candidate.pose_schema_revision),
            pose_schema_content_hash=str(schema["content_hash"]),
            verified_pose_sha256=(candidate.verified_pose_sha256),
            canonical_pose_json=canonical_pose,
            source_models_json=source_models,
            source_job_ids_json=list(source_job_ids),
            acquisition_provenance_json=provenance,
            review_provenance_json=review,
            item_sha256=item_sha256,
        )

        summary = {
            "item_id": item_id,
            "item_sha256": item_sha256,
            "candidate_id": candidate.id,
            "video_id": video.id,
            "video_sha256": video.sha256,
            "video_track_id": track.id,
            "frame_index": candidate.focus_frame,
            "verified_track_revision": track.revision,
            "verified_pose_sha256": (candidate.verified_pose_sha256),
            "canonical_pose_sha256": canonical_json_sha256(canonical_pose),
            "frozen_evidence_sha256": frozen_pose_item_evidence_sha256(item),
            "pose_schema_id": candidate.pose_schema_id,
            "pose_schema_revision": (candidate.pose_schema_revision),
            "pose_schema_content_hash": (schema["content_hash"]),
            "candidate_provenance_sha256": (candidate.provenance_sha256),
            "correction_id": candidate.correction_id,
        }

        return item, summary

    def create_from_round(
        self,
        round_id: str,
        request: PoseTrainingDatasetCreateRequest,
    ) -> PoseTrainingDatasetResponse:
        existing = self.session.scalar(
            select(PoseTrainingDataset).where(PoseTrainingDataset.source_round_id == round_id)
        )
        if existing is not None:
            # An idempotent freeze must not return corrupted persisted training truth.
            self.manifest(existing.id)
            return PoseTrainingDatasetResponse.model_validate(existing)

        round_record = self._round(round_id)

        retraining_manifest = PoseActiveLearningService(self.session).export_manifest(round_id)

        if not retraining_manifest.retraining_ready:
            raise ValidationError(
                "Pose Active Learning round is not "
                "retraining-ready. Finish or skip every "
                "candidate and verify at least one pose."
            )

        if round_record.status != "complete":
            raise ValidationError(
                "Pose Active Learning round must be complete "
                "before a training dataset can be frozen"
            )

        verified = list(
            self.session.scalars(
                select(PoseActiveLearningCandidate)
                .where(
                    PoseActiveLearningCandidate.round_id == round_id,
                    PoseActiveLearningCandidate.review_status == "verified",
                )
                .order_by(
                    PoseActiveLearningCandidate.video_track_id,
                    PoseActiveLearningCandidate.focus_frame,
                    PoseActiveLearningCandidate.id,
                )
            )
        )

        if not verified:
            raise ValidationError("Training dataset requires at least one scientist-verified pose")

        dataset_id = str(uuid4())

        item_rows: list[PoseTrainingDatasetItem] = []
        item_summaries: list[dict[str, Any]] = []

        for candidate in verified:
            item, summary = self._item_snapshot(
                dataset_id=dataset_id,
                project_id=round_record.project_id,
                round_record=round_record,
                candidate=candidate,
            )
            item_rows.append(item)
            item_summaries.append(summary)

        # The freeze API must independently verify the selection that led to
        # scientist review. Workflow Builder review gates are not the only
        # entry point to creating immutable training data.
        selection_manifest = round_record.selection_manifest_json
        if (
            not isinstance(selection_manifest, dict)
            or selection_manifest.get("schema_version") != "pose-active-learning-selection-0001"
        ):
            raise ConflictError("Pose Active Learning selection manifest is invalid")
        selection_identity = {
            **selection_manifest,
            "schema_version": "pose-active-learning-selection-identity-0001",
        }
        if canonical_json_sha256(selection_identity) != round_record.selection_sha256:
            raise ConflictError("Pose Active Learning selection manifest checksum changed")

        selected_items = selection_manifest.get("items")
        candidates = list(
            self.session.scalars(
                select(PoseActiveLearningCandidate).where(
                    PoseActiveLearningCandidate.round_id == round_id
                )
            )
        )
        if (
            not isinstance(selected_items, list)
            or len(selected_items) != round_record.selected_count
            or len(candidates) != round_record.selected_count
            or any(not isinstance(item, dict) for item in selected_items)
        ):
            raise ConflictError("Pose Active Learning selected candidate count changed")
        selected_fields = (
            "video_track_id",
            "focus_frame",
            "frame_start",
            "frame_end",
            "acquisition_score",
            "score_components",
            "reason_codes",
            "pose_schema_id",
            "pose_schema_revision",
            "source_track_revision",
            "provenance_sha256",
        )
        selected_digests = sorted(
            canonical_json_sha256({field: item.get(field) for field in selected_fields})
            for item in selected_items
        )
        candidate_digests = sorted(
            canonical_json_sha256(
                {
                    "video_track_id": candidate.video_track_id,
                    "focus_frame": candidate.focus_frame,
                    "frame_start": candidate.frame_start,
                    "frame_end": candidate.frame_end,
                    "acquisition_score": candidate.acquisition_score,
                    "score_components": candidate.score_components_json,
                    "reason_codes": candidate.reason_codes_json,
                    "pose_schema_id": candidate.pose_schema_id,
                    "pose_schema_revision": candidate.pose_schema_revision,
                    "source_track_revision": candidate.source_track_revision,
                    "provenance_sha256": candidate.provenance_sha256,
                }
            )
            for candidate in candidates
        )
        if selected_digests != candidate_digests:
            raise ConflictError("Pose Active Learning selected candidate identities changed")

        schema_identities = {
            (
                item.pose_schema_id,
                item.pose_schema_revision,
                item.pose_schema_content_hash,
            )
            for item in item_rows
        }

        if len(schema_identities) != 1:
            raise ValidationError(
                "One immutable pose-training dataset "
                "must use exactly one pose schema revision. "
                "Create separate datasets for different schemas."
            )

        (
            pose_schema_id,
            pose_schema_revision,
            pose_schema_content_hash,
        ) = next(iter(schema_identities))

        source_retraining_manifest = retraining_manifest.model_dump(mode="json")
        source_retraining_manifest_sha256 = canonical_json_sha256(source_retraining_manifest)

        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "dataset_id": dataset_id,
            "project_id": round_record.project_id,
            "source_round_id": round_record.id,
            "source_selection_sha256": (round_record.selection_sha256),
            "source_retraining_manifest_sha256": (source_retraining_manifest_sha256),
            "pose_schema": {
                "schema_id": pose_schema_id,
                "schema_revision": (pose_schema_revision),
                "content_hash": (pose_schema_content_hash),
            },
            "truth_policy": ("scientist_verified_only"),
            "skipped_candidates_included": False,
            "pending_candidates_included": False,
            "item_count": len(item_rows),
            "items": item_summaries,
        }

        manifest_sha256 = canonical_json_sha256(manifest)

        dataset = PoseTrainingDataset(
            id=dataset_id,
            project_id=round_record.project_id,
            source_round_id=round_record.id,
            name=(
                request.name.strip()
                if request.name is not None
                else f"{round_record.name} training dataset"
            ),
            status="complete",
            schema_version=DATASET_SCHEMA_VERSION,
            pose_schema_id=pose_schema_id,
            pose_schema_revision=pose_schema_revision,
            pose_schema_content_hash=(pose_schema_content_hash),
            source_selection_sha256=(round_record.selection_sha256),
            source_retraining_manifest_sha256=(source_retraining_manifest_sha256),
            manifest_json=manifest,
            manifest_sha256=manifest_sha256,
            item_count=len(item_rows),
            created_by=request.created_by,
        )

        self.session.add(dataset)

        for item in item_rows:
            self.session.add(item)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(dataset)

        return PoseTrainingDatasetResponse.model_validate(dataset)

    @staticmethod
    def _zip_member(
        archive: zipfile.ZipFile,
        name: str,
        content: bytes,
    ) -> None:
        info = zipfile.ZipInfo(
            filename=name,
            date_time=(1980, 1, 1, 0, 0, 0),
        )
        info.compress_type = zipfile.ZIP_DEFLATED
        # ZipInfo defaults to a host-specific OS marker. Pin it so the same
        # frozen scientific package has identical bytes on Windows and Linux.
        info.create_system = 3
        archive.writestr(info, content)

    def native_package(
        self,
        dataset_id: str,
    ) -> tuple[str, bytes, str]:
        dataset = self._dataset(dataset_id)
        items = list(
            self.session.scalars(
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
            raise ConflictError(
                "Pose training dataset item count does not match its immutable manifest"
            )
        # Reuse the retrieval contract so native exports cannot diverge from
        # the frozen manifest, verification policy, or item lineage checks.
        self.manifest(dataset_id)

        manifest_bytes = (
            json.dumps(
                dataset.manifest_json,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")

        rows: list[str] = []

        for item in items:
            payload = {
                "schema_version": ITEM_SCHEMA_VERSION,
                "item_id": item.id,
                "item_sha256": item.item_sha256,
                "candidate_id": item.candidate_id,
                "video_id": item.video_id,
                "video_sha256": item.video_sha256,
                "video_revision": item.video_revision,
                "video_track_id": item.video_track_id,
                "label_class_id": item.label_class_id,
                "frame_index": item.frame_index,
                "verified_track_revision": (item.verified_track_revision),
                "pose_schema_id": item.pose_schema_id,
                "pose_schema_revision": (item.pose_schema_revision),
                "pose_schema_content_hash": (item.pose_schema_content_hash),
                "verified_pose_sha256": (item.verified_pose_sha256),
                "canonical_pose": (item.canonical_pose_json),
                "source_models": (item.source_models_json),
                "source_job_ids": (item.source_job_ids_json),
                "acquisition_provenance": (item.acquisition_provenance_json),
                "review_provenance": (item.review_provenance_json),
            }

            rows.append(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )

        item_bytes = ("\n".join(rows) + "\n").encode("utf-8")

        readme = (
            b"ReefVision immutable pose-training dataset\n"
            b"\n"
            b"This package contains only scientist-verified "
            b"canonical pose snapshots.\n"
            b"Skipped, pending, and unreviewed model "
            b"predictions are excluded.\n"
            b"External trainer-specific image extraction and "
            b"SLEAP/COCO/DLC/Ultralytics/NWB rendering are "
            b"performed in the next Phase 9 interoperability "
            b"layer.\n"
            b"\n"
            b"Verify extracted files before scientific reuse:\n"
            b"  Linux: sha256sum -c SHA256SUMS\n"
            b"  macOS: shasum -a 256 -c SHA256SUMS\n"
            b"  Windows: compare Get-FileHash -Algorithm SHA256 results\n"
            b"           with the SHA256SUMS entries for each file.\n"
            b"Run these checks from the extracted package directory.\n"
        )

        # A portable checksum index lets researchers validate extracted files
        # independently of ZIP metadata or the original download response.
        checksum_bytes = "".join(
            f"{hashlib.sha256(payload).hexdigest()}  {name}\n"
            for name, payload in (
                (PACKAGE_MANIFEST_FILENAME, manifest_bytes),
                (PACKAGE_ITEMS_FILENAME, item_bytes),
                ("README.txt", readme),
            )
        ).encode("ascii")

        stream = io.BytesIO()

        with zipfile.ZipFile(
            stream,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            self._zip_member(
                archive,
                PACKAGE_MANIFEST_FILENAME,
                manifest_bytes,
            )
            self._zip_member(
                archive,
                PACKAGE_ITEMS_FILENAME,
                item_bytes,
            )
            self._zip_member(
                archive,
                "README.txt",
                readme,
            )
            self._zip_member(
                archive,
                PACKAGE_CHECKSUMS_FILENAME,
                checksum_bytes,
            )

        content = stream.getvalue()
        package_sha256 = hashlib.sha256(content).hexdigest()

        filename = f"pose-training-{dataset.id}.reefvision-pose.zip"

        return filename, content, package_sha256

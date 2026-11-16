"""Validate and rebind frozen temporal ReefPose evidence during project exchange."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseIdentityAssociationRun,
    PoseIdentityObservation,
    TemporalReefPoseRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.temporal_reefpose import TemporalFrameRead, TemporalPointRead
from reefvision.schemas.videos import VideoTrackKeyframe
from reefvision.services.temporal_reefpose import (
    TEMPORAL_DATASET_FORMAT,
    TEMPORAL_JOB,
    TEMPORAL_PROVIDER,
)
from reefvision.services.temporal_reefpose_sources import (
    TEMPORAL_METHOD,
    _identity_target,
    _point_mapping,
)
from reefvision.storage.datasets import canonical_json_sha256

TEMPORAL_DATASETS = "temporal_reefpose_datasets"
TEMPORAL_RUNS = "temporal_reefpose_runs"
TEMPORAL_FRAMES = "temporal_reefpose_frames"


def validate_temporal_exchange(sections: dict[str, list[dict[str, Any]]]) -> None:
    maps = {
        name: {row["id"]: row for row in sections.get(name, [])}
        for name in (
            TEMPORAL_DATASETS,
            TEMPORAL_RUNS,
            "jobs",
            "videos",
            "video_tracks",
            "models",
            "pose_identity_association_runs",
            "pose_identity_observations",
        )
    }
    parts: dict[str, str] = {}
    inference_counts: dict[str, int] = {}
    inference_inputs: dict[str, dict[int, dict[str, Any]]] = {}

    def verify_source(source: dict[str, Any]) -> None:
        recording = source["recording"]
        schema = source["schema"]
        landmark_ids = [item["id"] for item in schema["landmarks"]]
        absent = {
            identifier: TemporalPointRead(
                landmark_id=identifier, x=None, y=None, visibility="absent"
            ).model_dump(mode="json")
            for identifier in landmark_ids
        }
        video = maps["videos"].get(recording["id"])
        if video is not None and video["sha256"] != recording["sha256"]:
            raise ValidationError("Temporal archive recording checksum is inconsistent")
        for track in (source["frame_track"], source.get("reviewed_track")):
            if track is not None:
                current = maps["video_tracks"].get(track["id"])
                if current is not None and current["video_id"] != recording["id"]:
                    raise ValidationError("Temporal archive track belongs to another recording")
        if (
            source.get("reviewed_track")
            and source["reviewed_track"].get("confirmed_same_animal") is not True
        ):
            raise ValidationError("Temporal archive reviewed track pairing lacks confirmation")
        model = maps["models"].get(source["frame_model"]["id"])
        if model is not None and (
            model["task"] != "pose"
            or model["provider_name"] != "reefpose"
            or model["sha256"] != source["frame_model"]["checkpoint_sha256"]
        ):
            raise ValidationError("Temporal archive frame checkpoint has inconsistent provenance")
        prediction = source["frame_track"]
        job = maps["jobs"].get(prediction["job_id"])
        if job is not None:
            result = job.get("result_json") or {}
            if (
                job["job_type"] != "video_tracking"
                or job["status"] != "succeeded"
                or job["request_json"].get("video_id") != recording["id"]
                or job["request_json"].get("model_id") != source["frame_model"]["id"]
                or (result.get("pose_track_hashes") or {}).get(prediction["id"])
                != prediction["keyframes_sha256"]
                or (result.get("pose_input_hashes") or {}).get("model_sha256")
                != source["frame_model"]["checkpoint_sha256"]
                or (result.get("pose_input_hashes") or {}).get("video_sha256")
                != recording["sha256"]
                or result.get("pose_inference_protocol") != source["frame_model"]["configuration"]
            ):
                raise ValidationError(
                    "Temporal archive frame inference disagrees with its saved job"
                )
        if (
            canonical_json_sha256(source["frame_model"]["configuration"])
            != source["frame_model"]["configuration_sha256"]
        ):
            raise ValidationError(
                "Temporal archive frame inference configuration checksum does not match"
            )
        indices = [frame["frame_index"] for frame in source["frames"]]
        if not indices or indices != sorted(set(indices)):
            raise ValidationError("Temporal archive source frames are invalid")
        identity = source.get("identity")
        identity_rows: dict[int, dict[str, Any]] = {}
        if identity:
            for item in identity["observations"]:
                pinned = maps["pose_identity_observations"].get(item["id"])
                if pinned is None or pinned["revision"] != item["revision"]:
                    raise ValidationError(
                        "Temporal archive is missing a frozen identity observation"
                    )
                if pinned["source_video_track_id"] == prediction["id"]:
                    identity_rows[pinned["frame_index"]] = pinned
        raw_frames = _current_keyframes(prediction, maps["video_tracks"])
        reviewed = _current_keyframes(source.get("reviewed_track"), maps["video_tracks"])
        if raw_frames is not None and not identity and not set(raw_frames) <= set(indices):
            raise ValidationError("Temporal archive is missing frozen frame observations")
        for frame in source["frames"]:
            index = frame["frame_index"]
            if raw_frames is not None:
                raw = raw_frames.get(index)
                if (raw is None) != (frame["frame_points"] is None):
                    raise ValidationError(
                        "Temporal archive frame missingness differs from inference"
                    )
                if raw is not None:
                    expected = _point_mapping(raw, schema, human=False)
                    if [expected.get(key, absent[key]) for key in landmark_ids] != frame[
                        "frame_points"
                    ]:
                        raise ValidationError("Temporal archive frame points differ from inference")
            # Historical annotations are preserved as frozen snapshots. A matching
            # live revision or immutable identity observation can be checked directly.
            if source.get("reviewed_track") is None or reviewed is not None:
                human = reviewed.get(index) if reviewed is not None else None
                expected = _point_mapping(human, schema, human=True) if human else {}
                if not expected and index in identity_rows:
                    expected = _identity_target(
                        PoseIdentityObservation(**identity_rows[index]), landmark_ids
                    )
                targets = (
                    [expected.get(identifier) for identifier in landmark_ids] if expected else None
                )
                if targets != frame["target_points"]:
                    raise ValidationError("Temporal archive targets differ from reviewed landmarks")

    for dataset in maps[TEMPORAL_DATASETS].values():
        manifest = dataset["manifest_json"]
        if (
            manifest["format"] != TEMPORAL_DATASET_FORMAT
            or canonical_json_sha256(manifest) != dataset["manifest_sha256"]
            or not manifest["sources"]
        ):
            raise ValidationError("Temporal archive dataset integrity check failed")
        for source in manifest["sources"]:
            verify_source(source)
            if (
                source["schema"] != manifest["schema"]
                or source["frame_model"]["checkpoint_sha256"]
                != manifest["frame_model"]["checkpoint_sha256"]
            ):
                raise ValidationError(
                    "Temporal archive dataset contains incompatible source evidence"
                )
            for key in source["groups"]:
                if parts.setdefault(key, source["split"]) != source["split"]:
                    raise ValidationError("Temporal archive recording groups cross dataset splits")
    for row in maps[TEMPORAL_RUNS].values():
        manifest = row["input_manifest_json"]
        if (
            canonical_json_sha256(manifest) != row["input_manifest_sha256"]
            or manifest["configuration"] != row["configuration_json"]
        ):
            raise ValidationError("Temporal archive run input checksum does not match")
        linked_dataset = maps[TEMPORAL_DATASETS].get(row["dataset_id"])
        if row["dataset_id"] and (
            linked_dataset is None
            or manifest["dataset_id"] != linked_dataset["id"]
            or manifest["dataset_sha256"] != linked_dataset["manifest_sha256"]
        ):
            raise ValidationError("Temporal archive run dataset is inconsistent")
        job = maps["jobs"].get(row["job_id"])
        if job is not None and (
            job["job_type"] != TEMPORAL_JOB
            or job["request_json"].get("temporal_run_id") != row["id"]
            or job["request_json"].get("input_manifest_sha256") != row["input_manifest_sha256"]
        ):
            raise ValidationError("Temporal archive job refers to a different run")
        if row["kind"] == "inference":
            verify_source(manifest["source"])
            inference_inputs[row["id"]] = {
                item["frame_index"]: item for item in manifest["source"]["frames"]
            }
            if row["result_json"] is not None:
                inference_counts[row["id"]] = row["result_json"]["frame_count"]
            if row["review_revision"] > 0:
                reviewed = maps["pose_identity_association_runs"].get(row["identity_run_id"])
                if (
                    reviewed is None
                    or reviewed["algorithm"] != TEMPORAL_METHOD
                    or reviewed["revision"] < row["review_revision"]
                    or reviewed["input_manifest_sha256"] != row["input_manifest_sha256"]
                ):
                    raise ValidationError("Temporal archive review lineage is invalid")
    counts: dict[str, set[int]] = {}
    for frame in sections.get(TEMPORAL_FRAMES, []):
        evidence = frame["evidence_json"]
        indices = counts.setdefault(frame["run_id"], set())
        source_frame = inference_inputs.get(frame["run_id"], {}).get(frame["frame_index"])
        if (
            source_frame is None
            or frame["frame_index"] != evidence["frame_index"]
            or frame["frame_index"] in indices
            or canonical_json_sha256(evidence) != frame["evidence_sha256"]
        ):
            raise ValidationError("Temporal archive prediction evidence is inconsistent")
        if any(
            source_frame[field] != evidence[field]
            for field in (
                "timestamp_seconds",
                "timestamp_source",
                "frame_points",
                "bbox",
                "discontinuity",
            )
        ):
            raise ValidationError("Temporal archive result disagrees with frozen frame inputs")
        TemporalFrameRead.model_validate({**evidence, "review_source": frame["review_source"]})
        indices.add(frame["frame_index"])
    if any(
        len(counts.get(identifier, set())) != count
        for identifier, count in inference_counts.items()
    ):
        raise ValidationError("Temporal archive does not contain all completed inference frames")


def _current_keyframes(
    track: dict[str, Any] | None, inventory: dict[str, dict[str, Any]]
) -> dict[int, VideoTrackKeyframe] | None:
    current = inventory.get(track["id"]) if track is not None else None
    if track is None or current is None or current["revision"] != track["revision"]:
        return None
    if canonical_json_sha256(current["keyframes_json"]) != track["keyframes_sha256"]:
        raise ValidationError("Temporal archive track does not match its frozen keyframe checksum")
    frames = (VideoTrackKeyframe.model_validate(raw) for raw in current["keyframes_json"])
    return {frame.frame: frame for frame in frames}


def _bind_ids(value: dict[str, Any], keys: tuple[str, ...], mapping: dict[str, str]) -> None:
    for key in keys:
        if key in value and value[key] in mapping:
            value[key] = mapping[value[key]]


def _source(
    value: dict[str, Any], mapping: dict[str, str], track_digests: dict[str, tuple[str, str]]
) -> None:
    _bind_ids(value["recording"], ("id",), mapping)
    _bind_ids(value["schema"], ("schema_id",), mapping)
    _bind_ids(value["frame_model"], ("id",), mapping)
    _bind_ids(value, ("animal_id",), mapping)
    for track in (value["frame_track"], value.get("reviewed_track")):
        if track is not None:
            if (pair := track_digests.get(track["id"])) and pair[0] == track["keyframes_sha256"]:
                track["keyframes_sha256"] = pair[1]
            _bind_ids(track, ("id", "job_id"), mapping)
    if identity := value.get("identity"):
        _bind_ids(identity, ("run_id", "animal_id"), mapping)
        for observation in identity["observations"]:
            _bind_ids(observation, ("id",), mapping)


def remap_temporal_exchange_row(
    section: str,
    row: dict[str, Any],
    values: dict[str, Any],
    mapping: dict[str, str],
    digests: dict[str, str],
    track_digests: dict[str, tuple[str, str]],
) -> None:
    if section == TEMPORAL_DATASETS:
        manifest = deepcopy(row["manifest_json"])
        for source in manifest["sources"]:
            _source(source, mapping, track_digests)
        _bind_ids(manifest["schema"], ("schema_id",), mapping)
        _bind_ids(manifest["frame_model"], ("id",), mapping)
        for ancestor in manifest["frame_lineage"]["datasets"]:
            _bind_ids(ancestor, ("id",), mapping)
            _bind_ids(ancestor, ("sha256",), digests)
        values["manifest_json"] = manifest
        digests[row["manifest_sha256"]] = values["manifest_sha256"] = canonical_json_sha256(
            manifest
        )
    elif section == TEMPORAL_RUNS:
        manifest = deepcopy(row["input_manifest_json"])
        if source := manifest.get("source"):
            _source(source, mapping, track_digests)
        _bind_ids(manifest, ("dataset_id",), mapping)
        _bind_ids(manifest, ("dataset_sha256",), digests)
        manifest["configuration"] = values["configuration_json"]
        values["input_manifest_json"] = manifest
        digests[row["input_manifest_sha256"]] = values["input_manifest_sha256"] = (
            canonical_json_sha256(manifest)
        )
    elif section == TEMPORAL_FRAMES:
        # Source-pixel evidence has no exchange-local identifiers.
        values["evidence_json"] = deepcopy(row["evidence_json"])


def restore_temporal_links(session: Session, project_id: str, digests: dict[str, str]) -> None:
    for run in session.scalars(
        select(TemporalReefPoseRun).where(TemporalReefPoseRun.project_id == project_id)
    ):
        if run.job_id:
            job = session.get(Job, run.job_id)
            if job is not None:
                job.request_json = {
                    **job.request_json,
                    "input_manifest_sha256": run.input_manifest_sha256,
                }
        if run.identity_run_id:
            reviewed = session.get(PoseIdentityAssociationRun, run.identity_run_id)
            if reviewed is not None:
                reviewed.input_manifest_sha256 = run.input_manifest_sha256
    for model in session.scalars(
        select(ModelRegistration).where(
            ModelRegistration.project_id == project_id,
            ModelRegistration.provider_name == TEMPORAL_PROVIDER,
        )
    ):
        metadata = {**model.metadata_json}
        source_hash = metadata.get("source_temporal_dataset_sha256")
        if source_hash in digests:
            metadata["source_temporal_dataset_sha256"] = digests[source_hash]
        model.metadata_json = metadata

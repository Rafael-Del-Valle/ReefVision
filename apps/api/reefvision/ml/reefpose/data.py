"""Frozen ReefVision pose export conversion and ReefPose datasets."""

from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

import numpy as np
import torch
from PIL import Image, UnidentifiedImageError
from torch.utils.data import Dataset

from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.geometry import letterbox_tensor
from reefvision.ml.reefpose.schema import AnatomySchema
from reefvision.ml.reefpose.targets import generate_gaussian_heatmaps

EXPORT_MANIFEST_FILENAME = "reefvision-pose-training-export-manifest.json"
EXPORT_SCHEMA_VERSION = "pose-training-external-export-0001"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReefPoseValidationError(f"ReefVision export {label} must be an object")
    return cast(dict[str, Any], value)


def _required_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReefPoseValidationError(f"ReefVision export {label} must be an array")
    return value


@dataclass(frozen=True, slots=True)
class PoseRecord:
    sample_id: str
    image_path: Path
    group_id: str
    source_width: int
    source_height: int
    keypoints: tuple[tuple[float, float], ...]
    visibility: tuple[int, ...]
    visibility_states: tuple[str, ...]
    crop_box: tuple[float, float, float, float] | None = None
    class_label: str = "animal"

    def __post_init__(self) -> None:
        if not self.sample_id.strip() or not self.group_id.strip():
            raise ReefPoseValidationError("Pose record sample and group IDs cannot be blank")
        if self.source_width < 1 or self.source_height < 1:
            raise ReefPoseValidationError("Pose record source dimensions must be positive")
        if not self.keypoints or not (
            len(self.keypoints) == len(self.visibility) == len(self.visibility_states)
        ):
            raise ReefPoseValidationError("Pose record landmark arrays must be non-empty and equal")
        if any(state not in {0, 1, 2} for state in self.visibility):
            raise ReefPoseValidationError("Pose record visibility must use 0, 1, or 2")
        for (x, y), visibility in zip(self.keypoints, self.visibility, strict=True):
            if not math.isfinite(x) or not math.isfinite(y):
                raise ReefPoseValidationError("Pose record coordinates must be finite")
            if visibility > 0 and not (
                0 <= x <= self.source_width and 0 <= y <= self.source_height
            ):
                raise ReefPoseValidationError("Visible pose record coordinate is outside the source")
        if self.crop_box is not None:
            x_min, y_min, x_max, y_max = self.crop_box
            if (
                x_min < 0
                or y_min < 0
                or x_max > self.source_width
                or y_max > self.source_height
                or x_max <= x_min
                or y_max <= y_min
            ):
                raise ReefPoseValidationError("Pose record crop box is outside the source")


@dataclass(frozen=True, slots=True)
class PoseExportBundle:
    extraction_root: Path
    schema: AnatomySchema
    records: tuple[PoseRecord, ...]
    dataset_manifest_sha256: str
    source_schema_content_hash: str


def _validate_archive(archive: zipfile.ZipFile, max_uncompressed_bytes: int) -> None:
    names: set[str] = set()
    total_size = 0
    for info in archive.infolist():
        normalized = info.filename.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or not normalized:
            raise ReefPoseValidationError("ReefVision pose export contains an unsafe path")
        if normalized in names:
            raise ReefPoseValidationError("ReefVision pose export contains duplicate paths")
        names.add(normalized)
        unix_mode = info.external_attr >> 16
        if stat.S_ISLNK(unix_mode):
            raise ReefPoseValidationError("ReefVision pose export contains an unsafe symlink")
        total_size += info.file_size
        if total_size > max_uncompressed_bytes:
            raise ReefPoseValidationError("ReefVision pose export is too large to extract safely")
    if EXPORT_MANIFEST_FILENAME not in names:
        raise ReefPoseValidationError("ReefVision pose export manifest is missing")


def _extract_archive(
    archive_path: Path,
    destination: Path,
    *,
    max_uncompressed_bytes: int,
) -> None:
    if destination.exists():
        raise ReefPoseValidationError("ReefPose export destination must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _validate_archive(archive, max_uncompressed_bytes)
            for info in archive.infolist():
                normalized = info.filename.replace("\\", "/")
                output = temporary.joinpath(*PurePosixPath(normalized).parts)
                if info.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, output.open("wb") as target:
                    shutil.copyfileobj(source, target)
        temporary.replace(destination)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReefPoseValidationError("ReefVision pose export could not be extracted") from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _schema_from_manifest(payload: dict[str, Any]) -> tuple[AnatomySchema, str]:
    groups = _required_list(payload.get("groups"), "pose schema groups")
    expanded = _required_list(payload.get("expanded_labels"), "expanded landmark labels")
    keypoint_count = int(payload.get("keypoint_count", 0))
    if keypoint_count < 1 or len(expanded) != keypoint_count:
        raise ReefPoseValidationError("ReefVision pose schema landmark count is inconsistent")
    legacy_payload = {
        "schema_version": str(payload.get("schema_version", "")),
        "groups": groups,
        "expanded_labels": expanded,
        "keypoint_count": keypoint_count,
        "allows_repeated_labels": bool(payload.get("allows_repeated_labels", False)),
    }
    content_hash = str(payload.get("content_hash", ""))
    if _canonical_hash(legacy_payload) != content_hash:
        raise ReefPoseValidationError("ReefVision pose schema integrity checksum does not match")
    skeleton_raw = payload.get("skeleton", [])
    skeleton: list[tuple[str, str]] = []
    if skeleton_raw:
        for edge in _required_list(skeleton_raw, "pose skeleton"):
            if not isinstance(edge, (list, tuple)) or len(edge) != 2:
                raise ReefPoseValidationError("ReefVision pose skeleton edge is invalid")
            skeleton.append((str(edge[0]), str(edge[1])))
    schema = AnatomySchema.from_reefvision_groups(
        name=str(payload.get("name") or "ReefVision pose landmarks"),
        revision=int(payload.get("schema_revision", 0)),
        groups=[_required_mapping(item, "landmark group") for item in groups],
        schema_id=str(payload.get("schema_id", "")),
        description=(
            str(payload["description"]) if payload.get("description") is not None else None
        ),
        skeleton=skeleton,
    )
    if list(schema.expanded_names) != [str(item) for item in expanded]:
        raise ReefPoseValidationError("ReefVision expanded landmark order is inconsistent")
    return schema, content_hash


def _visibility_value(state: str) -> int:
    if state in {"absent", "out_of_frame"}:
        return 0
    if state in {"occluded", "uncertain"}:
        return 1
    if state == "visible":
        return 2
    raise ReefPoseValidationError(f"Unsupported ReefVision landmark visibility state: {state}")


def _record_from_annotation(
    annotation: dict[str, Any],
    *,
    root: Path,
    frame_paths: dict[int, Path],
    schema: AnatomySchema,
    source_width: int,
    source_height: int,
    group_id: str,
) -> PoseRecord:
    frame_index = int(annotation.get("source_frame_index", -1))
    image_path = frame_paths.get(frame_index)
    if image_path is None:
        raise ReefPoseValidationError("Pose annotation references a missing frozen frame")
    pose = _required_mapping(annotation.get("canonical_pose"), "canonical pose")
    observations = _required_list(pose.get("pose_observations"), "pose observations")
    by_slot: dict[tuple[str, int], dict[str, Any]] = {}
    for raw in observations:
        observation = _required_mapping(raw, "pose observation")
        key = (
            str(observation.get("semantic_label", "")).strip(),
            int(observation.get("occurrence_index", -1)),
        )
        if not key[0] or key[1] < 0 or key in by_slot:
            raise ReefPoseValidationError("Frozen pose observation identities are invalid")
        by_slot[key] = observation

    keypoints: list[tuple[float, float]] = []
    visibility: list[int] = []
    visibility_states: list[str] = []
    for landmark in schema.landmarks:
        observation = by_slot.pop((landmark.name, landmark.occurrence_index), None)
        if observation is None:
            keypoints.append((0.0, 0.0))
            visibility.append(0)
            visibility_states.append("absent")
            continue
        state = str(observation.get("status") or "absent").strip().casefold()
        keypoints.append((float(observation.get("x", 0.0)), float(observation.get("y", 0.0))))
        visibility.append(_visibility_value(state))
        visibility_states.append(state)
    if by_slot:
        raise ReefPoseValidationError("Frozen pose contains landmarks outside its schema")

    raw_bbox = pose.get("bbox")
    crop_box: tuple[float, float, float, float] | None = None
    if raw_bbox is not None:
        bbox = _required_list(raw_bbox, "pose bounding box")
        if len(bbox) != 4:
            raise ReefPoseValidationError("Frozen pose bounding box must contain x, y, w, h")
        x, y, width, height = (float(item) for item in bbox)
        crop_box = (x, y, x + width, y + height)
    return PoseRecord(
        sample_id=str(annotation.get("item_id", "")).strip(),
        image_path=root / image_path,
        group_id=group_id,
        source_width=source_width,
        source_height=source_height,
        keypoints=tuple(keypoints),
        visibility=tuple(visibility),
        visibility_states=tuple(visibility_states),
        crop_box=crop_box,
    )


def load_reefvision_pose_export(
    archive_path: Path,
    destination: Path,
    *,
    max_uncompressed_bytes: int = 20 * 1024 * 1024 * 1024,
) -> PoseExportBundle:
    """Validate and extract one immutable ReefVision Ultralytics-pose export."""

    if not archive_path.is_file():
        raise ReefPoseValidationError("ReefVision pose export archive does not exist")
    _extract_archive(
        archive_path,
        destination,
        max_uncompressed_bytes=max_uncompressed_bytes,
    )
    try:
        manifest = _required_mapping(
            json.loads((destination / EXPORT_MANIFEST_FILENAME).read_text(encoding="utf-8")),
            "manifest",
        )
        if manifest.get("schema_version") != EXPORT_SCHEMA_VERSION:
            raise ReefPoseValidationError("Unsupported ReefVision pose export schema version")
        if manifest.get("format") != "ultralytics_pose":
            raise ReefPoseValidationError("ReefPose requires an ultralytics_pose export")
        if manifest.get("truth_policy") != "scientist_verified_only":
            raise ReefPoseValidationError("ReefPose accepts only scientist-verified pose truth")

        dataset = _required_mapping(manifest.get("dataset"), "dataset metadata")
        dataset_hash = str(dataset.get("dataset_manifest_sha256", ""))
        if len(dataset_hash) != 64:
            raise ReefPoseValidationError("Frozen dataset manifest checksum is invalid")
        source_video = _required_mapping(manifest.get("source_video"), "source video")
        source_width = int(source_video.get("width_px", 0))
        source_height = int(source_video.get("height_px", 0))
        group_id = str(source_video.get("video_id", "")).strip()
        if min(source_width, source_height) < 1 or not group_id:
            raise ReefPoseValidationError("Frozen source-video identity is incomplete")
        schema, source_schema_hash = _schema_from_manifest(
            _required_mapping(manifest.get("pose_schema"), "pose schema")
        )

        frame_extraction = _required_mapping(manifest.get("frame_extraction"), "frame extraction")
        frame_paths: dict[int, Path] = {}
        for raw in _required_list(frame_extraction.get("frames"), "frozen frames"):
            frame = _required_mapping(raw, "frozen frame")
            frame_index = int(frame.get("source_frame_index", -1))
            relative = PurePosixPath(str(frame.get("path", "")).replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts or frame_index in frame_paths:
                raise ReefPoseValidationError("Frozen frame identity or path is invalid")
            path = destination.joinpath(*relative.parts)
            if not path.is_file() or _sha256(path) != str(frame.get("sha256", "")):
                raise ReefPoseValidationError("Frozen frame checksum does not match")
            try:
                with Image.open(path) as image:
                    if image.size != (source_width, source_height):
                        raise ReefPoseValidationError(
                            "Frozen frame dimensions do not match source metadata"
                        )
            except (OSError, UnidentifiedImageError) as exc:
                raise ReefPoseValidationError("Frozen frame is not a readable image") from exc
            frame_paths[frame_index] = Path(*relative.parts)

        annotations = _required_list(manifest.get("annotations"), "annotations")
        if len(annotations) != int(dataset.get("item_count", -1)):
            raise ReefPoseValidationError("Frozen dataset annotation count is inconsistent")
        records = tuple(
            _record_from_annotation(
                _required_mapping(raw, "annotation"),
                root=destination,
                frame_paths=frame_paths,
                schema=schema,
                source_width=source_width,
                source_height=source_height,
                group_id=group_id,
            )
            for raw in annotations
        )
        if len({record.sample_id for record in records}) != len(records):
            raise ReefPoseValidationError("Frozen pose sample IDs must be unique")
        return PoseExportBundle(
            extraction_root=destination,
            schema=schema,
            records=records,
            dataset_manifest_sha256=dataset_hash,
            source_schema_content_hash=source_schema_hash,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        if isinstance(exc, ReefPoseValidationError):
            raise
        raise ReefPoseValidationError("ReefVision pose export manifest is invalid") from exc
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


class ReefPoseDataset(Dataset[dict[str, Any]]):
    def __init__(
        self,
        records: tuple[PoseRecord, ...] | list[PoseRecord],
        schema: AnatomySchema,
        *,
        input_height: int,
        input_width: int,
        heatmap_sigma: float,
    ) -> None:
        self.records = tuple(records)
        self.schema = schema
        self.input_height = input_height
        self.input_width = input_width
        self.heatmap_sigma = heatmap_sigma
        if not self.records:
            raise ReefPoseValidationError("ReefPose dataset requires at least one record")
        if input_height % 4 or input_width % 4:
            raise ReefPoseValidationError("ReefPose dataset input dimensions must be divisible by 4")
        if heatmap_sigma <= 0:
            raise ReefPoseValidationError("ReefPose heatmap sigma must be positive")
        if any(len(record.keypoints) != schema.keypoint_count for record in self.records):
            raise ReefPoseValidationError("Pose record landmark count does not match the schema")

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> dict[str, Any]:
        record = self.records[index]
        try:
            with Image.open(record.image_path) as source:
                image = source.convert("RGB")
                if image.size != (record.source_width, record.source_height):
                    raise ReefPoseValidationError(
                        "Pose record dimensions do not match the source image"
                    )
                array = np.array(image, dtype=np.uint8, copy=True)
        except (OSError, UnidentifiedImageError) as exc:
            raise ReefPoseValidationError("Pose record image is not readable") from exc
        image_tensor = torch.from_numpy(array).permute(2, 0, 1).float().div_(255.0)
        integer_crop: tuple[int, int, int, int] | None = None
        if record.crop_box is not None:
            x_min, y_min, x_max, y_max = record.crop_box
            integer_crop = (
                max(0, math.floor(x_min)),
                max(0, math.floor(y_min)),
                min(record.source_width, math.ceil(x_max)),
                min(record.source_height, math.ceil(y_max)),
            )
        network_image, transform = letterbox_tensor(
            image_tensor,
            input_height=self.input_height,
            input_width=self.input_width,
            crop_box=integer_crop,
        )
        source_keypoints = torch.tensor(record.keypoints, dtype=torch.float32)
        heatmap_height = self.input_height // 4
        heatmap_width = self.input_width // 4
        heatmap_points = transform.source_to_heatmap(
            source_keypoints, heatmap_width, heatmap_height
        )
        states = torch.tensor(record.visibility, dtype=torch.int64)
        supervised = states > 0
        heatmap_points[supervised, 0].clamp_(0.0, heatmap_width - 1e-4)
        heatmap_points[supervised, 1].clamp_(0.0, heatmap_height - 1e-4)
        targets = generate_gaussian_heatmaps(
            heatmap_points,
            states,
            height=heatmap_height,
            width=heatmap_width,
            sigma=self.heatmap_sigma,
        )
        return {
            "sample_id": record.sample_id,
            "image": network_image,
            "heatmaps": targets.heatmaps,
            "heatmap_weights": targets.heatmap_weights,
            "visibility_targets": targets.visibility_targets,
            "source_keypoints": source_keypoints,
            "visibility_states": record.visibility_states,
        }


def group_aware_split(
    records: tuple[PoseRecord, ...] | list[PoseRecord],
    *,
    validation_fraction: float,
    seed: int,
) -> tuple[tuple[PoseRecord, ...], tuple[PoseRecord, ...]]:
    """Partition whole related groups deterministically without leakage."""

    items = tuple(records)
    if not items:
        raise ReefPoseValidationError("Cannot split an empty ReefPose dataset")
    if not 0 < validation_fraction < 1:
        raise ReefPoseValidationError("Validation fraction must be between 0 and 1")
    if len({item.sample_id for item in items}) != len(items):
        raise ReefPoseValidationError("ReefPose sample IDs must be unique before splitting")
    groups = sorted({item.group_id for item in items})
    if len(groups) < 2:
        raise ReefPoseValidationError(
            "Leakage-safe validation requires at least two groups; use a separate frozen dataset"
        )
    random.Random(seed).shuffle(groups)
    validation_group_count = max(1, min(len(groups) - 1, round(len(groups) * validation_fraction)))
    validation_groups = set(groups[:validation_group_count])
    training = tuple(item for item in items if item.group_id not in validation_groups)
    validation = tuple(item for item in items if item.group_id in validation_groups)
    if not training or not validation:
        raise ReefPoseValidationError("Leakage-safe split produced an empty partition")
    return training, validation


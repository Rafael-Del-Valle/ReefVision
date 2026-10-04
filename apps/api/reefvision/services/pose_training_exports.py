"""Loss-aware retraining exports from immutable verified pose datasets."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    LabelClass,
    PoseLandmarkSchemaRevision,
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
    VideoAsset,
)
from reefvision.domain.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from reefvision.schemas.pose_training_datasets import (
    PoseTrainingExportFormat,
)
from reefvision.services.pose_interoperability import (
    PoseInteroperabilityService,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.results_packages import sha256_file

EXPORT_MANIFEST_FILENAME = "reefvision-pose-training-export-manifest.json"
EXPORT_SCHEMA_VERSION = "pose-training-external-export-0001"


@dataclass(frozen=True)
class PoseTrainingExportArtifact:
    filename: str
    media_type: str
    content: bytes
    export_format: PoseTrainingExportFormat
    lossy: bool
    bundle_sha256: str


@dataclass(frozen=True)
class _SchemaContext:
    expanded_labels: tuple[str, ...]
    external_node_names: tuple[str, ...]
    node_mapping: tuple[dict[str, object], ...]
    metadata: dict[str, object]


class PoseTrainingExportService:
    """Render a frozen verified dataset without consulting live pose truth."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
    ) -> None:
        self.session = session
        self.settings = settings

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

        if dataset.status != "complete":
            raise ValidationError("Only complete immutable pose training datasets may be exported")

        actual_manifest_sha = canonical_json_sha256(dict(dataset.manifest_json))
        if actual_manifest_sha != dataset.manifest_sha256:
            raise ConflictError("Pose training dataset manifest checksum failed")

        return dataset

    def _items(
        self,
        dataset: PoseTrainingDataset,
    ) -> list[PoseTrainingDatasetItem]:
        items = list(
            self.session.scalars(
                select(PoseTrainingDatasetItem)
                .where(PoseTrainingDatasetItem.dataset_id == dataset.id)
                .order_by(
                    PoseTrainingDatasetItem.video_id,
                    PoseTrainingDatasetItem.frame_index,
                    PoseTrainingDatasetItem.video_track_id,
                    PoseTrainingDatasetItem.id,
                )
            )
        )

        if not items:
            raise ConflictError("Pose training dataset contains no frozen items")

        if len(items) != dataset.item_count:
            raise ConflictError(
                "Pose training dataset item count does not match its immutable manifest"
            )

        for item in items:
            if (
                item.pose_schema_id != dataset.pose_schema_id
                or item.pose_schema_revision != dataset.pose_schema_revision
                or item.pose_schema_content_hash != dataset.pose_schema_content_hash
            ):
                raise ConflictError("Frozen pose item schema identity does not match the dataset")

        return items

    def _schema(
        self,
        dataset: PoseTrainingDataset,
    ) -> _SchemaContext:
        revision = self.session.scalar(
            select(PoseLandmarkSchemaRevision).where(
                PoseLandmarkSchemaRevision.schema_id == dataset.pose_schema_id,
                PoseLandmarkSchemaRevision.revision == dataset.pose_schema_revision,
            )
        )

        if revision is None:
            raise ConflictError("Frozen pose dataset references a missing landmark schema revision")

        if revision.content_hash != dataset.pose_schema_content_hash:
            raise ConflictError(
                "Frozen pose schema content hash no longer matches its immutable dataset identity"
            )

        labels = tuple(str(item) for item in revision.expanded_labels_json)

        if not labels:
            raise ConflictError("Frozen pose schema contains no landmarks")

        if len(labels) != revision.keypoint_count:
            raise ConflictError("Frozen pose schema keypoint count is inconsistent")

        node_names, mapping = PoseInteroperabilityService._external_node_names(labels)

        return _SchemaContext(
            expanded_labels=labels,
            external_node_names=node_names,
            node_mapping=mapping,
            metadata={
                "schema_version": revision.schema_version,
                "schema_id": revision.schema_id,
                "schema_revision": revision.revision,
                "groups": list(revision.groups_json),
                "expanded_labels": list(labels),
                "keypoint_count": revision.keypoint_count,
                "allows_repeated_labels": (revision.allows_repeated_labels),
                "content_hash": revision.content_hash,
            },
        )

    def _source_video(
        self,
        items: list[PoseTrainingDatasetItem],
    ) -> tuple[VideoAsset, Path, str, int]:
        video_ids = {item.video_id for item in items}

        if len(video_ids) != 1:
            raise ValidationError("One retraining export must reference exactly one source video")

        video_id = next(iter(video_ids))

        expected_hashes = {item.video_sha256 for item in items}

        if len(expected_hashes) != 1:
            raise ConflictError("Frozen dataset contains inconsistent source video checksums")

        expected_hash = next(iter(expected_hashes))

        frozen_revisions = {item.video_revision for item in items}

        if len(frozen_revisions) != 1:
            raise ConflictError("Frozen dataset contains inconsistent source video revisions")

        frozen_revision = next(iter(frozen_revisions))

        video = self.session.get(
            VideoAsset,
            video_id,
        )

        if video is None:
            raise NotFoundError("Frozen dataset source video no longer exists")

        if video.sha256 != expected_hash:
            raise ConflictError("Source video database checksum differs from the frozen dataset")

        source = resolve_managed_project_path(
            self.settings,
            video.managed_path,
        )

        if not source.is_file():
            raise NotFoundError("Managed source video file is missing")

        if sha256_file(source) != expected_hash:
            raise ConflictError(
                "Managed source video bytes differ from the frozen dataset checksum"
            )

        if video.width_px <= 0 or video.height_px <= 0 or video.frame_count <= 0:
            raise ValidationError(
                "Source video dimensional/frame metadata is required for pose training export"
            )

        return (
            video,
            source,
            expected_hash,
            frozen_revision,
        )

    @staticmethod
    def _slot_keys(
        labels: tuple[str, ...],
    ) -> tuple[tuple[str, int], ...]:
        seen: dict[str, int] = defaultdict(int)
        result: list[tuple[str, int]] = []

        for label in labels:
            occurrence = seen[label]
            seen[label] += 1
            result.append(
                (
                    label,
                    occurrence,
                )
            )

        return tuple(result)

    @classmethod
    def _pose_slots(
        cls,
        item: PoseTrainingDatasetItem,
        schema: _SchemaContext,
        *,
        width: int,
        height: int,
    ) -> list[dict[str, object]]:
        pose = dict(item.canonical_pose_json or {})
        slots = cls._slot_keys(schema.expanded_labels)
        valid_slots = set(slots)

        observations_raw = pose.get("pose_observations")

        observations: dict[
            tuple[str, int],
            dict[str, object],
        ] = {}

        if (
            isinstance(
                observations_raw,
                list,
            )
            and observations_raw
        ):
            for raw in observations_raw:
                if not isinstance(raw, dict):
                    raise ConflictError("Frozen canonical pose contains malformed observations")

                label = str(raw.get("semantic_label") or "").strip()

                occurrence_raw = raw.get("occurrence_index")

                if (
                    not isinstance(
                        occurrence_raw,
                        int,
                    )
                    or isinstance(
                        occurrence_raw,
                        bool,
                    )
                    or occurrence_raw < 0
                ):
                    raise ConflictError(
                        "Frozen canonical pose contains an invalid landmark occurrence index"
                    )

                key = (
                    label,
                    occurrence_raw,
                )

                if key not in valid_slots:
                    raise ConflictError(
                        "Frozen pose observation does not match its immutable landmark schema"
                    )

                if key in observations:
                    raise ConflictError(
                        "Frozen canonical pose contains a duplicate landmark occurrence"
                    )

                observations[key] = {str(k): v for k, v in raw.items()}

        elif isinstance(
            pose.get("keypoints"),
            list,
        ):
            keypoints = list(pose["keypoints"])

            if len(keypoints) != len(slots):
                raise ConflictError(
                    "Frozen pose keypoint count does not match its immutable schema"
                )

            for key, raw in zip(
                slots,
                keypoints,
                strict=True,
            ):
                if (
                    not isinstance(
                        raw,
                        (list, tuple),
                    )
                    or len(raw) < 3
                ):
                    raise ConflictError("Frozen keypoint is malformed")

                legacy_confidence = float(raw[2])

                observations[key] = {
                    "semantic_label": key[0],
                    "occurrence_index": key[1],
                    "x": float(raw[0]),
                    "y": float(raw[1]),
                    "confidence": legacy_confidence,
                    "status": ("visible" if legacy_confidence > 0 else "absent"),
                    "source": "frozen",
                }

        else:
            raise ConflictError("Frozen canonical pose contains no usable landmark representation")

        output: list[dict[str, object]] = []

        for label, occurrence in slots:
            raw = observations.get(
                (
                    label,
                    occurrence,
                )
            )

            if raw is None:
                output.append(
                    {
                        "semantic_label": label,
                        "occurrence_index": occurrence,
                        "x": 0.0,
                        "y": 0.0,
                        "confidence": None,
                        "status": "absent",
                        "source": "frozen_missing",
                    }
                )
                continue

            status = str(raw.get("status") or "visible")

            if status not in {
                "visible",
                "uncertain",
                "occluded",
                "absent",
                "out_of_frame",
            }:
                raise ConflictError("Frozen pose contains an unsupported visibility state")

            confidence_raw = raw.get("confidence")

            confidence: float | None

            if confidence_raw is None:
                confidence = None
            else:
                confidence = float(cast(Any, confidence_raw))

                if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
                    raise ConflictError("Frozen pose confidence is invalid")

            if status in {
                "absent",
                "out_of_frame",
            }:
                x = 0.0
                y = 0.0
            else:
                try:
                    x = float(cast(Any, raw["x"]))
                    y = float(cast(Any, raw["y"]))
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                ) as exc:
                    raise ConflictError(
                        "Frozen visible/occluded landmark is missing coordinates"
                    ) from exc

                if not math.isfinite(x) or not math.isfinite(y):
                    raise ConflictError("Frozen landmark coordinates are not finite")

                if x < 0 or y < 0 or x >= width or y >= height:
                    raise ConflictError(
                        "Frozen landmark coordinates extend outside the source image"
                    )

            output.append(
                {
                    "semantic_label": label,
                    "occurrence_index": occurrence,
                    "x": x,
                    "y": y,
                    "confidence": confidence,
                    "status": status,
                    "source": str(raw.get("source") or "frozen"),
                }
            )

        return output

    @staticmethod
    def _bbox(
        item: PoseTrainingDatasetItem,
        *,
        width: int,
        height: int,
    ) -> tuple[
        float,
        float,
        float,
        float,
    ]:
        raw = dict(item.canonical_pose_json or {}).get("bbox")

        if (
            not isinstance(
                raw,
                (list, tuple),
            )
            or len(raw) != 4
        ):
            raise ConflictError("Frozen canonical pose requires a four-value bounding box")

        try:
            x, y, w, h = (float(value) for value in raw)
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ConflictError("Frozen pose bounding box is malformed") from exc

        if not all(
            math.isfinite(value)
            for value in (
                x,
                y,
                w,
                h,
            )
        ):
            raise ConflictError("Frozen pose bounding box contains non-finite values")

        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width + 1e-6 or y + h > height + 1e-6:
            raise ConflictError("Frozen pose bounding box extends outside the source frame")

        return (
            x,
            y,
            w,
            h,
        )

    @staticmethod
    def _frame_path(
        export_format: PoseTrainingExportFormat,
        frame_index: int,
    ) -> str:
        name = f"frame_{frame_index:08d}.png"

        if export_format == "ultralytics_pose":
            return f"images/train/{name}"

        if export_format == "dlc_csv":
            return f"labeled-data/ReefVisionPose/{name}"

        return f"frames/{name}"

    @staticmethod
    def _extract_exact_frames(
        *,
        source: Path,
        video: VideoAsset,
        frame_indices: list[int],
        export_format: PoseTrainingExportFormat,
    ) -> tuple[
        dict[str, bytes],
        list[dict[str, object]],
    ]:
        unique = sorted(set(frame_indices))

        if not unique:
            raise ValidationError("Pose training export requires at least one source frame")

        if unique[0] < 0:
            raise ValidationError("Pose training export contains a negative frame index")

        if unique[-1] >= video.frame_count:
            raise ValidationError("Pose training export frame is outside the source video")

        capture = cv2.VideoCapture(str(source))

        if not capture.isOpened():
            capture.release()
            raise ValidationError(
                "Could not open the managed source video for exact frame extraction"
            )

        targets = set(unique)
        files: dict[str, bytes] = {}
        records: list[dict[str, object]] = []

        frame_index = 0
        maximum = unique[-1]

        try:
            while frame_index <= maximum:
                ok, frame = capture.read()

                if not ok or frame is None:
                    raise ValidationError(
                        f"Source video ended before frozen frame {maximum} could be decoded"
                    )

                if frame_index in targets:
                    height, width = frame.shape[:2]

                    if width != video.width_px or height != video.height_px:
                        raise ConflictError(
                            "Decoded frame dimensions differ from source video metadata"
                        )

                    encoded_ok, encoded = cv2.imencode(
                        ".png",
                        frame,
                        [
                            cv2.IMWRITE_PNG_COMPRESSION,
                            3,
                        ],
                    )

                    if not encoded_ok:
                        raise ValidationError("Could not encode exact source frame as lossless PNG")

                    content = encoded.tobytes()

                    relative = PoseTrainingExportService._frame_path(
                        export_format,
                        frame_index,
                    )

                    files[relative] = content

                    records.append(
                        {
                            "source_frame_index": (frame_index),
                            "path": relative,
                            "sha256": (hashlib.sha256(content).hexdigest()),
                            "size_bytes": len(content),
                            "width_px": width,
                            "height_px": height,
                            "encoding": ("png-lossless"),
                        }
                    )

                frame_index += 1

        finally:
            capture.release()

        if len(records) != len(unique):
            raise ConflictError("Not every frozen source frame was extracted")

        return files, records

    def _class_mapping(
        self,
        items: list[PoseTrainingDatasetItem],
    ) -> list[dict[str, object]]:
        class_ids = sorted({item.label_class_id for item in items})

        output: list[dict[str, object]] = []

        for index, class_id in enumerate(class_ids):
            label = self.session.get(
                LabelClass,
                class_id,
            )

            output.append(
                {
                    "class_index": index,
                    "label_class_id": class_id,
                    "display_name": (label.name if label is not None else class_id),
                }
            )

        return output

    @staticmethod
    def _loss_policy(
        export_format: PoseTrainingExportFormat,
    ) -> dict[str, object]:
        common_manifest_only = [
            "scientist review/correction audit",
            "active-learning acquisition components",
            "source model/provider/checkpoint provenance",
            "verified pose SHA-256",
            "immutable item SHA-256",
            "source track revision",
        ]

        if export_format == "coco":
            return {
                "lossy_native_artifact": True,
                "preserved_natively": [
                    "source image",
                    "bounding box",
                    "landmark coordinates",
                    "visible/occluded/absent state via COCO visibility",
                    "class",
                ],
                "transformed": [
                    ("uncertain visibility is represented as visible in COCO"),
                    ("repeated semantic landmarks use stable unique external node names"),
                ],
                "manifest_only": [
                    *common_manifest_only,
                    "landmark confidence",
                    "original repeated semantic label mapping",
                ],
            }

        if export_format == "dlc_csv":
            return {
                "lossy_native_artifact": True,
                "preserved_natively": [
                    "source image",
                    "landmark coordinates",
                ],
                "transformed": [
                    ("repeated semantic landmarks use stable unique body-part names"),
                ],
                "manifest_only": [
                    *common_manifest_only,
                    "visibility state",
                    "landmark confidence",
                    "bounding box",
                    "track identity",
                    "class identity",
                    "original repeated semantic label mapping",
                ],
            }

        if export_format == "ultralytics_pose":
            return {
                "lossy_native_artifact": True,
                "preserved_natively": [
                    "source image",
                    "normalized bounding box",
                    "landmark coordinates",
                    "visible/occluded/absent state",
                    "class",
                ],
                "transformed": [
                    ("uncertain visibility is represented as visible"),
                    ("repeated semantic landmarks are represented by fixed keypoint order"),
                ],
                "manifest_only": [
                    *common_manifest_only,
                    "landmark confidence",
                    "original repeated semantic label mapping",
                ],
            }

        if export_format == "slp":
            return {
                "lossy_native_artifact": True,
                "preserved_natively": [
                    "source video/frame index",
                    "landmark coordinates",
                    "landmark visibility",
                    "track grouping",
                    "stable unique landmark names",
                ],
                "transformed": [
                    ("repeated semantic landmarks use stable unique SLEAP node names"),
                ],
                "manifest_only": [
                    *common_manifest_only,
                    "original repeated semantic label mapping",
                    "full frozen canonical pose JSON",
                ],
            }

        return {
            "lossy_native_artifact": True,
            "preserved_natively": [
                "source-frame timestamps",
                "landmark coordinates",
                "track grouping where supported",
            ],
            "transformed": [
                ("repeated semantic landmarks use stable unique external node names"),
            ],
            "manifest_only": [
                *common_manifest_only,
                "visibility distinctions not represented by NWB writer",
                "original repeated semantic label mapping",
                "full frozen canonical pose JSON",
            ],
        }

    def _manifest(
        self,
        *,
        export_format: PoseTrainingExportFormat,
        dataset: PoseTrainingDataset,
        items: list[PoseTrainingDatasetItem],
        video: VideoAsset,
        source_video_sha256: str,
        frozen_video_revision: int,
        schema: _SchemaContext,
        frame_records: list[dict[str, object]],
        class_mapping: list[dict[str, object]],
    ) -> dict[str, object]:
        annotations = []

        for item in items:
            annotations.append(
                {
                    "item_id": item.id,
                    "item_sha256": (item.item_sha256),
                    "candidate_id": (item.candidate_id),
                    "source_frame_index": (item.frame_index),
                    "video_track_id": (item.video_track_id),
                    "label_class_id": (item.label_class_id),
                    "verified_track_revision": (item.verified_track_revision),
                    "verified_pose_sha256": (item.verified_pose_sha256),
                    "canonical_pose": dict(item.canonical_pose_json),
                    "source_models": list(item.source_models_json),
                    "source_job_ids": list(item.source_job_ids_json),
                    "acquisition_provenance": dict(item.acquisition_provenance_json),
                    "review_provenance": dict(item.review_provenance_json),
                }
            )

        return {
            "schema_version": (EXPORT_SCHEMA_VERSION),
            "format": export_format,
            "truth_policy": ("scientist_verified_only"),
            "dataset": {
                "dataset_id": dataset.id,
                "dataset_name": dataset.name,
                "source_round_id": (dataset.source_round_id),
                "dataset_schema_version": (dataset.schema_version),
                "dataset_manifest_sha256": (dataset.manifest_sha256),
                "source_selection_sha256": (dataset.source_selection_sha256),
                "source_retraining_manifest_sha256": (dataset.source_retraining_manifest_sha256),
                "item_count": (dataset.item_count),
            },
            "source_video": {
                "video_id": video.id,
                "sha256": (source_video_sha256),
                "frozen_video_revision": (frozen_video_revision),
                "export_time_record_revision": (video.revision),
                "original_filename": (video.original_filename),
                "width_px": video.width_px,
                "height_px": video.height_px,
                "frame_count": video.frame_count,
                "fps": video.fps,
            },
            "pose_schema": {
                **schema.metadata,
                "external_node_names": list(schema.external_node_names),
                "node_mapping": list(schema.node_mapping),
            },
            "classes": class_mapping,
            "frame_extraction": {
                "method": ("opencv-sequential-decode-0001"),
                "decoder": "opencv",
                "decoder_version": (cv2.__version__),
                "source_frame_index_base": 0,
                "output_encoding": ("png-lossless"),
                "frames": frame_records,
            },
            "native_loss_policy": (self._loss_policy(export_format)),
            "annotations": annotations,
        }

    @staticmethod
    def _native_visibility(
        slot: dict[str, object],
    ) -> int:
        status = str(slot["status"])

        if status in {
            "absent",
            "out_of_frame",
        }:
            return 0

        if status == "occluded":
            return 1

        return 2

    def _coco(
        self,
        *,
        items: list[PoseTrainingDatasetItem],
        schema: _SchemaContext,
        video: VideoAsset,
        class_mapping: list[dict[str, object]],
    ) -> bytes:
        class_index = {
            str(item["label_class_id"]): (int(cast(Any, item["class_index"])) + 1)
            for item in class_mapping
        }

        frames = sorted({item.frame_index for item in items})

        image_ids = {frame: index + 1 for index, frame in enumerate(frames)}

        images = [
            {
                "id": image_ids[frame],
                "file_name": (
                    self._frame_path(
                        "coco",
                        frame,
                    )
                ),
                "width": video.width_px,
                "height": video.height_px,
            }
            for frame in frames
        ]

        categories = [
            {
                "id": (int(cast(Any, item["class_index"])) + 1),
                "name": str(item["display_name"]),
                "supercategory": "pose",
                "keypoints": list(schema.external_node_names),
                "skeleton": [],
            }
            for item in class_mapping
        ]

        annotations = []

        for annotation_id, item in enumerate(
            items,
            start=1,
        ):
            slots = self._pose_slots(
                item,
                schema,
                width=video.width_px,
                height=video.height_px,
            )

            keypoints: list[float | int] = []

            visible_count = 0

            for slot in slots:
                visibility = self._native_visibility(slot)

                if visibility == 0:
                    x = 0.0
                    y = 0.0
                else:
                    x = float(cast(Any, slot["x"]))
                    y = float(cast(Any, slot["y"]))
                    visible_count += 1

                keypoints.extend(
                    [
                        x,
                        y,
                        visibility,
                    ]
                )

            x, y, w, h = self._bbox(
                item,
                width=video.width_px,
                height=video.height_px,
            )

            annotations.append(
                {
                    "id": annotation_id,
                    "image_id": (image_ids[item.frame_index]),
                    "category_id": (class_index[item.label_class_id]),
                    "bbox": [
                        x,
                        y,
                        w,
                        h,
                    ],
                    "area": w * h,
                    "iscrowd": 0,
                    "num_keypoints": (visible_count),
                    "keypoints": keypoints,
                }
            )

        document = {
            "info": {
                "description": ("ReefVision immutable scientist-verified pose dataset"),
            },
            "images": images,
            "annotations": annotations,
            "categories": categories,
        }

        return (
            json.dumps(
                document,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    def _dlc(
        self,
        *,
        items: list[PoseTrainingDatasetItem],
        schema: _SchemaContext,
        video: VideoAsset,
    ) -> bytes:
        frame_counts = Counter(item.frame_index for item in items)

        duplicate_frames = [frame for frame, count in frame_counts.items() if count > 1]

        if duplicate_frames:
            raise ValidationError(
                "DeepLabCut CSV training export cannot "
                "silently flatten multiple individuals in "
                "the same image. Use SLEAP, COCO, or "
                "Ultralytics pose for multi-instance data."
            )

        stream = io.StringIO(newline="")
        writer = csv.writer(
            stream,
            lineterminator="\n",
        )

        scorer = ["scorer"]

        bodyparts = ["bodyparts"]

        coords = ["coords"]

        for name in schema.external_node_names:
            scorer.extend(
                [
                    "ReefVision",
                    "ReefVision",
                ]
            )
            bodyparts.extend(
                [
                    name,
                    name,
                ]
            )
            coords.extend(
                [
                    "x",
                    "y",
                ]
            )

        writer.writerow(scorer)
        writer.writerow(bodyparts)
        writer.writerow(coords)

        for item in items:
            slots = self._pose_slots(
                item,
                schema,
                width=video.width_px,
                height=video.height_px,
            )

            row: list[object] = [
                self._frame_path(
                    "dlc_csv",
                    item.frame_index,
                )
            ]

            for slot in slots:
                if str(slot["status"]) in {
                    "absent",
                    "out_of_frame",
                }:
                    row.extend(
                        [
                            "",
                            "",
                        ]
                    )
                else:
                    row.extend(
                        [
                            float(cast(Any, slot["x"])),
                            float(cast(Any, slot["y"])),
                        ]
                    )

            writer.writerow(row)

        return stream.getvalue().encode("utf-8")

    def _ultralytics(
        self,
        *,
        items: list[PoseTrainingDatasetItem],
        schema: _SchemaContext,
        video: VideoAsset,
        class_mapping: list[dict[str, object]],
    ) -> dict[str, bytes]:
        class_index = {
            str(item["label_class_id"]): int(cast(Any, item["class_index"]))
            for item in class_mapping
        }

        labels_by_frame: dict[
            int,
            list[str],
        ] = defaultdict(list)

        for item in items:
            x, y, w, h = self._bbox(
                item,
                width=video.width_px,
                height=video.height_px,
            )

            center_x = (x + w / 2.0) / video.width_px
            center_y = (y + h / 2.0) / video.height_px

            tokens = [
                str(class_index[item.label_class_id]),
                f"{center_x:.9g}",
                f"{center_y:.9g}",
                f"{w / video.width_px:.9g}",
                f"{h / video.height_px:.9g}",
            ]

            slots = self._pose_slots(
                item,
                schema,
                width=video.width_px,
                height=video.height_px,
            )

            for slot in slots:
                visibility = self._native_visibility(slot)

                if visibility == 0:
                    normalized_x = 0.0
                    normalized_y = 0.0
                else:
                    normalized_x = float(cast(Any, slot["x"])) / video.width_px
                    normalized_y = float(cast(Any, slot["y"])) / video.height_px

                tokens.extend(
                    [
                        f"{normalized_x:.9g}",
                        f"{normalized_y:.9g}",
                        str(visibility),
                    ]
                )

            labels_by_frame[item.frame_index].append(" ".join(tokens))

        files: dict[str, bytes] = {}

        for frame_index in sorted(labels_by_frame):
            name = f"frame_{frame_index:08d}.txt"

            rows = sorted(labels_by_frame[frame_index])

            files[f"labels/train/{name}"] = ("\n".join(rows) + "\n").encode("utf-8")

        yaml_lines = [
            "path: .",
            "train: images/train",
            "val: images/train",
            (f"kpt_shape: [{len(schema.external_node_names)}, 3]"),
            "names:",
        ]

        for class_entry in class_mapping:
            yaml_lines.append(
                f"  {int(cast(Any, class_entry['class_index']))}: "
                + json.dumps(str(class_entry["display_name"]))
            )

        yaml_lines.append("reefvision_keypoint_names:")

        for name in schema.external_node_names:
            yaml_lines.append("  - " + json.dumps(name))

        files["data.yaml"] = ("\n".join(yaml_lines) + "\n").encode("utf-8")

        return files

    def _sleap_labels(
        self,
        *,
        export_format: PoseTrainingExportFormat,
        items: list[PoseTrainingDatasetItem],
        schema: _SchemaContext,
        video: VideoAsset,
        source: Path,
        manifest: dict[str, object],
    ) -> tuple[Any, Any]:
        sio = PoseInteroperabilityService._sleap_io()

        skeleton = sio.Skeleton(
            nodes=list(schema.external_node_names),
            name=("ReefVision verified pose training"),
        )

        sio_video = sio.Video.from_filename(
            str(source),
            keep_open=False,
            grayscale=False,
        )

        tracks = {
            track_id: sio.Track(name=(f"reefvision-frozen-{track_id[:12]}"))
            for track_id in sorted({item.video_track_id for item in items})
        }

        instances_by_frame: dict[
            int,
            list[Any],
        ] = defaultdict(list)

        for item in items:
            slots = self._pose_slots(
                item,
                schema,
                width=video.width_px,
                height=video.height_px,
            )

            point_count = len(schema.external_node_names)

            points = np.full(
                (
                    point_count,
                    2,
                ),
                np.nan,
                dtype=np.float64,
            )

            scores = np.full(
                point_count,
                np.nan,
                dtype=np.float64,
            )

            visible = np.zeros(
                point_count,
                dtype=np.bool_,
            )

            for index, slot in enumerate(slots):
                status = str(slot["status"])

                if status not in {
                    "absent",
                    "out_of_frame",
                }:
                    points[
                        index,
                        0,
                    ] = float(cast(Any, slot["x"]))
                    points[
                        index,
                        1,
                    ] = float(cast(Any, slot["y"]))

                confidence = slot["confidence"]

                if confidence is not None:
                    scores[index] = float(cast(Any, confidence))

                visible[index] = status in {
                    "visible",
                    "uncertain",
                }

            external_track = tracks[item.video_track_id]

            instance: Any | None = None

            if export_format == "slp":
                user_instance = getattr(
                    sio,
                    "Instance",
                    None,
                )

                if user_instance is not None and hasattr(
                    user_instance,
                    "from_numpy",
                ):
                    try:
                        instance = user_instance.from_numpy(
                            points,
                            skeleton=skeleton,
                            track=external_track,
                        )
                    except (
                        TypeError,
                        ValueError,
                    ):
                        instance = None

            if instance is None:
                instance = sio.PredictedInstance.from_numpy(
                    points,
                    skeleton=skeleton,
                    point_scores=scores,
                    score=float(
                        cast(
                            Any,
                            dict(item.canonical_pose_json or {}).get("confidence") or 1.0,
                        )
                    ),
                    track=external_track,
                    tracking_score=None,
                )

            raw_points = getattr(
                instance,
                "points",
                None,
            )

            dtype_names = (
                getattr(
                    getattr(
                        raw_points,
                        "dtype",
                        None,
                    ),
                    "names",
                    None,
                )
                or ()
            )

            if raw_points is not None and "visible" in dtype_names:
                raw_points["visible"] = visible

            if raw_points is not None and "score" in dtype_names:
                raw_points["score"] = scores

            instances_by_frame[item.frame_index].append(instance)

        labeled_frames = [
            sio.LabeledFrame(
                video=sio_video,
                frame_idx=frame_index,
                instances=instances_by_frame[frame_index],
            )
            for frame_index in sorted(instances_by_frame)
        ]

        labels = sio.Labels(
            labeled_frames=labeled_frames,
            videos=[sio_video],
            skeletons=[skeleton],
            tracks=list(tracks.values()),
            categories=[],
            provenance={
                "reefvision_pose_training_export": (manifest),
            },
        )

        return (
            sio,
            labels,
        )

    def _slp_or_nwb(
        self,
        *,
        export_format: PoseTrainingExportFormat,
        items: list[PoseTrainingDatasetItem],
        schema: _SchemaContext,
        video: VideoAsset,
        source: Path,
        manifest: dict[str, object],
    ) -> tuple[str, bytes]:
        sio, labels = self._sleap_labels(
            export_format=export_format,
            items=items,
            schema=schema,
            video=video,
            source=source,
            manifest=manifest,
        )

        with TemporaryDirectory(prefix="reefvision-pose-training-export-") as temp:
            root = Path(temp)

            if export_format == "slp":
                output = root / "dataset.pose.slp"

                sio.save_slp(
                    labels,
                    str(output),
                    embed="all",
                    verbose=False,
                )

                return (
                    "dataset.pose.slp",
                    output.read_bytes(),
                )

            output = root / "dataset.pose.nwb"

            PoseInteroperabilityService._save_nwb_predictions(
                sio,
                labels,
                output,
                frame_count=video.frame_count,
                fps=video.fps,
            )

            return (
                "dataset.pose.nwb",
                output.read_bytes(),
            )

    @staticmethod
    def _write_zip(
        files: dict[str, bytes],
    ) -> bytes:
        stream = io.BytesIO()

        with zipfile.ZipFile(
            stream,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for name in sorted(files):
                info = zipfile.ZipInfo(
                    filename=name,
                    date_time=(
                        1980,
                        1,
                        1,
                        0,
                        0,
                        0,
                    ),
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(
                    info,
                    files[name],
                )

        return stream.getvalue()

    def export(
        self,
        dataset_id: str,
        export_format: PoseTrainingExportFormat,
    ) -> PoseTrainingExportArtifact:
        if export_format not in {
            "slp",
            "nwb",
            "coco",
            "dlc_csv",
            "ultralytics_pose",
        }:
            raise ValidationError(f"Unsupported pose training export: {export_format}")

        dataset = self._dataset(dataset_id)
        items = self._items(dataset)
        schema = self._schema(dataset)

        (
            video,
            source,
            source_hash,
            frozen_video_revision,
        ) = self._source_video(items)

        class_mapping = self._class_mapping(items)

        files, frame_records = self._extract_exact_frames(
            source=source,
            video=video,
            frame_indices=[item.frame_index for item in items],
            export_format=export_format,
        )

        manifest = self._manifest(
            export_format=export_format,
            dataset=dataset,
            items=items,
            video=video,
            source_video_sha256=source_hash,
            frozen_video_revision=(frozen_video_revision),
            schema=schema,
            frame_records=frame_records,
            class_mapping=class_mapping,
        )

        native_files: dict[
            str,
            bytes,
        ] = {}

        if export_format == "coco":
            native_files["annotations/instances_pose.json"] = self._coco(
                items=items,
                schema=schema,
                video=video,
                class_mapping=class_mapping,
            )

        elif export_format == "dlc_csv":
            native_files["CollectedData_ReefVision.csv"] = self._dlc(
                items=items,
                schema=schema,
                video=video,
            )

        elif export_format == "ultralytics_pose":
            native_files.update(
                self._ultralytics(
                    items=items,
                    schema=schema,
                    video=video,
                    class_mapping=class_mapping,
                )
            )

        else:
            name, content = self._slp_or_nwb(
                export_format=export_format,
                items=items,
                schema=schema,
                video=video,
                source=source,
                manifest=manifest,
            )
            native_files[name] = content

        files.update(native_files)

        manifest["native_artifacts"] = [
            {
                "path": name,
                "sha256": (hashlib.sha256(content).hexdigest()),
                "size_bytes": len(content),
            }
            for name, content in sorted(native_files.items())
        ]

        files[EXPORT_MANIFEST_FILENAME] = (
            json.dumps(
                manifest,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

        files["README.txt"] = (
            b"ReefVision scientist-verified pose training export\n"
            b"\n"
            b"The native external artifact is intentionally treated as lossy.\n"
            b"Use reefvision-pose-training-export-manifest.json to recover\n"
            b"repeated semantic landmark mapping, canonical frozen poses,\n"
            b"review/acquisition provenance, checksums, and exact source-frame\n"
            b"identity. PNG images were decoded sequentially from the managed\n"
            b"source video after validating its SHA-256 against the frozen\n"
            b"training dataset.\n"
        )

        bundle = self._write_zip(files)

        return PoseTrainingExportArtifact(
            filename=(f"pose-training-{dataset.id}.{export_format}.zip"),
            media_type="application/zip",
            content=bundle,
            export_format=export_format,
            lossy=True,
            bundle_sha256=(hashlib.sha256(bundle).hexdigest()),
        )

"""Loss-aware pose export through the optional SLEAP-IO interoperability runtime."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    LabelClass,
    PoseLandmarkSchema,
    PoseLandmarkSchemaRevision,
    VideoAsset,
    VideoTrack,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.sleap_nn_provider import SLEAP_IO_SUPPORTED_VERSION
from reefvision.schemas.pose_interoperability import (
    PoseInteroperabilityFormat,
    PoseInteroperabilityImportResponse,
)
from reefvision.schemas.videos import VideoPoseObservation, VideoTrackKeyframe
from reefvision.storage.projects import resolve_managed_project_path


@dataclass(frozen=True)
class PoseInteroperabilityArtifact:
    filename: str
    media_type: str
    content: bytes
    exchange_format: PoseInteroperabilityFormat
    lossy: bool = True


@dataclass(frozen=True)
class _PoseSchemaContext:
    expanded_labels: tuple[str, ...]
    external_node_names: tuple[str, ...]
    node_mapping: tuple[dict[str, object], ...]
    schema_metadata: dict[str, object]


@dataclass(frozen=True)
class _ImportedSchema:
    groups: tuple[dict[str, object], ...]
    expanded_labels: tuple[str, ...]
    external_node_names: tuple[str, ...]
    used_reefvision_provenance: bool
    provenance: dict[str, object] | None


@dataclass(frozen=True)
class _ImportedTrack:
    external_track_name: str | None
    keyframes: tuple[VideoTrackKeyframe, ...]


POSE_BUNDLE_MANIFEST_FILENAME = "reefvision-pose-manifest.json"


class PoseInteroperabilityService:
    """Translate canonical ReefVision video poses into external pose ecosystems."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    @staticmethod
    def _sleap_io() -> Any:
        try:
            installed = version("sleap-io")
        except PackageNotFoundError as exc:
            raise ValidationError(
                "Pose interoperability requires optional sleap-io "
                f"{SLEAP_IO_SUPPORTED_VERSION}"
            ) from exc
        if installed != SLEAP_IO_SUPPORTED_VERSION:
            raise ValidationError(
                "Pose interoperability requires sleap-io "
                f"{SLEAP_IO_SUPPORTED_VERSION}; found {installed}"
            )
        try:
            return import_module("sleap_io")
        except Exception as exc:
            raise ValidationError(
                f"sleap-io {SLEAP_IO_SUPPORTED_VERSION} could not be imported: {exc}"
            ) from exc

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _pose_tracks(self, video_id: str) -> list[VideoTrack]:
        tracks = list(
            self.session.scalars(
                select(VideoTrack)
                .where(
                    VideoTrack.video_id == video_id,
                    VideoTrack.deleted_at.is_(None),
                )
                .order_by(VideoTrack.track_number, VideoTrack.id)
            )
        )
        pose_tracks = [
            track
            for track in tracks
            if isinstance((track.metadata_json or {}).get("pose_landmark_schema"), dict)
            and any(
                isinstance(item, dict)
                and (item.get("pose_observations") is not None or item.get("keypoints") is not None)
                for item in track.keyframes_json
            )
        ]
        if not pose_tracks:
            raise ValidationError(
                "No canonical pose tracks with a bound ReefVision landmark schema are available"
            )
        return pose_tracks

    @staticmethod
    def _external_node_names(labels: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[dict[str, object], ...]]:
        counts = Counter(labels)
        seen: dict[str, int] = defaultdict(int)
        used: set[str] = set()
        names: list[str] = []
        mapping: list[dict[str, object]] = []
        for label in labels:
            occurrence = seen[label]
            seen[label] += 1
            candidate = label if counts[label] == 1 else f"{label}__{occurrence + 1}"
            base = candidate
            collision = 2
            while candidate in used:
                candidate = f"{base}__rv{collision}"
                collision += 1
            used.add(candidate)
            names.append(candidate)
            mapping.append(
                {
                    "external_node_name": candidate,
                    "semantic_label": label,
                    "occurrence_index": occurrence,
                }
            )
        return tuple(names), tuple(mapping)

    @classmethod
    def _schema_context(cls, tracks: list[VideoTrack]) -> _PoseSchemaContext:
        first = cast(dict[str, object], (tracks[0].metadata_json or {})["pose_landmark_schema"])
        labels_raw = first.get("expanded_labels")
        if not isinstance(labels_raw, list) or not labels_raw:
            raise ValidationError("Canonical pose schema is missing expanded landmark labels")
        expanded = tuple(str(item).strip() for item in labels_raw)
        if any(not item for item in expanded):
            raise ValidationError("Canonical pose schema contains a blank landmark label")

        first_hash = first.get("content_hash")
        for track in tracks[1:]:
            current = cast(
                dict[str, object],
                (track.metadata_json or {})["pose_landmark_schema"],
            )
            current_labels_raw = current.get("expanded_labels")
            current_labels = (
                tuple(str(item).strip() for item in current_labels_raw)
                if isinstance(current_labels_raw, list)
                else ()
            )
            if current_labels != expanded:
                raise ValidationError(
                    "Pose interoperability requires one canonical landmark schema per video export"
                )
            current_hash = current.get("content_hash")
            if first_hash is not None and current_hash is not None and current_hash != first_hash:
                raise ValidationError(
                    "Pose interoperability cannot mix different landmark schema revisions"
                )

        node_names, mapping = cls._external_node_names(expanded)
        return _PoseSchemaContext(
            expanded_labels=expanded,
            external_node_names=node_names,
            node_mapping=mapping,
            schema_metadata=dict(first),
        )

    @staticmethod
    def _slot_keys(labels: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
        seen: dict[str, int] = defaultdict(int)
        keys: list[tuple[str, int]] = []
        for label in labels:
            occurrence = seen[label]
            seen[label] += 1
            keys.append((label, occurrence))
        return tuple(keys)

    @classmethod
    def _keyframe_points(
        cls,
        keyframe: VideoTrackKeyframe,
        schema: _PoseSchemaContext,
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
        point_count = len(schema.expanded_labels)
        points = np.full((point_count, 3), np.nan, dtype=np.float64)
        points[:, 2] = 0.0
        scores = np.zeros(point_count, dtype=np.float64)

        if keyframe.pose_observations is not None:
            observations: dict[tuple[str, int], VideoPoseObservation] = {}
            valid_keys = set(cls._slot_keys(schema.expanded_labels))
            for observation in keyframe.pose_observations:
                key = (observation.semantic_label, observation.occurrence_index)
                if key not in valid_keys:
                    raise ValidationError(
                        "Pose observation does not match the bound canonical landmark schema"
                    )
                if key in observations:
                    raise ValidationError(
                        "Pose keyframe contains a duplicate semantic-label occurrence"
                    )
                observations[key] = observation

            for index, key in enumerate(cls._slot_keys(schema.expanded_labels)):
                current_observation = observations.get(key)
                if current_observation is None:
                    continue
                scores[index] = float(current_observation.confidence or 0.0)
                if current_observation.status in {"absent", "out_of_frame"}:
                    continue
                points[index, 0] = float(current_observation.x)
                points[index, 1] = float(current_observation.y)
                points[index, 2] = (
                    1.0
                    if current_observation.status in {"visible", "uncertain"}
                    else 0.0
                )
            return points, scores

        if keyframe.keypoints is None:
            return None
        if len(keyframe.keypoints) != point_count:
            raise ValidationError(
                "Pose keypoint count does not match the bound canonical landmark schema"
            )
        for index, (x, y, confidence) in enumerate(keyframe.keypoints):
            score = float(confidence)
            scores[index] = score
            points[index, 0] = float(x)
            points[index, 1] = float(y)
            points[index, 2] = 1.0 if score > 0 else 0.0
        return points, scores

    @staticmethod
    def _instance_score(
        keyframe: VideoTrackKeyframe,
        scores: NDArray[np.float64],
    ) -> float:
        if keyframe.confidence is not None:
            return float(keyframe.confidence)
        positive = scores[scores > 0]
        return float(positive.mean()) if positive.size else 0.0

    def _labels(self, video: VideoAsset, tracks: list[VideoTrack], schema: _PoseSchemaContext) -> Any:
        sio = self._sleap_io()
        managed_path = resolve_managed_project_path(self.settings, video.managed_path)
        if not managed_path.is_file():
            raise NotFoundError("Managed video file is missing")

        skeleton = sio.Skeleton(
            nodes=list(schema.external_node_names),
            name="ReefVision canonical pose",
        )
        sio_video = sio.Video.from_filename(str(managed_path), keep_open=False)

        external_tracks: dict[str, Any] = {}
        categories: dict[str, Any] = {}
        track_provenance: dict[str, dict[str, object]] = {}
        instances_by_frame: dict[int, list[Any]] = defaultdict(list)

        for track in tracks:
            external_name = f"reefvision-track-{track.track_number}-{track.id[:8]}"
            external_track = sio.Track(name=external_name)
            external_tracks[track.id] = external_track

            label_class = self.session.get(LabelClass, track.label_class_id)
            category_name = label_class.name if label_class is not None else track.label_class_id
            category = categories.get(category_name)
            if category is None:
                category = sio.Category(name=category_name)
                categories[category_name] = category

            track_provenance[external_name] = {
                "video_track_id": track.id,
                "track_number": track.track_number,
                "label_class_id": track.label_class_id,
                "source_model_id": track.source_model_id,
                "source_job_id": track.source_job_id,
                "revision": track.revision,
            }

            for raw_keyframe in track.keyframes_json:
                keyframe = VideoTrackKeyframe.model_validate(raw_keyframe)
                converted = self._keyframe_points(keyframe, schema)
                if converted is None:
                    continue
                points, point_scores = converted
                instance = sio.PredictedInstance.from_numpy(
                    points,
                    skeleton=skeleton,
                    point_scores=point_scores,
                    score=self._instance_score(keyframe, point_scores),
                    track=external_track,
                    tracking_score=None,
                    category=category,
                    category_score=keyframe.confidence,
                )
                instances_by_frame[keyframe.frame].append(instance)

        if not instances_by_frame:
            raise ValidationError("Canonical pose tracks do not contain exportable pose observations")

        labeled_frames = [
            sio.LabeledFrame(
                video=sio_video,
                frame_idx=frame_index,
                instances=instances_by_frame[frame_index],
            )
            for frame_index in sorted(instances_by_frame)
        ]

        provenance = {
            "reefvision_pose_interoperability": {
                "schema_version": "reefvision-pose-interoperability-0001",
                "source_video_id": video.id,
                "source_video_sha256": video.sha256,
                "source_filename": video.original_filename,
                "frame_index_base": 0,
                "coordinate_base": 0,
                "pose_schema": schema.schema_metadata,
                "node_mapping": list(schema.node_mapping),
                "tracks": track_provenance,
                "loss_policy": (
                    "External formats do not preserve the complete ReefVision immutable "
                    "association/correction audit trail; use the ReefVision pose audit JSON "
                    "for full provenance."
                ),
            }
        }
        return sio.Labels(
            labeled_frames=labeled_frames,
            videos=[sio_video],
            skeletons=[skeleton],
            tracks=list(external_tracks.values()),
            categories=list(categories.values()),
            provenance=provenance,
        )

    @staticmethod
    def _zip_directory(directory: Path) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in directory.rglob("*") if item.is_file()):
                archive.write(path, path.relative_to(directory).as_posix())
        return buffer.getvalue()

    @classmethod
    def _bundle_manifest(
        cls,
        labels: Any,
        exchange_format: PoseInteroperabilityFormat,
    ) -> dict[str, object]:
        provenance = cls._reefvision_provenance(labels)
        if provenance is None:
            raise ValidationError("Canonical ReefVision pose labels are missing provenance")
        frames: list[dict[str, object]] = []
        for labeled_frame in sorted(
            list(getattr(labels, "labeled_frames", []) or []),
            key=lambda item: int(getattr(item, "frame_idx", -1)),
        ):
            frame_index = int(getattr(labeled_frame, "frame_idx", -1))
            if frame_index < 0:
                raise ValidationError("Canonical ReefVision pose frame index is invalid")
            instances: list[dict[str, object]] = []
            for instance in list(getattr(labeled_frame, "instances", []) or []):
                track = getattr(instance, "track", None)
                track_name = (
                    str(getattr(track, "name", "") or "").strip()
                    if track is not None
                    else ""
                )
                instances.append(
                    {"external_track_name": track_name or None}
                )
            frames.append(
                {
                    "reefvision_frame_index": frame_index,
                    "instances": instances,
                }
            )
        return {
            "schema_version": "reefvision-pose-bundle-0001",
            "format": exchange_format,
            "reefvision_pose_interoperability": provenance,
            "frames": frames,
        }

    @staticmethod
    def _write_bundle_manifest(
        directory: Path,
        manifest: dict[str, object],
    ) -> None:
        (directory / POSE_BUNDLE_MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @classmethod
    def _read_bundle_manifest(
        cls,
        directory: Path,
        exchange_format: PoseInteroperabilityFormat,
    ) -> dict[str, object] | None:
        candidates = sorted(directory.rglob(POSE_BUNDLE_MANIFEST_FILENAME))
        if not candidates:
            return None
        if len(candidates) != 1:
            raise ValidationError("Pose interoperability bundle contains multiple manifests")
        try:
            raw = json.loads(candidates[0].read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Pose interoperability bundle manifest is invalid") from exc
        if not isinstance(raw, dict):
            raise ValidationError("Pose interoperability bundle manifest must be a JSON object")
        if raw.get("schema_version") != "reefvision-pose-bundle-0001":
            raise ValidationError("Unsupported ReefVision pose bundle manifest version")
        if raw.get("format") != exchange_format:
            raise ValidationError("Pose interoperability bundle format does not match the request")
        provenance = raw.get("reefvision_pose_interoperability")
        frames = raw.get("frames")
        if not isinstance(provenance, dict) or not isinstance(frames, list):
            raise ValidationError("Pose interoperability bundle manifest is incomplete")
        return cast(dict[str, object], raw)

    @classmethod
    def _inject_bundle_manifest(
        cls,
        labels: Any,
        manifest: dict[str, object] | None,
    ) -> Any:
        if manifest is None:
            return labels
        provenance = manifest.get("reefvision_pose_interoperability")
        frames = manifest.get("frames")
        if not isinstance(provenance, dict) or not isinstance(frames, list):
            raise ValidationError("Pose interoperability bundle manifest is malformed")
        merged = {str(key): value for key, value in provenance.items()}
        merged["reefvision_frame_manifest"] = frames
        raw_labels_provenance = getattr(labels, "provenance", None)
        if not isinstance(raw_labels_provenance, dict):
            raw_labels_provenance = {}
            labels.provenance = raw_labels_provenance
        raw_labels_provenance["reefvision_pose_interoperability"] = merged
        return labels

    @staticmethod
    def _reefvision_provenance(labels: Any) -> dict[str, object] | None:
        raw_provenance = getattr(labels, "provenance", None)
        if not isinstance(raw_provenance, dict):
            return None
        raw = raw_provenance.get("reefvision_pose_interoperability")
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValidationError("ReefVision pose provenance is malformed")
        return cast(dict[str, object], raw)

    @classmethod
    def _imported_schema(cls, labels: Any) -> _ImportedSchema:
        skeletons = list(getattr(labels, "skeletons", []) or [])
        if len(skeletons) != 1:
            raise ValidationError(
                "Pose interoperability import requires exactly one external skeleton"
            )
        external_node_names = tuple(
            str(item).strip() for item in getattr(skeletons[0], "node_names", [])
        )
        if not external_node_names or any(not item for item in external_node_names):
            raise ValidationError("External pose skeleton contains blank or missing node names")
        if len(external_node_names) != len(set(external_node_names)):
            raise ValidationError("External pose skeleton node names must be unique")

        provenance = cls._reefvision_provenance(labels)
        if provenance is None:
            return _ImportedSchema(
                groups=tuple(
                    {"name": node_name, "count": 1}
                    for node_name in external_node_names
                ),
                expanded_labels=external_node_names,
                external_node_names=external_node_names,
                used_reefvision_provenance=False,
                provenance=None,
            )

        raw_mapping = provenance.get("node_mapping")
        raw_schema = provenance.get("pose_schema")
        if not isinstance(raw_mapping, list) or not isinstance(raw_schema, dict):
            raise ValidationError("ReefVision pose provenance is missing schema mapping metadata")
        if len(raw_mapping) != len(external_node_names):
            raise ValidationError(
                "ReefVision pose provenance node mapping does not match the external skeleton"
            )

        expanded: list[str] = []
        for index, external_name in enumerate(external_node_names):
            mapping = raw_mapping[index]
            if not isinstance(mapping, dict):
                raise ValidationError("ReefVision pose provenance node mapping is malformed")
            if str(mapping.get("external_node_name") or "") != external_name:
                raise ValidationError(
                    "ReefVision pose provenance node order does not match the external skeleton"
                )
            semantic_label = str(mapping.get("semantic_label") or "").strip()
            if not semantic_label:
                raise ValidationError(
                    "ReefVision pose provenance contains a blank semantic landmark label"
                )
            expanded.append(semantic_label)

        raw_expanded = raw_schema.get("expanded_labels")
        if not isinstance(raw_expanded, list) or tuple(str(item) for item in raw_expanded) != tuple(
            expanded
        ):
            raise ValidationError(
                "ReefVision pose provenance semantic labels do not match its schema metadata"
            )

        raw_groups = raw_schema.get("groups")
        if not isinstance(raw_groups, list) or not raw_groups:
            raise ValidationError("ReefVision pose provenance is missing landmark groups")
        groups: list[dict[str, object]] = []
        reconstructed: list[str] = []
        seen_names: set[str] = set()
        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                raise ValidationError("ReefVision pose provenance landmark groups are malformed")
            name = str(raw_group.get("name") or "").strip()
            count_raw = raw_group.get("count")
            if (
                not name
                or name.casefold() in seen_names
                or not isinstance(count_raw, int)
                or isinstance(count_raw, bool)
                or count_raw < 1
            ):
                raise ValidationError("ReefVision pose provenance landmark groups are invalid")
            seen_names.add(name.casefold())
            groups.append({"name": name, "count": count_raw})
            reconstructed.extend([name] * count_raw)
        if tuple(reconstructed) != tuple(expanded):
            raise ValidationError(
                "ReefVision pose provenance groups do not reproduce the landmark order"
            )
        return _ImportedSchema(
            groups=tuple(groups),
            expanded_labels=tuple(expanded),
            external_node_names=external_node_names,
            used_reefvision_provenance=True,
            provenance=provenance,
        )

    @staticmethod
    def _validate_archive_member(name: str) -> Path:
        normalized = name.replace("\\", "/")
        candidate = Path(normalized)
        if (
            not normalized
            or normalized.startswith("/")
            or candidate.is_absolute()
            or ".." in candidate.parts
        ):
            raise ValidationError("Ultralytics pose ZIP contains an unsafe archive path")
        return candidate

    @classmethod
    def _extract_safe_zip(
        cls,
        content: bytes,
        destination: Path,
        *,
        label: str,
    ) -> None:
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise ValidationError(f"{label} requires a valid ZIP archive") from exc
        with archive:
            members = archive.infolist()
            if len(members) > 20000:
                raise ValidationError(f"{label} ZIP contains too many files")
            expanded_bytes = sum(item.file_size for item in members)
            if expanded_bytes > 512 * 1024 * 1024:
                raise ValidationError(f"{label} ZIP expands beyond 512 MiB")
            root = destination.resolve()
            for item in members:
                relative = cls._validate_archive_member(item.filename)
                target = (destination / relative).resolve()
                if root not in target.parents and target != root:
                    raise ValidationError(f"{label} ZIP escapes its extraction directory")
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as output:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)

    @classmethod
    def _extract_ultralytics_zip(cls, content: bytes, destination: Path) -> Path:
        cls._extract_safe_zip(
            content,
            destination,
            label="Ultralytics pose import",
        )
        manifests = sorted(destination.rglob("data.yaml"))
        if len(manifests) != 1:
            raise ValidationError(
                "Ultralytics pose ZIP must contain exactly one data.yaml manifest"
            )
        return manifests[0].parent

    @classmethod
    def _validate_coco_paths(cls, content: bytes) -> None:
        try:
            document = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("COCO pose import requires valid UTF-8 JSON") from exc
        if not isinstance(document, dict):
            raise ValidationError("COCO pose import requires a JSON object")
        images = document.get("images")
        if not isinstance(images, list):
            raise ValidationError("COCO pose import is missing its images array")
        for image in images:
            if not isinstance(image, dict):
                raise ValidationError("COCO pose import contains a malformed image record")
            filename = image.get("file_name")
            if not isinstance(filename, str) or not filename.strip():
                raise ValidationError("COCO pose image records require file_name")
            cls._validate_archive_member(filename)

    @staticmethod
    def _placeholder_image(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return
        Image.new("RGB", (1, 1), (0, 0, 0)).save(path)

    @classmethod
    def _prepare_coco_placeholders(cls, source: Path) -> None:
        try:
            document = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("COCO pose import requires valid UTF-8 JSON") from exc
        if not isinstance(document, dict):
            raise ValidationError("COCO pose import requires a JSON object")
        images = document.get("images")
        if not isinstance(images, list):
            raise ValidationError("COCO pose import is missing its images array")
        for image in images:
            if not isinstance(image, dict):
                raise ValidationError("COCO pose import contains a malformed image record")
            filename = image.get("file_name")
            if not isinstance(filename, str) or not filename.strip():
                raise ValidationError("COCO pose image records require file_name")
            relative = cls._validate_archive_member(filename)
            cls._placeholder_image(source.parent / relative)

    @classmethod
    def _prepare_dlc_placeholders(cls, source: Path) -> None:
        try:
            rows = list(csv.reader(source.read_text(encoding="utf-8-sig").splitlines()))
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            raise ValidationError("DeepLabCut pose import requires valid CSV") from exc
        image_rows = 0
        for row in rows:
            if not row:
                continue
            candidate = row[0].strip()
            lowered = candidate.casefold()
            if not candidate or not lowered.endswith(
                (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")
            ):
                continue
            relative = cls._validate_archive_member(candidate)
            cls._placeholder_image(source.parent / relative)
            image_rows += 1
        if image_rows == 0:
            raise ValidationError(
                "DeepLabCut pose CSV does not contain any image-index rows"
            )

    @staticmethod
    def _native_bundle_file(
        directory: Path,
        exchange_format: PoseInteroperabilityFormat,
    ) -> Path:
        suffixes: dict[PoseInteroperabilityFormat, tuple[str, ...]] = {
            "slp": (".slp",),
            "nwb": (".nwb",),
            "coco": (".json",),
            "dlc_csv": (".csv",),
            "ultralytics_pose": (".yaml",),
        }
        candidates = [
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path.name != POSE_BUNDLE_MANIFEST_FILENAME
            and path.name.casefold().endswith(suffixes[exchange_format])
        ]
        if exchange_format == "ultralytics_pose":
            candidates = [path for path in candidates if path.name == "data.yaml"]
        if len(candidates) != 1:
            raise ValidationError(
                "Pose interoperability bundle must contain exactly one native artifact"
            )
        return candidates[0]

    def _load_labels(
        self,
        exchange_format: PoseInteroperabilityFormat,
        content: bytes,
        source_filename: str | None,
    ) -> Any:
        sio = self._sleap_io()
        try:
            with TemporaryDirectory(prefix="reefvision-pose-import-") as temp:
                root = Path(temp)

                if exchange_format == "ultralytics_pose":
                    dataset_root = root / "dataset"
                    dataset_root.mkdir(parents=True, exist_ok=True)
                    actual_dataset_root = self._extract_ultralytics_zip(
                        content,
                        dataset_root,
                    )
                    manifest = self._read_bundle_manifest(
                        dataset_root,
                        exchange_format,
                    )
                    labels = sio.load_ultralytics(
                        str(actual_dataset_root),
                        split="train",
                    )
                    return self._inject_bundle_manifest(labels, manifest)

                suffixes: dict[PoseInteroperabilityFormat, str] = {
                    "slp": ".slp",
                    "nwb": ".nwb",
                    "coco": ".json",
                    "dlc_csv": ".csv",
                    "ultralytics_pose": ".zip",
                }
                manifest: dict[str, object] | None = None

                if exchange_format != "slp" and zipfile.is_zipfile(io.BytesIO(content)):
                    bundle_root = root / "bundle"
                    bundle_root.mkdir(parents=True, exist_ok=True)
                    self._extract_safe_zip(
                        content,
                        bundle_root,
                        label="Pose interoperability import",
                    )
                    manifest = self._read_bundle_manifest(
                        bundle_root,
                        exchange_format,
                    )
                    source = self._native_bundle_file(
                        bundle_root,
                        exchange_format,
                    )
                else:
                    filename = Path(
                        source_filename or f"pose{suffixes[exchange_format]}"
                    ).name
                    if not filename.casefold().endswith(suffixes[exchange_format]):
                        filename = f"pose{suffixes[exchange_format]}"
                    source = root / filename
                    source.write_bytes(content)

                if exchange_format == "slp":
                    labels = sio.load_slp(str(source), open_videos=False)
                elif exchange_format == "nwb":
                    labels = sio.load_nwb(str(source))
                elif exchange_format == "coco":
                    self._validate_coco_paths(source.read_bytes())
                    self._prepare_coco_placeholders(source)
                    labels = sio.load_coco(
                        str(source),
                        dataset_root=str(source.parent),
                    )
                elif exchange_format == "dlc_csv":
                    self._prepare_dlc_placeholders(source)
                    labels = sio.load_dlc(str(source), config=False)
                else:
                    raise ValidationError(
                        f"Unsupported pose interoperability format: {exchange_format}"
                    )
                return self._inject_bundle_manifest(labels, manifest)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(
                f"Could not parse {exchange_format} pose interoperability file: {exc}"
            ) from exc

    @staticmethod
    def _point_arrays(instance: Any, expected_count: int) -> tuple[
        NDArray[np.float64],
        NDArray[np.bool_],
        NDArray[np.float64],
    ]:
        raw_points = getattr(instance, "points", None)
        if raw_points is None:
            raise ValidationError("External pose instance is missing landmark points")
        try:
            xy = np.asarray(raw_points["xy"], dtype=np.float64)
            visible = np.asarray(raw_points["visible"], dtype=np.bool_)
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ValidationError("External pose point data is malformed") from exc
        if xy.shape != (expected_count, 2) or visible.shape != (expected_count,):
            raise ValidationError(
                "External pose point count does not match the imported landmark schema"
            )
        dtype_names = getattr(getattr(raw_points, "dtype", None), "names", None) or ()
        if "score" in dtype_names:
            try:
                scores = np.asarray(raw_points["score"], dtype=np.float64)
            except (IndexError, KeyError, TypeError, ValueError) as exc:
                raise ValidationError("External pose confidence data is malformed") from exc
        else:
            scores = np.where(visible, 1.0, 0.0).astype(np.float64)
        if scores.shape != (expected_count,):
            raise ValidationError(
                "External pose confidence count does not match the imported landmark schema"
            )
        return xy, visible, scores

    @staticmethod
    def _import_bbox(
        xy: NDArray[np.float64],
        video: VideoAsset,
    ) -> tuple[float, float, float, float] | None:
        finite = np.isfinite(xy).all(axis=1)
        if not bool(finite.any()):
            return None
        points = xy[finite]
        if (
            (points[:, 0] < 0).any()
            or (points[:, 1] < 0).any()
            or (points[:, 0] >= video.width_px).any()
            or (points[:, 1] >= video.height_px).any()
        ):
            raise ValidationError("External pose coordinates extend outside the target video")
        min_x = float(points[:, 0].min())
        min_y = float(points[:, 1].min())
        max_x = float(points[:, 0].max())
        max_y = float(points[:, 1].max())
        width = min(float(video.width_px) - min_x, max(1.0, max_x - min_x))
        height = min(float(video.height_px) - min_y, max(1.0, max_y - min_y))
        return min_x, min_y, width, height

    @classmethod
    def _import_keyframe(
        cls,
        *,
        instance: Any,
        frame_index: int,
        schema: _ImportedSchema,
        video: VideoAsset,
    ) -> VideoTrackKeyframe | None:
        xy, visible, scores = cls._point_arrays(instance, len(schema.expanded_labels))
        bbox = cls._import_bbox(xy, video)
        if bbox is None:
            return None
        observations: list[dict[str, object]] = []
        keypoints: list[tuple[float, float, float]] = []
        source = "model" if "score" in (
            getattr(getattr(getattr(instance, "points", None), "dtype", None), "names", None) or ()
        ) else "manual"
        for index, (semantic_label, occurrence_index) in enumerate(
            cls._slot_keys(schema.expanded_labels)
        ):
            x = float(xy[index, 0])
            y = float(xy[index, 1])
            score = float(scores[index]) if np.isfinite(scores[index]) else 0.0
            if score < 0 or score > 1:
                raise ValidationError("External pose landmark confidence must be between 0 and 1")
            finite = np.isfinite(x) and np.isfinite(y)
            if finite:
                status = "visible" if bool(visible[index]) else "occluded"
                keypoint_confidence = score if status == "visible" else 0.0
                keypoints.append((x, y, keypoint_confidence))
                observation_x = x
                observation_y = y
            else:
                status = "absent"
                keypoints.append((0.0, 0.0, 0.0))
                observation_x = 0.0
                observation_y = 0.0
            observations.append(
                {
                    "id": f"interop:{uuid4()}",
                    "semantic_label": semantic_label,
                    "occurrence_index": occurrence_index,
                    "x": observation_x,
                    "y": observation_y,
                    "confidence": score if score > 0 else None,
                    "status": status,
                    "source": source,
                }
            )

        raw_instance_score = getattr(instance, "score", None)
        instance_score: float | None = None
        if isinstance(raw_instance_score, (int, float)) and not isinstance(
            raw_instance_score, bool
        ):
            candidate_score = float(raw_instance_score)
            if np.isfinite(candidate_score):
                if candidate_score < 0 or candidate_score > 1:
                    raise ValidationError(
                        "External pose instance confidence must be between 0 and 1"
                    )
                instance_score = candidate_score

        return VideoTrackKeyframe.model_validate(
            {
                "frame": frame_index,
                "bbox": bbox,
                "confidence": instance_score,
                "keypoints": keypoints,
                "pose_observations": observations,
            }
        )

    @classmethod
    def _import_tracks_from_labels(
        cls,
        labels: Any,
        schema: _ImportedSchema,
        video: VideoAsset,
    ) -> tuple[list[_ImportedTrack], list[str]]:
        grouped: dict[tuple[str, int], list[VideoTrackKeyframe]] = defaultdict(list)
        names: dict[tuple[str, int], str | None] = {}
        seen_frames: dict[tuple[str, int], set[int]] = defaultdict(set)
        warnings: list[str] = []
        skipped_empty = 0

        labeled_frames = sorted(
            list(getattr(labels, "labeled_frames", []) or []),
            key=lambda item: int(getattr(item, "frame_idx", -1)),
        )
        external_videos = {
            id(getattr(labeled_frame, "video", None))
            for labeled_frame in labeled_frames
        }
        if len(external_videos) > 1:
            raise ValidationError(
                "Pose interoperability import cannot flatten multiple external videos "
                "into one ReefVision video"
            )
        for labeled_frame in labeled_frames:
            frame_index = int(getattr(labeled_frame, "frame_idx", -1))
            if frame_index < 0 or frame_index >= video.frame_count:
                raise ValidationError(
                    "External pose frame index extends outside the target video"
                )
            for instance_index, instance in enumerate(
                list(getattr(labeled_frame, "instances", []) or [])
            ):
                track = getattr(instance, "track", None)
                if track is None:
                    group_key = ("untracked", frame_index * 1000000 + instance_index)
                    external_name = None
                else:
                    group_key = ("tracked", id(track))
                    external_name = str(getattr(track, "name", "") or "").strip() or None
                if frame_index in seen_frames[group_key]:
                    raise ValidationError(
                        "External pose track contains multiple instances on the same frame"
                    )
                seen_frames[group_key].add(frame_index)
                keyframe = cls._import_keyframe(
                    instance=instance,
                    frame_index=frame_index,
                    schema=schema,
                    video=video,
                )
                if keyframe is None:
                    skipped_empty += 1
                    continue
                grouped[group_key].append(keyframe)
                names[group_key] = external_name

        imported: list[_ImportedTrack] = []
        for group_key, keyframes in grouped.items():
            if not keyframes:
                continue
            keyframes.sort(key=lambda item: item.frame)
            imported.append(
                _ImportedTrack(
                    external_track_name=names.get(group_key),
                    keyframes=tuple(keyframes),
                )
            )
        if not imported:
            raise ValidationError("External pose file contains no importable pose instances")
        if len(imported) > 10000:
            raise ValidationError("Pose interoperability import exceeds 10000 tracks")
        keyframe_count = sum(len(item.keyframes) for item in imported)
        if keyframe_count > 100000:
            raise ValidationError("Pose interoperability import exceeds 100000 keyframes")
        if skipped_empty:
            warnings.append(
                f"Skipped {skipped_empty} pose instances containing no finite landmark coordinates."
            )
        if any(item.external_track_name is None for item in imported):
            warnings.append(
                "Untracked external instances were imported as independent one-frame tracks; "
                "ReefVision did not infer temporal identity."
            )
        return imported, warnings

    @staticmethod
    def _schema_payload(imported_schema: _ImportedSchema) -> tuple[dict[str, object], str]:
        groups = [dict(item) for item in imported_schema.groups]
        expanded = list(imported_schema.expanded_labels)
        repeated = any(
            isinstance(item.get("count"), int)
            and not isinstance(item.get("count"), bool)
            and cast(int, item["count"]) > 1
            for item in groups
        )
        payload: dict[str, object] = {
            "schema_version": "pose-landmarks-0001",
            "groups": groups,
            "expanded_labels": expanded,
            "keypoint_count": len(expanded),
            "allows_repeated_labels": repeated,
        }
        content_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return payload, content_hash

    def _resolve_import_schema(
        self,
        video: VideoAsset,
        imported_schema: _ImportedSchema,
        exchange_format: PoseInteroperabilityFormat,
    ) -> dict[str, object]:
        payload, content_hash = self._schema_payload(imported_schema)
        existing = self.session.scalar(
            select(PoseLandmarkSchemaRevision)
            .join(
                PoseLandmarkSchema,
                PoseLandmarkSchema.id == PoseLandmarkSchemaRevision.schema_id,
            )
            .where(
                PoseLandmarkSchema.project_id == video.project_id,
                PoseLandmarkSchemaRevision.content_hash == content_hash,
            )
            .order_by(PoseLandmarkSchemaRevision.created_at, PoseLandmarkSchemaRevision.id)
        )
        if existing is None:
            schema = PoseLandmarkSchema(
                project_id=video.project_id,
                name=f"Imported {exchange_format} pose landmarks",
            )
            self.session.add(schema)
            self.session.flush()
            existing = PoseLandmarkSchemaRevision(
                schema_id=schema.id,
                revision=1,
                schema_version="pose-landmarks-0001",
                groups_json=[dict(item) for item in imported_schema.groups],
                expanded_labels_json=list(imported_schema.expanded_labels),
                keypoint_count=len(imported_schema.expanded_labels),
                allows_repeated_labels=bool(payload["allows_repeated_labels"]),
                content_hash=content_hash,
            )
            self.session.add(existing)
            self.session.flush()
        return {
            **payload,
            "schema_id": existing.schema_id,
            "schema_revision": existing.revision,
            "content_hash": content_hash,
        }

    @staticmethod
    def _verify_import_video_mapping(
        *,
        video: VideoAsset,
        imported_schema: _ImportedSchema,
        confirm_frame_mapping: bool,
    ) -> list[str]:
        provenance = imported_schema.provenance
        if provenance is not None:
            source_sha = str(provenance.get("source_video_sha256") or "").strip().casefold()
            if not source_sha:
                raise ValidationError(
                    "ReefVision pose provenance is missing its source video SHA-256"
                )
            if source_sha != video.sha256.casefold():
                raise ValidationError(
                    "ReefVision pose provenance source video does not match the target video"
                )
            return []
        if not confirm_frame_mapping:
            raise ValidationError(
                "External pose files without ReefVision video provenance require explicit "
                "confirmation that their frame indices correspond to the target video"
            )
        return [
            "External pose file had no ReefVision source-video provenance; frame mapping "
            "was accepted from the explicit user confirmation."
        ]

    def _reject_duplicate_reefvision_source_tracks(
        self,
        video: VideoAsset,
        imported_schema: _ImportedSchema,
    ) -> None:
        provenance = imported_schema.provenance
        if provenance is None or str(provenance.get("source_video_id") or "") != video.id:
            return
        raw_tracks = provenance.get("tracks")
        if not isinstance(raw_tracks, dict):
            return
        source_track_ids = {
            str(item.get("video_track_id") or "")
            for item in raw_tracks.values()
            if isinstance(item, dict) and str(item.get("video_track_id") or "")
        }
        if not source_track_ids:
            return
        existing = self.session.scalar(
            select(VideoTrack.id).where(
                VideoTrack.video_id == video.id,
                VideoTrack.id.in_(source_track_ids),
                VideoTrack.deleted_at.is_(None),
            )
        )
        if existing is not None:
            raise ValidationError(
                "This ReefVision pose export references tracks that are already present "
                "on the target video; import would create duplicate scientific records"
            )

    @staticmethod
    def _source_track_metadata(
        imported_schema: _ImportedSchema,
        external_track_name: str | None,
    ) -> dict[str, object] | None:
        if external_track_name is None or imported_schema.provenance is None:
            return None
        raw_tracks = imported_schema.provenance.get("tracks")
        if not isinstance(raw_tracks, dict):
            return None
        raw = raw_tracks.get(external_track_name)
        if not isinstance(raw, dict):
            return None
        return {str(key): value for key, value in raw.items()}

    def import_bytes(
        self,
        video_id: str,
        exchange_format: PoseInteroperabilityFormat,
        content: bytes,
        *,
        source_filename: str | None,
        label_class_id: str,
        confirm_frame_mapping: bool,
    ) -> PoseInteroperabilityImportResponse:
        if not content:
            raise ValidationError("Pose interoperability import file is empty")
        video = self._video(video_id)
        label_class = self.session.get(LabelClass, label_class_id)
        if (
            label_class is None
            or label_class.project_id != video.project_id
            or not label_class.is_active
        ):
            raise ValidationError(
                "Pose interoperability import requires an active label class "
                "from the target video's project"
            )

        labels = self._load_labels(exchange_format, content, source_filename)
        imported_schema = self._imported_schema(labels)
        warnings = self._verify_import_video_mapping(
            video=video,
            imported_schema=imported_schema,
            confirm_frame_mapping=confirm_frame_mapping,
        )
        self._reject_duplicate_reefvision_source_tracks(video, imported_schema)
        imported_tracks, track_warnings = self._import_tracks_from_labels(
            labels,
            imported_schema,
            video,
        )
        warnings.extend(track_warnings)
        if not imported_schema.used_reefvision_provenance:
            warnings.append(
                "External skeleton node names were imported as distinct semantic landmarks; "
                "repeated-label equivalence was not inferred."
            )

        try:
            schema_metadata = self._resolve_import_schema(
                video,
                imported_schema,
                exchange_format,
            )
            next_track_number = int(
                self.session.scalar(
                    select(func.max(VideoTrack.track_number)).where(
                        VideoTrack.video_id == video.id
                    )
                )
                or 0
            )
            created: list[VideoTrack] = []
            for offset, imported_track in enumerate(imported_tracks, start=1):
                track = VideoTrack(
                    video_id=video.id,
                    label_class_id=label_class.id,
                    track_number=next_track_number + offset,
                    geometry_kind="bbox",
                    keyframes_json=[
                        keyframe.model_dump(mode="json", exclude_none=True)
                        for keyframe in imported_track.keyframes
                    ],
                    interpolation="hold",
                    status="imported_review_required",
                    source_model_id=None,
                    source_job_id=None,
                    metadata_json={
                        "source": "pose_interoperability_import",
                        "pose_tracking": True,
                        "pose_landmark_schema": schema_metadata,
                        "pose_interoperability_import": {
                            "schema_version": "pose-interoperability-import-0001",
                            "format": exchange_format,
                            "source_filename": Path(source_filename or "pose").name,
                            "external_track_name": imported_track.external_track_name,
                            "source_reefvision_track": self._source_track_metadata(
                                imported_schema,
                                imported_track.external_track_name,
                            ),
                            "used_reefvision_provenance": (
                                imported_schema.used_reefvision_provenance
                            ),
                        },
                    },
                )
                self.session.add(track)
                created.append(track)
            self.session.commit()
            for track in created:
                self.session.refresh(track)
        except Exception:
            self.session.rollback()
            raise

        return PoseInteroperabilityImportResponse(
            video_id=video.id,
            format=exchange_format,
            created_track_ids=[track.id for track in created],
            track_count=len(created),
            keyframe_count=sum(len(track.keyframes_json) for track in created),
            pose_schema_id=cast(str, schema_metadata["schema_id"]),
            pose_schema_revision=cast(int, schema_metadata["schema_revision"]),
            used_reefvision_provenance=imported_schema.used_reefvision_provenance,
            warnings=warnings,
        )

    def export(
        self,
        video_id: str,
        exchange_format: PoseInteroperabilityFormat,
    ) -> PoseInteroperabilityArtifact:
        video = self._video(video_id)
        tracks = self._pose_tracks(video_id)
        schema = self._schema_context(tracks)
        labels = self._labels(video, tracks, schema)
        sio = self._sleap_io()
        stem = Path(video.original_filename).stem or "video"

        with TemporaryDirectory(prefix="reefvision-pose-export-") as temp:
            root = Path(temp)
            if exchange_format == "slp":
                output = root / f"{stem}.pose.slp"
                sio.save_slp(labels, str(output), embed=False, verbose=False)
                return PoseInteroperabilityArtifact(
                    filename=output.name,
                    media_type="application/octet-stream",
                    content=output.read_bytes(),
                    exchange_format=exchange_format,
                )

            if exchange_format == "nwb":
                output = root / f"{stem}.pose.nwb"
                sio.save_nwb(labels, output, nwb_format="predictions")
                return PoseInteroperabilityArtifact(
                    filename=output.name,
                    media_type="application/x-hdf5",
                    content=output.read_bytes(),
                    exchange_format=exchange_format,
                )

            if exchange_format == "coco":
                output = root / f"{stem}.pose.coco.json"
                sio.save_coco(labels, str(output), visibility_encoding="ternary")
                return PoseInteroperabilityArtifact(
                    filename=output.name,
                    media_type="application/json",
                    content=output.read_bytes(),
                    exchange_format=exchange_format,
                )

            if exchange_format == "dlc_csv":
                output = root / f"{stem}.pose.dlc.csv"
                sio.save_csv(
                    labels,
                    str(output),
                    format="dlc",
                    include_score=True,
                    scorer="ReefVision",
                    save_metadata=False,
                )
                return PoseInteroperabilityArtifact(
                    filename=output.name,
                    media_type="text/csv; charset=utf-8",
                    content=output.read_bytes(),
                    exchange_format=exchange_format,
                )

            if exchange_format == "ultralytics_pose":
                output_dir = root / f"{stem}-ultralytics-pose"
                sio.save_ultralytics(
                    labels,
                    str(output_dir),
                    split_ratios={"train": 1.0},
                    class_id=0,
                    verbose=False,
                    use_multiprocessing=False,
                )
                return PoseInteroperabilityArtifact(
                    filename=f"{stem}.pose.ultralytics.zip",
                    media_type="application/zip",
                    content=self._zip_directory(output_dir),
                    exchange_format=exchange_format,
                )

        raise ValidationError(f"Unsupported pose interoperability format: {exchange_format}")

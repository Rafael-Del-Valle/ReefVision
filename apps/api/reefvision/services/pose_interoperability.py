"""Loss-aware pose export through the optional SLEAP-IO interoperability runtime."""

from __future__ import annotations

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

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import LabelClass, VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.sleap_nn_provider import SLEAP_IO_SUPPORTED_VERSION
from reefvision.schemas.pose_interoperability import PoseInteroperabilityFormat
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
                observation = observations.get(key)
                if observation is None:
                    continue
                scores[index] = float(observation.confidence or 0.0)
                if observation.status in {"absent", "out_of_frame"}:
                    continue
                points[index, 0] = float(observation.x)
                points[index, 1] = float(observation.y)
                points[index, 2] = (
                    1.0 if observation.status in {"visible", "uncertain"} else 0.0
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

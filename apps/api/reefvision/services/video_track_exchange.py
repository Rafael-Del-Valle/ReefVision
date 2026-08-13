"""Transactional video-track export and import across ReefVision JSON, CSV, and MOT."""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import LabelClass, VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.video_track_exchange import (
    ReefVisionTrackExchangeItem,
    ReefVisionVideoTrackExchange,
    VideoTrackExchangeFormat,
    VideoTrackImportResponse,
)
from reefvision.schemas.videos import VideoTrackKeyframe


@dataclass(frozen=True)
class TrackExportPayload:
    filename: str
    media_type: str
    content: str


@dataclass(frozen=True)
class _ImportedTrack:
    label_class_id: str
    label_class_name: str
    interpolation: str
    status: str
    keyframes: list[VideoTrackKeyframe]
    original_track_id: str | None
    original_track_number: int | None
    original_source_model_id: str | None
    original_source_job_id: str | None
    metadata: dict[str, Any]


class VideoTrackExchangeService:
    MAX_TRACKS = 10_000
    MAX_OBSERVATIONS = 2_000_000
    JSON_SCHEMA_VERSION = "reefvision-video-tracks-0001"

    def __init__(self, session: Session) -> None:
        self.session = session

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _active_tracks(self, video_id: str) -> list[VideoTrack]:
        return list(
            self.session.scalars(
                select(VideoTrack)
                .where(
                    VideoTrack.video_id == video_id,
                    VideoTrack.deleted_at.is_(None),
                )
                .order_by(VideoTrack.track_number, VideoTrack.created_at, VideoTrack.id)
            )
        )

    def _project_classes(self, video: VideoAsset) -> list[LabelClass]:
        return list(
            self.session.scalars(
                select(LabelClass)
                .where(LabelClass.project_id == video.project_id)
                .order_by(LabelClass.display_order, LabelClass.class_index, LabelClass.id)
            )
        )

    @staticmethod
    def _keyframes(track: VideoTrack) -> list[VideoTrackKeyframe]:
        try:
            return [VideoTrackKeyframe.model_validate(item) for item in track.keyframes_json]
        except PydanticValidationError as exc:
            raise ValidationError(f"Stored track {track.id} has invalid keyframes") from exc

    @staticmethod
    def _float(value: float) -> str:
        return format(float(value), ".12g")

    @staticmethod
    def _confidence(value: float | None) -> str:
        return "" if value is None else format(float(value), ".12g")

    def export(
        self,
        video_id: str,
        exchange_format: VideoTrackExchangeFormat,
    ) -> TrackExportPayload:
        video = self._video(video_id)
        tracks = self._active_tracks(video_id)
        classes = {item.id: item for item in self._project_classes(video)}
        stem = video.original_filename.rsplit(".", 1)[0] or "video"

        if exchange_format == "reefvision_json":
            items: list[ReefVisionTrackExchangeItem] = []
            for track in tracks:
                label_class = classes.get(track.label_class_id)
                if label_class is None:
                    raise ValidationError(
                        f"Track {track.id} references a class outside the video project"
                    )
                items.append(
                    ReefVisionTrackExchangeItem(
                        original_track_id=track.id,
                        original_track_number=track.track_number,
                        label_class_id=track.label_class_id,
                        label_class_name=label_class.name,
                        geometry_kind="bbox",
                        interpolation=(
                            "hold" if track.interpolation == "hold" else "linear"
                        ),
                        status=track.status,
                        keyframes=self._keyframes(track),
                        original_source_model_id=track.source_model_id,
                        original_source_job_id=track.source_job_id,
                        metadata=dict(track.metadata_json or {}),
                    )
                )
            document = ReefVisionVideoTrackExchange(
                schema_version=self.JSON_SCHEMA_VERSION,
                source_video_id=video.id,
                source_video_sha256=video.sha256,
                source_filename=video.original_filename,
                width_px=video.width_px,
                height_px=video.height_px,
                frame_count=video.frame_count,
                fps=video.fps,
                tracks=items,
            )
            return TrackExportPayload(
                filename=f"{stem}-reefvision-tracks.json",
                media_type="application/json",
                content=f"{document.model_dump_json(indent=2)}\n",
            )

        if exchange_format == "reefvision_csv":
            output = io.StringIO(newline="")
            fieldnames = [
                "track_number",
                "frame",
                "label_class_id",
                "label_class_name",
                "x",
                "y",
                "width",
                "height",
                "confidence",
                "interpolation",
                "status",
                "source_track_id",
                "source_model_id",
                "source_job_id",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for track in tracks:
                label_class = classes.get(track.label_class_id)
                if label_class is None:
                    raise ValidationError(
                        f"Track {track.id} references a class outside the video project"
                    )
                for keyframe in self._keyframes(track):
                    x, y, width, height = keyframe.bbox
                    writer.writerow(
                        {
                            "track_number": track.track_number,
                            "frame": keyframe.frame,
                            "label_class_id": track.label_class_id,
                            "label_class_name": label_class.name,
                            "x": self._float(x),
                            "y": self._float(y),
                            "width": self._float(width),
                            "height": self._float(height),
                            "confidence": self._confidence(keyframe.confidence),
                            "interpolation": track.interpolation,
                            "status": track.status,
                            "source_track_id": track.id,
                            "source_model_id": track.source_model_id or "",
                            "source_job_id": track.source_job_id or "",
                        }
                    )
            return TrackExportPayload(
                filename=f"{stem}-reefvision-tracks.csv",
                media_type="text/csv",
                content=output.getvalue(),
            )

        if exchange_format == "mot_csv":
            output = io.StringIO(newline="")
            writer = csv.writer(output, lineterminator="\n")
            for track in tracks:
                for keyframe in self._keyframes(track):
                    x, y, width, height = keyframe.bbox
                    writer.writerow(
                        [
                            keyframe.frame + 1,
                            track.track_number,
                            self._float(x + 1.0),
                            self._float(y + 1.0),
                            self._float(width),
                            self._float(height),
                            (
                                self._float(keyframe.confidence)
                                if keyframe.confidence is not None
                                else "-1"
                            ),
                            -1,
                            -1,
                            -1,
                        ]
                    )
            return TrackExportPayload(
                filename=f"{stem}-mot.txt",
                media_type="text/plain",
                content=output.getvalue(),
            )

        raise ValidationError(f"Unsupported video-track exchange format: {exchange_format}")

    @staticmethod
    def _resolve_class(
        classes: list[LabelClass],
        label_class_id: str | None,
        label_class_name: str | None,
    ) -> LabelClass:
        by_id = {item.id: item for item in classes}
        if label_class_id and label_class_id in by_id:
            return by_id[label_class_id]
        if label_class_name:
            normalized = label_class_name.strip().casefold()
            matches = [item for item in classes if item.name.strip().casefold() == normalized]
            if len(matches) == 1:
                return matches[0]
        requested = label_class_name or label_class_id or "<missing>"
        raise ValidationError(
            f"Could not map imported track class {requested!r} to this video project"
        )

    @staticmethod
    def _validate_keyframes(
        video: VideoAsset,
        keyframes: list[VideoTrackKeyframe],
    ) -> None:
        if not keyframes:
            raise ValidationError("Imported tracks must contain at least one observation")
        frames = [item.frame for item in keyframes]
        if frames != sorted(frames) or len(frames) != len(set(frames)):
            raise ValidationError("Imported track frames must be unique and ascending")
        for item in keyframes:
            if item.frame >= video.frame_count:
                raise ValidationError(
                    f"Imported frame {item.frame} exceeds source video frame range"
                )
            x, y, width, height = item.bbox
            if x + width > video.width_px or y + height > video.height_px:
                raise ValidationError("Imported track box extends outside source video bounds")

    @classmethod
    def _enforce_limits(cls, tracks: list[_ImportedTrack]) -> None:
        if len(tracks) > cls.MAX_TRACKS:
            raise ValidationError(f"Track import exceeds {cls.MAX_TRACKS} tracks")
        observations = sum(len(track.keyframes) for track in tracks)
        if observations > cls.MAX_OBSERVATIONS:
            raise ValidationError(
                f"Track import exceeds {cls.MAX_OBSERVATIONS} observations"
            )

    def _parse_json(
        self,
        video: VideoAsset,
        content: str,
        classes: list[LabelClass],
    ) -> tuple[list[_ImportedTrack], list[str]]:
        try:
            raw = json.loads(content)
            document = ReefVisionVideoTrackExchange.model_validate(raw)
        except (json.JSONDecodeError, PydanticValidationError) as exc:
            raise ValidationError("Invalid ReefVision video-track JSON") from exc

        if document.width_px != video.width_px or document.height_px != video.height_px:
            raise ValidationError("Track JSON dimensions do not match the target video")
        if document.frame_count != video.frame_count:
            raise ValidationError("Track JSON frame count does not match the target video")

        warnings: list[str] = []
        if document.source_video_sha256 and document.source_video_sha256 != video.sha256:
            warnings.append(
                "Source video SHA-256 differs from the target video; dimensions and frame count matched."
            )
        if abs(document.fps - video.fps) > 1e-6:
            warnings.append(
                f"Source FPS {document.fps:.9g} differs from target FPS {video.fps:.9g}."
            )

        tracks: list[_ImportedTrack] = []
        for item in document.tracks:
            label_class = self._resolve_class(
                classes,
                item.label_class_id,
                item.label_class_name,
            )
            keyframes = list(item.keyframes)
            self._validate_keyframes(video, keyframes)
            tracks.append(
                _ImportedTrack(
                    label_class_id=label_class.id,
                    label_class_name=label_class.name,
                    interpolation=item.interpolation,
                    status=item.status,
                    keyframes=keyframes,
                    original_track_id=item.original_track_id,
                    original_track_number=item.original_track_number,
                    original_source_model_id=item.original_source_model_id,
                    original_source_job_id=item.original_source_job_id,
                    metadata=dict(item.metadata),
                )
            )
        return tracks, warnings

    @staticmethod
    def _required_csv_columns(reader: csv.DictReader[str], required: set[str]) -> None:
        fields = set(reader.fieldnames or [])
        missing = sorted(required - fields)
        if missing:
            raise ValidationError(
                "ReefVision track CSV is missing required columns: " + ", ".join(missing)
            )

    @staticmethod
    def _parse_int(value: str, field: str, row_number: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"Invalid integer {field!r} at CSV row {row_number}"
            ) from exc
        return parsed

    @staticmethod
    def _parse_float(value: str, field: str, row_number: int) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"Invalid number {field!r} at CSV row {row_number}"
            ) from exc
        return parsed

    def _parse_reefvision_csv(
        self,
        video: VideoAsset,
        content: str,
        classes: list[LabelClass],
    ) -> tuple[list[_ImportedTrack], list[str]]:
        reader = csv.DictReader(io.StringIO(content))
        self._required_csv_columns(
            reader,
            {
                "track_number",
                "frame",
                "label_class_id",
                "label_class_name",
                "x",
                "y",
                "width",
                "height",
                "confidence",
                "interpolation",
                "status",
                "source_track_id",
                "source_model_id",
                "source_job_id",
            },
        )
        grouped: dict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
        for row_number, raw_row in enumerate(reader, start=2):
            row = {key: value or "" for key, value in raw_row.items() if key is not None}
            source_track_id = row.get("source_track_id", "").strip()
            track_number = row.get("track_number", "").strip()
            group_key = source_track_id or f"track-number:{track_number}"
            grouped[group_key].append((row_number, row))

        tracks: list[_ImportedTrack] = []
        for group_key, rows in grouped.items():
            first_row_number, first = rows[0]
            label_class = self._resolve_class(
                classes,
                first.get("label_class_id", "").strip() or None,
                first.get("label_class_name", "").strip() or None,
            )
            interpolation = first.get("interpolation", "linear").strip() or "linear"
            if interpolation not in {"linear", "hold"}:
                raise ValidationError(
                    f"Unsupported interpolation at CSV row {first_row_number}: {interpolation}"
                )
            status = first.get("status", "verified").strip() or "verified"
            if len(status) > 30:
                raise ValidationError(f"Track status is too long at CSV row {first_row_number}")

            keyframes: list[VideoTrackKeyframe] = []
            for row_number, row in rows:
                current_class = self._resolve_class(
                    classes,
                    row.get("label_class_id", "").strip() or None,
                    row.get("label_class_name", "").strip() or None,
                )
                if current_class.id != label_class.id:
                    raise ValidationError(
                        f"Track {group_key} changes class at CSV row {row_number}"
                    )
                if (row.get("interpolation", "linear").strip() or "linear") != interpolation:
                    raise ValidationError(
                        f"Track {group_key} changes interpolation at CSV row {row_number}"
                    )
                if (row.get("status", "verified").strip() or "verified") != status:
                    raise ValidationError(
                        f"Track {group_key} changes status at CSV row {row_number}"
                    )
                confidence_text = row.get("confidence", "").strip()
                confidence = (
                    None
                    if not confidence_text
                    else self._parse_float(confidence_text, "confidence", row_number)
                )
                try:
                    keyframe = VideoTrackKeyframe(
                        frame=self._parse_int(row.get("frame", ""), "frame", row_number),
                        bbox=(
                            self._parse_float(row.get("x", ""), "x", row_number),
                            self._parse_float(row.get("y", ""), "y", row_number),
                            self._parse_float(row.get("width", ""), "width", row_number),
                            self._parse_float(row.get("height", ""), "height", row_number),
                        ),
                        confidence=confidence,
                    )
                except PydanticValidationError as exc:
                    raise ValidationError(
                        f"Invalid bounding box or confidence at CSV row {row_number}"
                    ) from exc
                keyframes.append(keyframe)
            keyframes.sort(key=lambda item: item.frame)
            self._validate_keyframes(video, keyframes)
            original_number_text = first.get("track_number", "").strip()
            original_number = (
                self._parse_int(original_number_text, "track_number", first_row_number)
                if original_number_text
                else None
            )
            tracks.append(
                _ImportedTrack(
                    label_class_id=label_class.id,
                    label_class_name=label_class.name,
                    interpolation=interpolation,
                    status=status,
                    keyframes=keyframes,
                    original_track_id=first.get("source_track_id", "").strip() or None,
                    original_track_number=original_number,
                    original_source_model_id=(
                        first.get("source_model_id", "").strip() or None
                    ),
                    original_source_job_id=first.get("source_job_id", "").strip() or None,
                    metadata={},
                )
            )
        return tracks, []

    def _parse_mot_csv(
        self,
        video: VideoAsset,
        content: str,
        classes: list[LabelClass],
        mot_label_class_id: str | None,
    ) -> tuple[list[_ImportedTrack], list[str]]:
        if not mot_label_class_id:
            raise ValidationError("MOT import requires mot_label_class_id")
        label_class = self._resolve_class(classes, mot_label_class_id, None)
        reader = csv.reader(io.StringIO(content))
        grouped: dict[int, list[VideoTrackKeyframe]] = defaultdict(list)
        for row_number, row in enumerate(reader, start=1):
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) < 6:
                raise ValidationError(
                    f"MOT row {row_number} requires at least 6 columns"
                )
            frame_1based = self._parse_int(row[0].strip(), "frame", row_number)
            track_number = self._parse_int(row[1].strip(), "track_id", row_number)
            if frame_1based < 1 or track_number < 1:
                raise ValidationError("MOT frames and track IDs must be 1-based positive integers")
            x_1based = self._parse_float(row[2].strip(), "bb_left", row_number)
            y_1based = self._parse_float(row[3].strip(), "bb_top", row_number)
            width = self._parse_float(row[4].strip(), "bb_width", row_number)
            height = self._parse_float(row[5].strip(), "bb_height", row_number)
            confidence: float | None = None
            if len(row) >= 7 and row[6].strip():
                parsed_confidence = self._parse_float(row[6].strip(), "confidence", row_number)
                if parsed_confidence >= 0:
                    confidence = parsed_confidence
            try:
                keyframe = VideoTrackKeyframe(
                    frame=frame_1based - 1,
                    bbox=(x_1based - 1.0, y_1based - 1.0, width, height),
                    confidence=confidence,
                )
            except PydanticValidationError as exc:
                raise ValidationError(f"Invalid MOT geometry at row {row_number}") from exc
            grouped[track_number].append(keyframe)

        tracks: list[_ImportedTrack] = []
        for original_number, keyframes in sorted(grouped.items()):
            keyframes.sort(key=lambda item: item.frame)
            self._validate_keyframes(video, keyframes)
            tracks.append(
                _ImportedTrack(
                    label_class_id=label_class.id,
                    label_class_name=label_class.name,
                    interpolation="linear",
                    status="draft",
                    keyframes=keyframes,
                    original_track_id=None,
                    original_track_number=original_number,
                    original_source_model_id=None,
                    original_source_job_id=None,
                    metadata={"mot_original_track_id": original_number},
                )
            )
        return tracks, [
            "MOT has no ReefVision class metadata; the requested class was applied to every imported track.",
            "MOT frame and left/top coordinates were converted from 1-based to ReefVision 0-based coordinates.",
            "MOT imports are created with draft status and no model/job foreign-key linkage.",
        ]

    def import_text(
        self,
        video_id: str,
        exchange_format: VideoTrackExchangeFormat,
        content: str,
        *,
        mot_label_class_id: str | None = None,
    ) -> VideoTrackImportResponse:
        video = self._video(video_id)
        classes = self._project_classes(video)
        if exchange_format == "reefvision_json":
            tracks, warnings = self._parse_json(video, content, classes)
        elif exchange_format == "reefvision_csv":
            tracks, warnings = self._parse_reefvision_csv(video, content, classes)
        elif exchange_format == "mot_csv":
            tracks, warnings = self._parse_mot_csv(
                video,
                content,
                classes,
                mot_label_class_id,
            )
        else:
            raise ValidationError(f"Unsupported video-track exchange format: {exchange_format}")

        self._enforce_limits(tracks)
        next_number = (
            int(
                self.session.scalar(
                    select(func.max(VideoTrack.track_number)).where(
                        VideoTrack.video_id == video_id
                    )
                )
                or 0
            )
            + 1
        )
        created: list[VideoTrack] = []
        try:
            for offset, imported in enumerate(tracks):
                metadata = dict(imported.metadata)
                metadata["exchange_import"] = {
                    "format": exchange_format,
                    "original_track_id": imported.original_track_id,
                    "original_track_number": imported.original_track_number,
                    "original_source_model_id": imported.original_source_model_id,
                    "original_source_job_id": imported.original_source_job_id,
                    "label_class_name": imported.label_class_name,
                }
                track = VideoTrack(
                    video_id=video_id,
                    label_class_id=imported.label_class_id,
                    track_number=next_number + offset,
                    geometry_kind="bbox",
                    keyframes_json=[
                        {
                            "frame": item.frame,
                            "bbox": list(item.bbox),
                            "confidence": item.confidence,
                        }
                        for item in imported.keyframes
                    ],
                    interpolation=imported.interpolation,
                    status=imported.status,
                    source_model_id=None,
                    source_job_id=None,
                    metadata_json=metadata,
                )
                self.session.add(track)
                created.append(track)
            if created:
                video.revision += 1
            self.session.flush()
            created_ids = [track.id for track in created]
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return VideoTrackImportResponse(
            schema_version="video-track-import-0001",
            video_id=video_id,
            format=exchange_format,
            created_track_ids=created_ids,
            track_count=len(created),
            observation_count=sum(len(track.keyframes) for track in tracks),
            warnings=warnings,
        )

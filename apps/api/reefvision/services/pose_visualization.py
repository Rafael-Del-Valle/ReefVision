"""Canonical pose heatmap, trajectory, and provider-visualization analytics."""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import pairwise
from math import hypot
from typing import Any, cast

from sqlalchemy.orm import Session

from reefvision.db.models import ModelRegistration, VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.pose_tracking import (
    PoseLandmarkAssociationDecisionResponse,
    PoseLandmarkObservationResponse,
)
from reefvision.schemas.pose_visualization import (
    PosePafAvailability,
    PoseProviderVisualizationCapabilities,
    PoseVisualizationCell,
    PoseVisualizationExportFormat,
    PoseVisualizationPoint,
    PoseVisualizationRequest,
    PoseVisualizationResponse,
    PoseVisualizationTrajectory,
)
from reefvision.schemas.videos import VideoTrackKeyframe
from reefvision.services.pose_temporal_tracking import PoseTemporalTrackingService


@dataclass(frozen=True)
class PoseVisualizationExportPayload:
    filename: str
    media_type: str
    content: str


@dataclass(frozen=True)
class _Sample:
    frame_index: int
    time_s: float
    semantic_label: str
    occurrence_index: int
    x_px: float
    y_px: float
    confidence: float | None
    visibility_state: str
    observation_source: str
    coordinate_kind: str
    landmark_track_id: str | None = None
    association_state: str | None = None
    verification_state: str | None = None


@dataclass
class _CellAccumulator:
    sample_count: int = 0
    observed_sample_count: int = 0
    predicted_sample_count: int = 0
    confidence_values: list[float] | None = None
    sampled_frames: set[int] | None = None
    landmark_track_ids: set[str] | None = None
    movement_segment_count: int = 0
    movement_distance_pixels: float = 0.0
    movement_duration_seconds: float = 0.0
    maximum_speed_pixels_per_second: float | None = None

    def __post_init__(self) -> None:
        self.confidence_values = []
        self.sampled_frames = set()
        self.landmark_track_ids = set()


class PoseVisualizationService:
    """Derive reproducible visualization data without mutating canonical pose records."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.temporal = PoseTemporalTrackingService(session)

    def _track(self, track_id: str) -> VideoTrack:
        track = self.session.get(VideoTrack, track_id)
        if track is None or track.deleted_at is not None:
            raise NotFoundError("Video track not found")
        return track

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        if video.width_px <= 0 or video.height_px <= 0 or video.fps <= 0:
            raise ValidationError(
                "Pose visualization requires valid source video dimensions and fps"
            )
        return video

    @staticmethod
    def _keyframes(track: VideoTrack) -> list[VideoTrackKeyframe]:
        try:
            return [
                VideoTrackKeyframe.model_validate(item) for item in list(track.keyframes_json or [])
            ]
        except ValueError as exc:
            raise ValidationError("Stored video track keyframes are invalid") from exc

    @staticmethod
    def _expanded_labels(track: VideoTrack) -> list[str]:
        metadata = dict(track.metadata_json or {})
        raw_schema = metadata.get("pose_landmark_schema")
        if not isinstance(raw_schema, dict):
            return []
        raw_labels = raw_schema.get("expanded_labels")
        if not isinstance(raw_labels, list):
            return []
        return [str(item) for item in raw_labels if isinstance(item, str) and item.strip()]

    @staticmethod
    def _cell_index(
        x: float,
        y: float,
        width: int,
        height: int,
        rows: int,
        columns: int,
    ) -> tuple[int, int]:
        column = min(columns - 1, max(0, int((x / width) * columns)))
        row = min(rows - 1, max(0, int((y / height) * rows)))
        return row, column

    @staticmethod
    def _validate_coordinate(sample: _Sample, video: VideoAsset) -> None:
        if (
            sample.x_px < 0
            or sample.y_px < 0
            or sample.x_px > video.width_px
            or sample.y_px > video.height_px
        ):
            raise ValidationError(
                "Canonical pose coordinates cannot extend outside source video bounds"
            )

    def _source_samples(
        self,
        track: VideoTrack,
        video: VideoAsset,
        payload: PoseVisualizationRequest,
        start_frame: int,
        end_frame: int,
    ) -> tuple[list[_Sample], int, int]:
        samples: list[_Sample] = []
        excluded_missing = 0
        excluded_filter = 0
        expanded_labels = self._expanded_labels(track)

        for keyframe in self._keyframes(track):
            if keyframe.frame < start_frame or keyframe.frame > end_frame:
                continue
            if keyframe.pose_observations is not None:
                for observation in keyframe.pose_observations:
                    status = observation.status
                    if status in {"absent", "out_of_frame"}:
                        excluded_missing += 1
                        continue
                    if status == "uncertain" and not payload.include_uncertain:
                        excluded_filter += 1
                        continue
                    if status == "occluded" and not payload.include_predicted:
                        excluded_filter += 1
                        continue
                    confidence = (
                        float(observation.confidence)
                        if observation.confidence is not None
                        else None
                    )
                    if payload.minimum_landmark_confidence is not None and (
                        confidence is None
                        or confidence < float(payload.minimum_landmark_confidence)
                    ):
                        excluded_filter += 1
                        continue
                    sample = _Sample(
                        frame_index=keyframe.frame,
                        time_s=keyframe.frame / video.fps,
                        semantic_label=observation.semantic_label,
                        occurrence_index=observation.occurrence_index,
                        x_px=float(observation.x),
                        y_px=float(observation.y),
                        confidence=confidence,
                        visibility_state=status,
                        observation_source=observation.source,
                        coordinate_kind="predicted" if status == "occluded" else "observed",
                    )
                    self._validate_coordinate(sample, video)
                    samples.append(sample)
                continue

            occurrence_counts: dict[str, int] = defaultdict(int)
            for index, point in enumerate(keyframe.keypoints or []):
                confidence = float(point[2])
                if confidence <= 0:
                    excluded_missing += 1
                    continue
                if payload.minimum_landmark_confidence is not None and confidence < float(
                    payload.minimum_landmark_confidence
                ):
                    excluded_filter += 1
                    continue
                semantic_label = (
                    expanded_labels[index]
                    if index < len(expanded_labels)
                    else f"landmark_{index + 1}"
                )
                occurrence_index = occurrence_counts[semantic_label]
                occurrence_counts[semantic_label] += 1
                sample = _Sample(
                    frame_index=keyframe.frame,
                    time_s=keyframe.frame / video.fps,
                    semantic_label=semantic_label,
                    occurrence_index=occurrence_index,
                    x_px=float(point[0]),
                    y_px=float(point[1]),
                    confidence=confidence,
                    visibility_state="visible",
                    observation_source=(
                        "model"
                        if track.source_model_id is not None or track.source_job_id is not None
                        else "manual"
                    ),
                    coordinate_kind="observed",
                )
                self._validate_coordinate(sample, video)
                samples.append(sample)

        samples.sort(
            key=lambda item: (
                item.frame_index,
                item.semantic_label.casefold(),
                item.occurrence_index,
            )
        )
        return samples, excluded_missing, excluded_filter

    def _identity_context(
        self,
        track: VideoTrack,
        samples: list[_Sample],
    ) -> tuple[
        list[_Sample],
        str,
        str | None,
        dict[str, tuple[str, str]],
        set[tuple[str, int]],
    ]:
        summary = self.temporal.summary(track.id)
        if not summary.observations:
            return (
                samples,
                "not_built",
                "Build temporal identities before interpreting trajectory or activity continuity.",
                {},
                set(),
            )

        latest_observations: dict[str, PoseLandmarkObservationResponse] = {}
        for observation in summary.observations:
            current_observation = latest_observations.get(observation.observation_series_id)
            if current_observation is None or observation.revision > current_observation.revision:
                latest_observations[observation.observation_series_id] = observation

        latest_created_at = max(item.created_at for item in latest_observations.values())
        if latest_created_at < track.updated_at:
            return (
                samples,
                "stale",
                "Temporal identities predate the current video-track revision; "
                "rebuild them before interpreting trajectories or activity.",
                {},
                set(),
            )

        latest_decisions: dict[str, PoseLandmarkAssociationDecisionResponse] = {}
        for decision in summary.association_decisions:
            current_decision = latest_decisions.get(decision.observation_id)
            if (
                current_decision is None
                or decision.decision_revision > current_decision.decision_revision
            ):
                latest_decisions[decision.observation_id] = decision

        identities: dict[tuple[int, str, int], tuple[str | None, str | None, str | None]] = {}
        for observation in latest_observations.values():
            latest_decision = latest_decisions.get(observation.id)
            landmark_track_id = None
            association_state = None
            verification_state = None
            if latest_decision is not None:
                association_state = latest_decision.association_state
                verification_state = latest_decision.verification_state
                if (
                    latest_decision.association_state in {"confirmed", "provisional"}
                    and latest_decision.selected_landmark_track_id is not None
                ):
                    landmark_track_id = latest_decision.selected_landmark_track_id
            identities[
                (
                    observation.frame_index,
                    observation.semantic_label,
                    observation.occurrence_index,
                )
            ] = (
                landmark_track_id,
                association_state,
                verification_state,
            )

        attached: list[_Sample] = []
        for sample in samples:
            identity = identities.get(
                (sample.frame_index, sample.semantic_label, sample.occurrence_index)
            )
            if identity is None:
                attached.append(sample)
                continue
            attached.append(
                replace(
                    sample,
                    landmark_track_id=identity[0],
                    association_state=identity[1],
                    verification_state=identity[2],
                )
            )

        track_context = {
            item.id: (item.semantic_label, item.lifecycle_state) for item in summary.landmark_tracks
        }
        identity_breaks = {
            (item.predecessor_landmark_track_id, item.break_after_frame)
            for item in summary.identity_breaks
        }
        return attached, "current", None, track_context, identity_breaks

    def _provider_capabilities(
        self,
        track: VideoTrack,
    ) -> PoseProviderVisualizationCapabilities:
        provider_name: str | None = None
        if track.source_model_id is not None:
            model = self.session.get(ModelRegistration, track.source_model_id)
            if model is not None:
                provider_name = model.provider_name

        keypoint_scores_persisted = any(
            (
                any(point[2] > 0 for point in keyframe.keypoints or [])
                or any(
                    observation.confidence is not None
                    for observation in keyframe.pose_observations or []
                )
            )
            for keyframe in self._keyframes(track)
        )
        if provider_name == "sleap_nn":
            reason = (
                "The current SLEAP-NN adapter persists canonical keypoint scores, "
                "but ReefVision does not retain native confidence-map or "
                "part-affinity-field tensors from inference."
            )
        elif provider_name == "ultralytics":
            reason = (
                "The Ultralytics adapter persists canonical keypoint scores when "
                "provided, but ReefVision does not retain native model heatmap or "
                "part-affinity-field tensors."
            )
        elif provider_name is not None:
            reason = (
                f"The {provider_name} adapter does not expose persisted raw pose "
                "visualization tensors through ReefVision."
            )
        else:
            reason = (
                "This track has no registered model provider; visualizations use "
                "only persisted canonical pose observations."
            )
        return PoseProviderVisualizationCapabilities(
            provider_name=provider_name,
            keypoint_scores_persisted=keypoint_scores_persisted,
            native_confidence_maps_persisted=False,
            part_affinity_fields_persisted=False,
            raw_tensor_export_available=False,
            reason=reason,
        )

    @staticmethod
    def _paf_availability(
        capabilities: PoseProviderVisualizationCapabilities,
    ) -> PosePafAvailability:
        return PosePafAvailability(
            available=capabilities.part_affinity_fields_persisted,
            provider_name=capabilities.provider_name,
            reason=(
                "A persisted raw part-affinity-field artifact is available."
                if capabilities.part_affinity_fields_persisted
                else capabilities.reason
            ),
        )

    def analyze(
        self,
        track_id: str,
        payload: PoseVisualizationRequest,
    ) -> PoseVisualizationResponse:
        track = self._track(track_id)
        video = self._video(track.video_id)
        start_frame = payload.start_frame if payload.start_frame is not None else 0
        end_frame = (
            payload.end_frame if payload.end_frame is not None else max(0, video.frame_count - 1)
        )
        if start_frame >= video.frame_count or end_frame >= video.frame_count:
            raise ValidationError("Pose visualization frame range cannot exceed the source video")

        samples, excluded_missing, excluded_filter = self._source_samples(
            track,
            video,
            payload,
            start_frame,
            end_frame,
        )
        (
            samples,
            identity_status,
            identity_warning,
            track_context,
            identity_breaks,
        ) = self._identity_context(track, samples)

        accumulators = [
            [_CellAccumulator() for _ in range(payload.grid_columns)]
            for _ in range(payload.grid_rows)
        ]
        sampled_frames: set[int] = set()
        observed_count = 0
        predicted_count = 0
        resolved_count = 0
        unresolved_count = 0

        for sample in samples:
            sampled_frames.add(sample.frame_index)
            row, column = self._cell_index(
                sample.x_px,
                sample.y_px,
                video.width_px,
                video.height_px,
                payload.grid_rows,
                payload.grid_columns,
            )
            cell = accumulators[row][column]
            cell.sample_count += 1
            cast(set[int], cell.sampled_frames).add(sample.frame_index)
            if sample.coordinate_kind == "predicted":
                cell.predicted_sample_count += 1
                predicted_count += 1
            else:
                cell.observed_sample_count += 1
                observed_count += 1
            if sample.confidence is not None:
                cast(list[float], cell.confidence_values).append(sample.confidence)
            if identity_status == "current":
                if sample.landmark_track_id is not None:
                    resolved_count += 1
                    cast(set[str], cell.landmark_track_ids).add(sample.landmark_track_id)
                else:
                    unresolved_count += 1

        by_identity: dict[str, list[_Sample]] = defaultdict(list)
        if identity_status == "current":
            for sample in samples:
                if sample.landmark_track_id is not None:
                    by_identity[sample.landmark_track_id].append(sample)

        trajectories: list[PoseVisualizationTrajectory] = []
        total_activity_segments = 0
        for landmark_track_id in sorted(by_identity):
            points = sorted(
                by_identity[landmark_track_id],
                key=lambda item: (item.frame_index, item.time_s),
            )
            path_length = 0.0
            evaluated_seconds = 0.0
            segment_count = 0
            for first, second in pairwise(points):
                if second.frame_index <= first.frame_index:
                    continue
                if any(
                    break_track_id == landmark_track_id
                    and first.frame_index <= break_after_frame < second.frame_index
                    for break_track_id, break_after_frame in identity_breaks
                ):
                    continue
                duration = second.time_s - first.time_s
                if duration <= 0:
                    continue
                distance = hypot(second.x_px - first.x_px, second.y_px - first.y_px)
                speed = distance / duration
                midpoint_x = (first.x_px + second.x_px) / 2.0
                midpoint_y = (first.y_px + second.y_px) / 2.0
                row, column = self._cell_index(
                    midpoint_x,
                    midpoint_y,
                    video.width_px,
                    video.height_px,
                    payload.grid_rows,
                    payload.grid_columns,
                )
                cell = accumulators[row][column]
                cell.movement_segment_count += 1
                cell.movement_distance_pixels += distance
                cell.movement_duration_seconds += duration
                cell.maximum_speed_pixels_per_second = (
                    speed
                    if cell.maximum_speed_pixels_per_second is None
                    else max(cell.maximum_speed_pixels_per_second, speed)
                )
                path_length += distance
                evaluated_seconds += duration
                segment_count += 1
                total_activity_segments += 1

            semantic_label, lifecycle_state = track_context.get(
                landmark_track_id,
                (points[0].semantic_label, "unknown"),
            )
            trajectories.append(
                PoseVisualizationTrajectory(
                    landmark_track_id=landmark_track_id,
                    semantic_label=semantic_label,
                    lifecycle_state=lifecycle_state,
                    points=[
                        PoseVisualizationPoint(
                            frame_index=item.frame_index,
                            time_s=item.time_s,
                            semantic_label=item.semantic_label,
                            occurrence_index=item.occurrence_index,
                            x_px=item.x_px,
                            y_px=item.y_px,
                            landmark_confidence=item.confidence,
                            visibility_state=item.visibility_state,
                            observation_source=item.observation_source,
                            coordinate_kind=cast(Any, item.coordinate_kind),
                            landmark_track_id=item.landmark_track_id,
                            association_state=item.association_state,
                            verification_state=item.verification_state,
                        )
                        for item in points
                    ],
                    path_length_pixels=path_length,
                    evaluated_seconds=evaluated_seconds,
                    movement_segment_count=segment_count,
                )
            )

        total_samples = len(samples)
        sampled_frame_count = len(sampled_frames)
        cell_width = video.width_px / payload.grid_columns
        cell_height = video.height_px / payload.grid_rows
        cells: list[PoseVisualizationCell] = []
        for row in range(payload.grid_rows):
            for column in range(payload.grid_columns):
                item = accumulators[row][column]
                confidences = cast(list[float], item.confidence_values)
                movement_speed = (
                    item.movement_distance_pixels / item.movement_duration_seconds
                    if item.movement_duration_seconds > 0
                    else None
                )
                cells.append(
                    PoseVisualizationCell(
                        row=row,
                        column=column,
                        x_min_pixels=column * cell_width,
                        y_min_pixels=row * cell_height,
                        x_max_pixels=(column + 1) * cell_width,
                        y_max_pixels=(row + 1) * cell_height,
                        sample_count=item.sample_count,
                        observed_sample_count=item.observed_sample_count,
                        predicted_sample_count=item.predicted_sample_count,
                        confidence_sample_count=len(confidences),
                        mean_landmark_confidence=(
                            sum(confidences) / len(confidences) if confidences else None
                        ),
                        sample_fraction=(
                            item.sample_count / total_samples if total_samples else 0.0
                        ),
                        occupied_sampled_frame_count=len(cast(set[int], item.sampled_frames)),
                        occupied_sampled_frame_fraction=(
                            len(cast(set[int], item.sampled_frames)) / sampled_frame_count
                            if sampled_frame_count
                            else 0.0
                        ),
                        unique_landmark_track_count=len(cast(set[str], item.landmark_track_ids)),
                        movement_segment_count=item.movement_segment_count,
                        movement_distance_pixels=item.movement_distance_pixels,
                        movement_duration_seconds=item.movement_duration_seconds,
                        mean_speed_pixels_per_second=movement_speed,
                        maximum_speed_pixels_per_second=(item.maximum_speed_pixels_per_second),
                    )
                )

        capabilities = self._provider_capabilities(track)
        return PoseVisualizationResponse(
            parent_video_track_id=track.id,
            source_track_revision=track.revision,
            video_id=video.id,
            video_width_pixels=video.width_px,
            video_height_pixels=video.height_px,
            fps=video.fps,
            start_frame=start_frame,
            end_frame=end_frame,
            grid_rows=payload.grid_rows,
            grid_columns=payload.grid_columns,
            predicted_coordinate_policy=(
                "include_occluded_predictions"
                if payload.include_predicted
                else "exclude_occluded_predictions"
            ),
            identity_status=cast(Any, identity_status),
            identity_warning=identity_warning,
            sampled_frame_count=sampled_frame_count,
            spatial_sample_count=total_samples,
            observed_sample_count=observed_count,
            predicted_sample_count=predicted_count,
            resolved_identity_sample_count=resolved_count,
            unresolved_identity_sample_count=unresolved_count,
            excluded_missing_coordinate_count=excluded_missing,
            excluded_filter_count=excluded_filter,
            activity_segment_count=total_activity_segments,
            cells=cells,
            trajectories=trajectories,
            provider_capabilities=capabilities,
            paf=self._paf_availability(capabilities),
        )

    def export(
        self,
        track_id: str,
        payload: PoseVisualizationRequest,
        export_format: PoseVisualizationExportFormat,
    ) -> PoseVisualizationExportPayload:
        result = self.analyze(track_id, payload)
        video = self._video(result.video_id)
        stem = video.original_filename.rsplit(".", 1)[0]
        request_payload = payload.model_dump(mode="json")
        provenance = {
            "export_schema_version": "reefvision-pose-visualization-export-0001",
            "visualization_schema_version": result.schema_version,
            "video_id": result.video_id,
            "parent_video_track_id": result.parent_video_track_id,
            "source_track_revision": result.source_track_revision,
            "coordinate_space": result.coordinate_space,
            "sampling_policy": result.sampling_policy,
            "identity_policy": result.identity_policy,
            "identity_status": result.identity_status,
            "request": request_payload,
            "provider_capabilities": result.provider_capabilities.model_dump(mode="json"),
            "paf": result.paf.model_dump(mode="json"),
        }

        if export_format == "json":
            document = {
                **provenance,
                "visualization": result.model_dump(mode="json"),
            }
            return PoseVisualizationExportPayload(
                filename=f"{stem}-pose-visualization.json",
                media_type="application/json",
                content=json.dumps(document, indent=2, sort_keys=True) + "\n",
            )

        if export_format == "cells_csv":
            output = io.StringIO(newline="")
            fieldnames = [
                "video_id",
                "parent_video_track_id",
                "source_track_revision",
                "start_frame",
                "end_frame",
                "grid_rows",
                "grid_columns",
                "include_predicted",
                "include_uncertain",
                "minimum_landmark_confidence",
                "identity_status",
                "row",
                "column",
                "x_min_pixels",
                "y_min_pixels",
                "x_max_pixels",
                "y_max_pixels",
                "sample_count",
                "observed_sample_count",
                "predicted_sample_count",
                "confidence_sample_count",
                "mean_landmark_confidence",
                "sample_fraction",
                "occupied_sampled_frame_count",
                "occupied_sampled_frame_fraction",
                "unique_landmark_track_count",
                "movement_segment_count",
                "movement_distance_pixels",
                "movement_duration_seconds",
                "mean_speed_pixels_per_second",
                "maximum_speed_pixels_per_second",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for cell in result.cells:
                writer.writerow(
                    {
                        "video_id": result.video_id,
                        "parent_video_track_id": result.parent_video_track_id,
                        "source_track_revision": result.source_track_revision,
                        "start_frame": result.start_frame,
                        "end_frame": result.end_frame,
                        "grid_rows": result.grid_rows,
                        "grid_columns": result.grid_columns,
                        "include_predicted": payload.include_predicted,
                        "include_uncertain": payload.include_uncertain,
                        "minimum_landmark_confidence": (
                            payload.minimum_landmark_confidence
                            if payload.minimum_landmark_confidence is not None
                            else ""
                        ),
                        "identity_status": result.identity_status,
                        **cell.model_dump(mode="json"),
                    }
                )
            return PoseVisualizationExportPayload(
                filename=f"{stem}-pose-visualization-cells.csv",
                media_type="text/csv",
                content=output.getvalue(),
            )

        if export_format != "trajectories_csv":
            raise ValidationError("Unsupported pose visualization export format")
        if result.identity_status != "current" or not result.trajectories:
            raise ValidationError(
                "Trajectory CSV export requires current temporal identities and "
                "at least one resolved landmark trajectory"
            )

        output = io.StringIO(newline="")
        fieldnames = [
            "video_id",
            "parent_video_track_id",
            "source_track_revision",
            "start_frame",
            "end_frame",
            "include_predicted",
            "include_uncertain",
            "minimum_landmark_confidence",
            "landmark_track_id",
            "semantic_label",
            "lifecycle_state",
            "trajectory_path_length_pixels",
            "trajectory_evaluated_seconds",
            "trajectory_movement_segment_count",
            "frame_index",
            "time_s",
            "occurrence_index",
            "x_px",
            "y_px",
            "landmark_confidence",
            "visibility_state",
            "observation_source",
            "coordinate_kind",
            "association_state",
            "verification_state",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for trajectory in result.trajectories:
            for point in trajectory.points:
                writer.writerow(
                    {
                        "video_id": result.video_id,
                        "parent_video_track_id": result.parent_video_track_id,
                        "source_track_revision": result.source_track_revision,
                        "start_frame": result.start_frame,
                        "end_frame": result.end_frame,
                        "include_predicted": payload.include_predicted,
                        "include_uncertain": payload.include_uncertain,
                        "minimum_landmark_confidence": (
                            payload.minimum_landmark_confidence
                            if payload.minimum_landmark_confidence is not None
                            else ""
                        ),
                        "landmark_track_id": trajectory.landmark_track_id,
                        "semantic_label": trajectory.semantic_label,
                        "lifecycle_state": trajectory.lifecycle_state,
                        "trajectory_path_length_pixels": trajectory.path_length_pixels,
                        "trajectory_evaluated_seconds": trajectory.evaluated_seconds,
                        "trajectory_movement_segment_count": (
                            trajectory.movement_segment_count
                        ),
                        "frame_index": point.frame_index,
                        "time_s": point.time_s,
                        "occurrence_index": point.occurrence_index,
                        "x_px": point.x_px,
                        "y_px": point.y_px,
                        "landmark_confidence": (
                            point.landmark_confidence
                            if point.landmark_confidence is not None
                            else ""
                        ),
                        "visibility_state": point.visibility_state,
                        "observation_source": point.observation_source,
                        "coordinate_kind": point.coordinate_kind,
                        "association_state": point.association_state or "",
                        "verification_state": point.verification_state or "",
                    }
                )
        return PoseVisualizationExportPayload(
            filename=f"{stem}-pose-visualization-trajectories.csv",
            media_type="text/csv",
            content=output.getvalue(),
        )

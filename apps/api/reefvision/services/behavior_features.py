"""Deterministic behavior feature extraction from canonical track and pose state."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from itertools import combinations, pairwise
from math import hypot, sqrt
from statistics import pstdev

from sqlalchemy.orm import Session

from reefvision.db.models import VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.behavior_features import (
    BehaviorFeatureQuality,
    BehaviorFeatureRequest,
    BehaviorFeatureSource,
    BehaviorFeatureValue,
    BehaviorFeatureVectorResponse,
)
from reefvision.schemas.pose_visualization import PoseVisualizationRequest
from reefvision.schemas.videos import VideoTrackKeyframe
from reefvision.services.pose_visualization import PoseVisualizationService
from reefvision.services.video_tracks import VideoTrackService

FEATURE_SET_VERSION = "reefvision-behavior-features-0001"


class BehaviorFeatureService:
    """Generate explicit scalar features without persisting a derived copy."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _track(self, track_id: str) -> VideoTrack:
        track = self.session.get(VideoTrack, track_id)
        if track is None or track.deleted_at is not None:
            raise NotFoundError("Video track not found")
        return track

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        if video.fps <= 0:
            raise ValidationError("Behavior features require a positive source-video fps")
        return video

    @staticmethod
    def _keyframes(track: VideoTrack) -> list[VideoTrackKeyframe]:
        frames = [
            VideoTrackKeyframe.model_validate(item)
            for item in list(track.keyframes_json or [])
        ]
        frames.sort(key=lambda item: item.frame)
        if not frames:
            raise ValidationError("Behavior features require a track with keyframes")
        return frames

    @staticmethod
    def _parameters_hash(payload: BehaviorFeatureRequest) -> str:
        document = {
            "feature_set_version": FEATURE_SET_VERSION,
            **payload.model_dump(mode="json"),
        }
        encoded = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _feature(
        name: str,
        value: float,
        unit: str,
        source: BehaviorFeatureSource,
        definition: str,
    ) -> BehaviorFeatureValue:
        return BehaviorFeatureValue(
            name=name,
            value=float(value),
            unit=unit,
            source=source,
            available=True,
            definition=definition,
        )

    @staticmethod
    def _missing_feature(
        name: str,
        unit: str,
        source: str,
        definition: str,
        reason: str,
    ) -> BehaviorFeatureValue:
        return BehaviorFeatureValue(
            name=name,
            value=None,
            unit=unit,
            source=source,
            available=False,
            definition=definition,
            missing_reason=reason,
        )

    @staticmethod
    def _pose_points(
        track: VideoTrack,
        payload: BehaviorFeatureRequest,
        start_frame: int,
        end_frame: int,
    ) -> dict[int, list[tuple[float, float, float | None, str]]]:
        points: dict[int, list[tuple[float, float, float | None, str]]] = defaultdict(list)
        for keyframe in BehaviorFeatureService._keyframes(track):
            if keyframe.frame < start_frame or keyframe.frame > end_frame:
                continue
            if keyframe.pose_observations:
                for observation in keyframe.pose_observations:
                    if observation.status in {"absent", "out_of_frame"}:
                        continue
                    if observation.status == "uncertain" and not payload.include_uncertain:
                        continue
                    coordinate_kind = "observed"
                    if observation.status == "occluded":
                        if not payload.include_predicted:
                            continue
                        coordinate_kind = "predicted"
                    confidence = (
                        float(observation.confidence)
                        if observation.confidence is not None
                        else None
                    )
                    if (
                        payload.minimum_landmark_confidence is not None
                        and (
                            confidence is None
                            or confidence < payload.minimum_landmark_confidence
                        )
                    ):
                        continue
                    points[keyframe.frame].append(
                        (
                            float(observation.x),
                            float(observation.y),
                            confidence,
                            coordinate_kind,
                        )
                    )
                continue

            for point in keyframe.keypoints or []:
                confidence = float(point[2])
                if confidence <= 0:
                    continue
                if (
                    payload.minimum_landmark_confidence is not None
                    and confidence < payload.minimum_landmark_confidence
                ):
                    continue
                points[keyframe.frame].append(
                    (float(point[0]), float(point[1]), confidence, "observed")
                )
        return dict(points)

    def extract(
        self,
        track_id: str,
        payload: BehaviorFeatureRequest,
    ) -> BehaviorFeatureVectorResponse:
        track = self._track(track_id)
        video = self._video(track.video_id)
        interpolation = VideoTrackService(self.session).interpolate(track.id)
        track_first = interpolation.frames[0].frame
        track_last = interpolation.frames[-1].frame
        start_frame = payload.start_frame if payload.start_frame is not None else track_first
        end_frame = payload.end_frame if payload.end_frame is not None else track_last
        if start_frame < track_first or end_frame > track_last:
            raise ValidationError(
                "Behavior feature frame range must stay within the selected track"
            )

        frames = [
            frame
            for frame in interpolation.frames
            if start_frame <= frame.frame <= end_frame
        ]
        if not frames:
            raise ValidationError("Behavior feature frame range contains no track samples")

        centers = [(frame.center_x, frame.center_y) for frame in frames]
        track_distances = [
            hypot(second[0] - first[0], second[1] - first[1])
            for first, second in pairwise(centers)
        ]
        track_path = sum(track_distances)
        track_displacement = hypot(
            centers[-1][0] - centers[0][0],
            centers[-1][1] - centers[0][1],
        )
        track_motion_seconds = (
            (frames[-1].frame - frames[0].frame) / video.fps
            if len(frames) > 1
            else 0.0
        )
        track_speeds = [distance * video.fps for distance in track_distances]
        bbox_areas = [float(frame.bbox[2] * frame.bbox[3]) for frame in frames]
        bbox_diagonals = [
            hypot(float(frame.bbox[2]), float(frame.bbox[3]))
            for frame in frames
        ]
        mean_bbox_area = sum(bbox_areas) / len(bbox_areas)
        mean_bbox_diagonal = sum(bbox_diagonals) / len(bbox_diagonals)
        bbox_area_cv = (
            pstdev(bbox_areas) / mean_bbox_area
            if len(bbox_areas) > 1 and mean_bbox_area > 0
            else 0.0
        )

        features: list[BehaviorFeatureValue] = [
            self._feature(
                "track.path_length_pixels",
                track_path,
                "pixels",
                "track_kinematics",
                "Cumulative center-point distance over configured track interpolation.",
            ),
            self._feature(
                "track.displacement_pixels",
                track_displacement,
                "pixels",
                "track_kinematics",
                "Euclidean distance between first and last track centers in the feature window.",
            ),
            self._feature(
                "track.mean_speed_pixels_per_second",
                track_path / track_motion_seconds if track_motion_seconds > 0 else 0.0,
                "pixels_per_second",
                "track_kinematics",
                "Track path length divided by elapsed time between first and last sampled frames.",
            ),
            self._feature(
                "track.maximum_speed_pixels_per_second",
                max(track_speeds, default=0.0),
                "pixels_per_second",
                "track_kinematics",
                "Maximum frame-to-frame center speed over configured interpolation.",
            ),
            self._feature(
                "track.mean_bbox_area_pixels_squared",
                mean_bbox_area,
                "pixels_squared",
                "track_kinematics",
                "Mean interpolated bounding-box area over the feature window.",
            ),
            self._feature(
                "track.bbox_area_coefficient_of_variation",
                bbox_area_cv,
                "ratio",
                "track_kinematics",
                "Population standard deviation of bounding-box area divided by mean area.",
            ),
            self._feature(
                "track.mean_bbox_diagonal_pixels",
                mean_bbox_diagonal,
                "pixels",
                "track_kinematics",
                "Mean interpolated bounding-box diagonal over the feature window.",
            ),
            self._feature(
                "track.path_length_per_mean_bbox_diagonal",
                track_path / mean_bbox_diagonal if mean_bbox_diagonal > 0 else 0.0,
                "ratio",
                "track_kinematics",
                "Cumulative track path normalized by mean parent bounding-box diagonal.",
            ),
        ]

        pose_request = PoseVisualizationRequest(
            grid_rows=1,
            grid_columns=1,
            start_frame=start_frame,
            end_frame=end_frame,
            include_predicted=payload.include_predicted,
            include_uncertain=payload.include_uncertain,
            minimum_landmark_confidence=payload.minimum_landmark_confidence,
        )
        pose = PoseVisualizationService(self.session).analyze(track.id, pose_request)
        pose_points = self._pose_points(track, payload, start_frame, end_frame)

        evaluated_frame_count = end_frame - start_frame + 1
        pose_frame_count = len(pose_points)
        pose_counts = [len(items) for items in pose_points.values()]
        confidence_values = [
            confidence
            for items in pose_points.values()
            for _x, _y, confidence, _kind in items
            if confidence is not None
        ]
        predicted_count = sum(
            1
            for items in pose_points.values()
            for _x, _y, _confidence, kind in items
            if kind == "predicted"
        )
        total_pose_points = sum(pose_counts)

        spreads: list[float] = []
        normalized_spreads: list[float] = []
        pairwise_distances: list[float] = []
        normalized_pairwise_distances: list[float] = []
        bbox_by_frame = {frame.frame: frame.bbox for frame in frames}
        for frame_index, items in pose_points.items():
            if not items:
                continue
            center_x = sum(item[0] for item in items) / len(items)
            center_y = sum(item[1] for item in items) / len(items)
            spread = sqrt(
                sum(
                    (item[0] - center_x) ** 2 + (item[1] - center_y) ** 2
                    for item in items
                )
                / len(items)
            )
            spreads.append(spread)
            bbox = bbox_by_frame.get(frame_index)
            diagonal = (
                hypot(float(bbox[2]), float(bbox[3]))
                if bbox is not None
                else 0.0
            )
            if diagonal > 0:
                normalized_spreads.append(spread / diagonal)
            for first, second in combinations(items, 2):
                distance = hypot(second[0] - first[0], second[1] - first[1])
                pairwise_distances.append(distance)
                if diagonal > 0:
                    normalized_pairwise_distances.append(distance / diagonal)

        features.extend(
            [
                self._feature(
                    "pose.frame_coverage_fraction",
                    pose_frame_count / evaluated_frame_count,
                    "ratio",
                    "pose_geometry",
                    "Fraction of evaluated source frames containing at least one included pose coordinate.",
                ),
                self._feature(
                    "pose.mean_landmarks_per_sampled_frame",
                    sum(pose_counts) / pose_frame_count if pose_frame_count else 0.0,
                    "count",
                    "pose_geometry",
                    "Mean included landmark count across pose-sampled frames.",
                ),
                self._feature(
                    "pose.predicted_coordinate_fraction",
                    predicted_count / total_pose_points if total_pose_points else 0.0,
                    "ratio",
                    "pose_geometry",
                    "Fraction of included pose coordinates marked as occlusion-predicted.",
                ),
            ]
        )

        if confidence_values:
            features.append(
                self._feature(
                    "pose.mean_landmark_confidence",
                    sum(confidence_values) / len(confidence_values),
                    "probability",
                    "pose_geometry",
                    "Mean persisted confidence across included landmarks that have confidence values.",
                )
            )
        else:
            features.append(
                self._missing_feature(
                    "pose.mean_landmark_confidence",
                    "probability",
                    "pose_geometry",
                    "Mean persisted confidence across included landmarks that have confidence values.",
                    "No included pose landmarks have persisted confidence values.",
                )
            )

        if spreads:
            features.extend(
                [
                    self._feature(
                        "pose.mean_spread_pixels",
                        sum(spreads) / len(spreads),
                        "pixels",
                        "pose_geometry",
                        "Mean per-frame RMS landmark distance from the pose centroid.",
                    ),
                    self._feature(
                        "pose.maximum_spread_pixels",
                        max(spreads),
                        "pixels",
                        "pose_geometry",
                        "Maximum per-frame RMS landmark distance from the pose centroid.",
                    ),
                ]
            )
        else:
            for name, definition in (
                (
                    "pose.mean_spread_pixels",
                    "Mean per-frame RMS landmark distance from the pose centroid.",
                ),
                (
                    "pose.maximum_spread_pixels",
                    "Maximum per-frame RMS landmark distance from the pose centroid.",
                ),
            ):
                features.append(
                    self._missing_feature(
                        name,
                        "pixels",
                        "pose_geometry",
                        definition,
                        "No included pose coordinates are available in the feature window.",
                    )
                )

        if normalized_spreads:
            features.append(
                self._feature(
                    "pose.mean_spread_per_bbox_diagonal",
                    sum(normalized_spreads) / len(normalized_spreads),
                    "ratio",
                    "pose_geometry",
                    "Mean pose spread divided by the parent bounding-box diagonal at the same frame.",
                )
            )
        else:
            features.append(
                self._missing_feature(
                    "pose.mean_spread_per_bbox_diagonal",
                    "ratio",
                    "pose_geometry",
                    "Mean pose spread divided by the parent bounding-box diagonal at the same frame.",
                    "No pose frame has both included coordinates and a positive bounding-box diagonal.",
                )
            )

        if pairwise_distances:
            features.extend(
                [
                    self._feature(
                        "pose.mean_pairwise_distance_pixels",
                        sum(pairwise_distances) / len(pairwise_distances),
                        "pixels",
                        "pose_geometry",
                        "Mean within-frame Euclidean distance across all included landmark pairs.",
                    ),
                    self._feature(
                        "pose.maximum_pairwise_distance_pixels",
                        max(pairwise_distances),
                        "pixels",
                        "pose_geometry",
                        "Maximum within-frame Euclidean distance across included landmark pairs.",
                    ),
                ]
            )
        else:
            for name, definition in (
                (
                    "pose.mean_pairwise_distance_pixels",
                    "Mean within-frame Euclidean distance across all included landmark pairs.",
                ),
                (
                    "pose.maximum_pairwise_distance_pixels",
                    "Maximum within-frame Euclidean distance across included landmark pairs.",
                ),
            ):
                features.append(
                    self._missing_feature(
                        name,
                        "pixels",
                        "pose_geometry",
                        definition,
                        "At least two included landmarks in the same frame are required.",
                    )
                )

        if normalized_pairwise_distances:
            features.append(
                self._feature(
                    "pose.mean_pairwise_distance_per_bbox_diagonal",
                    sum(normalized_pairwise_distances)
                    / len(normalized_pairwise_distances),
                    "ratio",
                    "pose_geometry",
                    "Mean within-frame landmark-pair distance normalized by parent bounding-box diagonal.",
                )
            )
        else:
            features.append(
                self._missing_feature(
                    "pose.mean_pairwise_distance_per_bbox_diagonal",
                    "ratio",
                    "pose_geometry",
                    "Mean within-frame landmark-pair distance normalized by parent bounding-box diagonal.",
                    "At least two included landmarks and a positive bounding-box diagonal are required.",
                )
            )

        identity_reason = (
            pose.identity_warning
            or "Persistent temporal pose identities have not been built for this track."
        )
        if pose.identity_status == "current":
            resolved_fraction = (
                pose.resolved_identity_sample_count / pose.spatial_sample_count
                if pose.spatial_sample_count
                else 0.0
            )
            total_identity_path = sum(
                trajectory.path_length_pixels for trajectory in pose.trajectories
            )
            total_identity_seconds = sum(
                trajectory.evaluated_seconds for trajectory in pose.trajectories
            )
            identity_speeds: list[float] = []
            for trajectory in pose.trajectories:
                for segment in trajectory.segments:
                    for first, second in pairwise(segment.points):
                        duration = second.time_s - first.time_s
                        if duration <= 0:
                            continue
                        identity_speeds.append(
                            hypot(
                                second.x_px - first.x_px,
                                second.y_px - first.y_px,
                            )
                            / duration
                        )
            features.extend(
                [
                    self._feature(
                        "pose.resolved_identity_fraction",
                        resolved_fraction,
                        "ratio",
                        "pose_identity",
                        "Fraction of included pose samples assigned to a current persistent landmark identity.",
                    ),
                    self._feature(
                        "pose.identity_path_length_pixels",
                        total_identity_path,
                        "pixels",
                        "pose_identity",
                        "Sum of continuity-safe persistent-landmark path lengths.",
                    ),
                    self._feature(
                        "pose.identity_mean_speed_pixels_per_second",
                        total_identity_path / total_identity_seconds
                        if total_identity_seconds > 0
                        else 0.0,
                        "pixels_per_second",
                        "pose_identity",
                        "Total continuity-safe persistent-landmark path divided by evaluated identity-motion time.",
                    ),
                    self._feature(
                        "pose.identity_maximum_speed_pixels_per_second",
                        max(identity_speeds, default=0.0),
                        "pixels_per_second",
                        "pose_identity",
                        "Maximum continuity-safe persistent-landmark segment speed.",
                    ),
                    self._feature(
                        "pose.identity_continuity_segment_count",
                        sum(len(trajectory.segments) for trajectory in pose.trajectories),
                        "count",
                        "pose_identity",
                        "Number of persistent-landmark continuity segments after gaps and breaks are applied.",
                    ),
                ]
            )
        else:
            for name, unit, definition in (
                (
                    "pose.resolved_identity_fraction",
                    "ratio",
                    "Fraction of included pose samples assigned to a current persistent landmark identity.",
                ),
                (
                    "pose.identity_path_length_pixels",
                    "pixels",
                    "Sum of continuity-safe persistent-landmark path lengths.",
                ),
                (
                    "pose.identity_mean_speed_pixels_per_second",
                    "pixels_per_second",
                    "Total continuity-safe persistent-landmark path divided by evaluated identity-motion time.",
                ),
                (
                    "pose.identity_maximum_speed_pixels_per_second",
                    "pixels_per_second",
                    "Maximum continuity-safe persistent-landmark segment speed.",
                ),
                (
                    "pose.identity_continuity_segment_count",
                    "count",
                    "Number of persistent-landmark continuity segments after gaps and breaks are applied.",
                ),
            ):
                features.append(
                    self._missing_feature(
                        name,
                        unit,
                        "pose_identity",
                        definition,
                        identity_reason,
                    )
                )

        return BehaviorFeatureVectorResponse(
            track_id=track.id,
            video_id=video.id,
            track_number=track.track_number,
            source_track_revision=track.revision,
            start_frame=start_frame,
            end_frame=end_frame,
            fps=video.fps,
            evaluated_seconds_inclusive=evaluated_frame_count / video.fps,
            predicted_coordinate_policy=pose.predicted_coordinate_policy,
            pose_identity_status=pose.identity_status,
            pose_identity_warning=pose.identity_warning,
            parameters_sha256=self._parameters_hash(payload),
            quality=BehaviorFeatureQuality(
                evaluated_frame_count=evaluated_frame_count,
                track_motion_interval_count=max(0, len(frames) - 1),
                pose_sampled_frame_count=pose.sampled_frame_count,
                pose_spatial_sample_count=pose.spatial_sample_count,
                pose_observed_sample_count=pose.observed_sample_count,
                pose_predicted_sample_count=pose.predicted_sample_count,
                pose_excluded_missing_coordinate_count=pose.excluded_missing_coordinate_count,
                pose_excluded_filter_count=pose.excluded_filter_count,
                pose_resolved_identity_sample_count=pose.resolved_identity_sample_count,
                pose_unresolved_identity_sample_count=pose.unresolved_identity_sample_count,
                pose_identity_movement_segment_count=pose.activity_segment_count,
                pose_identity_continuity_segment_count=sum(
                    len(trajectory.segments) for trajectory in pose.trajectories
                ),
            ),
            features=features,
        )

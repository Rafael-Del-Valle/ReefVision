"""Canonical temporal pose association, review, and export services."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from math import hypot
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    ModelRegistration,
    PoseLandmarkAssociationCandidate,
    PoseLandmarkAssociationDecision,
    PoseLandmarkCorrection,
    PoseLandmarkIdentityBreak,
    PoseLandmarkObservation,
    PoseLandmarkTrack,
    VideoAsset,
    VideoTrack,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.pose_tracking import (
    PoseAssociationCorrectionRequest,
    PoseIdentityBreakCreateRequest,
    PoseLandmarkAssociationDecisionResponse,
    PoseLandmarkCorrectionResponse,
    PoseLandmarkIdentityBreakResponse,
    PoseLandmarkObservationResponse,
    PoseLandmarkTrackResponse,
    PoseTemporalAssociationBuildRequest,
    PoseTemporalBuildResponse,
    PoseTemporalTrackSummaryResponse,
)
from reefvision.schemas.videos import VideoPoseObservation, VideoTrackKeyframe


ASSOCIATION_ALGORITHM = "reefvision-temporal-pose"
ASSOCIATION_ALGORITHM_VERSION = "0001"
AUDIT_SCHEMA_VERSION = "reefvision-pose-tracks-0001"


@dataclass(frozen=True)
class PoseTemporalExportPayload:
    filename: str
    media_type: str
    content: str


@dataclass
class _ActiveTrack:
    record: PoseLandmarkTrack
    observation_count: int
    last_frame: int
    last_x: float
    last_y: float
    previous_frame: int | None
    previous_x: float | None
    previous_y: float | None
    last_observation_id: str
    last_center_x: float
    last_center_y: float
    last_diagonal: float


@dataclass(frozen=True)
class _SourceObservation:
    frame_index: int
    time_s: float
    bbox: tuple[float, float, float, float]
    semantic_label: str
    occurrence_index: int
    x: float | None
    y: float | None
    confidence: float | None
    visibility_state: str
    observation_source: str


@dataclass(frozen=True)
class _CandidateCost:
    track_id: str
    total_cost: float
    motion_cost: float
    geometry_cost: float


def _parameters_hash(parameters: dict[str, object]) -> str:
    payload = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _minimum_cost_assignment(costs: list[list[float]]) -> list[tuple[int, int]]:
    """Hungarian assignment for a rectangular matrix where columns >= rows."""
    if not costs:
        return []
    row_count = len(costs)
    column_count = len(costs[0])
    if column_count < row_count or any(len(row) != column_count for row in costs):
        raise ValueError("Assignment matrix must be rectangular with columns >= rows")

    u = [0.0] * (row_count + 1)
    v = [0.0] * (column_count + 1)
    p = [0] * (column_count + 1)
    way = [0] * (column_count + 1)

    for i in range(1, row_count + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (column_count + 1)
        used = [False] * (column_count + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, column_count + 1):
                if used[j]:
                    continue
                current = costs[i0 - 1][j - 1] - u[i0] - v[j]
                if current < minv[j]:
                    minv[j] = current
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(column_count + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assignments: list[tuple[int, int]] = []
    for j in range(1, column_count + 1):
        if p[j] != 0:
            assignments.append((p[j] - 1, j - 1))
    assignments.sort()
    return assignments


class PoseTemporalTrackingService:
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
        return video

    @staticmethod
    def _keyframes(track: VideoTrack) -> list[VideoTrackKeyframe]:
        try:
            return [
                VideoTrackKeyframe.model_validate(item)
                for item in list(track.keyframes_json or [])
            ]
        except ValueError as exc:
            raise ValidationError("Stored video track keyframes are invalid") from exc

    def _schema_context(
        self,
        track: VideoTrack,
    ) -> tuple[str, int, list[str]]:
        if track.source_model_id is not None:
            model = self.session.get(ModelRegistration, track.source_model_id)
            if model is not None:
                schema = (model.metadata_json or {}).get("pose_landmark_schema")
                if isinstance(schema, dict):
                    version = str(schema.get("schema_version") or "pose-landmarks-0001")
                    labels = schema.get("expanded_labels")
                    if isinstance(labels, list) and labels and all(
                        isinstance(item, str) and item for item in labels
                    ):
                        return f"model:{model.id}:{version}", 1, [str(item) for item in labels]

        labels_by_slot: dict[int, str] = {}
        for keyframe in self._keyframes(track):
            for observation in keyframe.pose_observations or []:
                slot = observation.occurrence_index
                while slot in labels_by_slot and labels_by_slot[slot] != observation.semantic_label:
                    slot += 1
                labels_by_slot.setdefault(slot, observation.semantic_label)
        if labels_by_slot:
            labels = [labels_by_slot[index] for index in sorted(labels_by_slot)]
            return f"video-track:{track.id}:pose-landmarks-0001", 1, labels
        return f"video-track:{track.id}:pose-landmarks-0001", 1, []

    def _source_observations(
        self,
        track: VideoTrack,
        video: VideoAsset,
        expanded_labels: list[str],
    ) -> list[_SourceObservation]:
        source: list[_SourceObservation] = []
        for keyframe in self._keyframes(track):
            bbox = tuple(float(value) for value in keyframe.bbox)
            if keyframe.pose_observations:
                for observation in keyframe.pose_observations:
                    observed = observation.status in {"visible", "uncertain"}
                    predicted = observation.status == "occluded"
                    x = float(observation.x) if observed or predicted else None
                    y = float(observation.y) if observed or predicted else None
                    source.append(
                        _SourceObservation(
                            frame_index=keyframe.frame,
                            time_s=keyframe.frame / video.fps,
                            bbox=bbox,
                            semantic_label=observation.semantic_label,
                            occurrence_index=observation.occurrence_index,
                            x=x,
                            y=y,
                            confidence=(
                                float(observation.confidence)
                                if observation.confidence is not None
                                else None
                            ),
                            visibility_state=observation.status,
                            observation_source=observation.source,
                        )
                    )
                continue

            occurrence_counts: dict[str, int] = {}
            for index, point in enumerate(keyframe.keypoints or []):
                if index >= len(expanded_labels):
                    semantic_label = f"landmark_{index + 1}"
                else:
                    semantic_label = expanded_labels[index]
                occurrence_index = occurrence_counts.get(semantic_label, 0)
                occurrence_counts[semantic_label] = occurrence_index + 1
                confidence = float(point[2])
                if confidence <= 0:
                    continue
                source.append(
                    _SourceObservation(
                        frame_index=keyframe.frame,
                        time_s=keyframe.frame / video.fps,
                        bbox=bbox,
                        semantic_label=semantic_label,
                        occurrence_index=occurrence_index,
                        x=float(point[0]),
                        y=float(point[1]),
                        confidence=confidence,
                        visibility_state="visible",
                        observation_source=(
                            "model"
                            if track.source_model_id is not None or track.source_job_id is not None
                            else "manual"
                        ),
                    )
                )
        source.sort(
            key=lambda item: (
                item.frame_index,
                item.semantic_label.casefold(),
                item.occurrence_index,
            )
        )
        return source

    def _clear_existing(self, track_id: str) -> None:
        observation_ids = list(
            self.session.scalars(
                select(PoseLandmarkObservation.id).where(
                    PoseLandmarkObservation.parent_video_track_id == track_id
                )
            )
        )
        if observation_ids:
            decision_ids = list(
                self.session.scalars(
                    select(PoseLandmarkAssociationDecision.id).where(
                        PoseLandmarkAssociationDecision.observation_id.in_(observation_ids)
                    )
                )
            )
            if decision_ids:
                self.session.execute(
                    delete(PoseLandmarkAssociationCandidate).where(
                        PoseLandmarkAssociationCandidate.association_decision_id.in_(decision_ids)
                    )
                )
                self.session.execute(
                    delete(PoseLandmarkAssociationDecision).where(
                        PoseLandmarkAssociationDecision.id.in_(decision_ids)
                    )
                )
        self.session.execute(
            delete(PoseLandmarkIdentityBreak).where(
                PoseLandmarkIdentityBreak.parent_video_track_id == track_id
            )
        )
        self.session.execute(
            delete(PoseLandmarkCorrection).where(
                PoseLandmarkCorrection.parent_video_track_id == track_id
            )
        )
        self.session.execute(
            delete(PoseLandmarkObservation).where(
                PoseLandmarkObservation.parent_video_track_id == track_id
            )
        )
        self.session.execute(
            delete(PoseLandmarkTrack).where(
                PoseLandmarkTrack.parent_video_track_id == track_id
            )
        )
        self.session.flush()

    @staticmethod
    def _point_for_association(item: _SourceObservation) -> tuple[float, float] | None:
        if item.x is None or item.y is None:
            return None
        if item.visibility_state == "absent":
            return None
        return item.x, item.y

    @staticmethod
    def _bbox_geometry(
        bbox: tuple[float, float, float, float],
    ) -> tuple[float, float, float]:
        x, y, width, height = bbox
        return x + width / 2.0, y + height / 2.0, max(hypot(width, height), 1.0)

    @staticmethod
    def _candidate_cost(
        active: _ActiveTrack,
        source: _SourceObservation,
    ) -> _CandidateCost | None:
        point = PoseTemporalTrackingService._point_for_association(source)
        if point is None:
            return None
        current_x, current_y = point
        gap = source.frame_index - active.last_frame
        if gap <= 0:
            return None

        predicted_x = active.last_x
        predicted_y = active.last_y
        if (
            active.previous_frame is not None
            and active.previous_x is not None
            and active.previous_y is not None
            and active.last_frame > active.previous_frame
        ):
            span = active.last_frame - active.previous_frame
            vx = (active.last_x - active.previous_x) / span
            vy = (active.last_y - active.previous_y) / span
            predicted_x += vx * gap
            predicted_y += vy * gap

        center_x, center_y, diagonal = PoseTemporalTrackingService._bbox_geometry(source.bbox)
        motion_cost = hypot(current_x - predicted_x, current_y - predicted_y) / diagonal

        current_rel_x = (current_x - center_x) / diagonal
        current_rel_y = (current_y - center_y) / diagonal
        previous_rel_x = (active.last_x - active.last_center_x) / active.last_diagonal
        previous_rel_y = (active.last_y - active.last_center_y) / active.last_diagonal
        geometry_cost = hypot(
            current_rel_x - previous_rel_x,
            current_rel_y - previous_rel_y,
        )
        total_cost = 0.7 * motion_cost + 0.3 * geometry_cost
        return _CandidateCost(
            track_id=active.record.id,
            total_cost=total_cost,
            motion_cost=motion_cost,
            geometry_cost=geometry_cost,
        )

    def _terminate_expired(
        self,
        active_by_label: dict[str, dict[str, _ActiveTrack]],
        frame_index: int,
        max_gap_frames: int,
    ) -> int:
        break_count = 0
        for active_for_label in active_by_label.values():
            expired = [
                track_id
                for track_id, active in active_for_label.items()
                if frame_index - active.last_frame > max_gap_frames
            ]
            for track_id in expired:
                active = active_for_label.pop(track_id)
                active.record.lifecycle_state = "terminated"
                active.record.last_frame = active.last_frame
                active.record.terminated_at = utc_now()
                self.session.add(
                    PoseLandmarkIdentityBreak(
                        parent_video_track_id=active.record.parent_video_track_id,
                        predecessor_landmark_track_id=active.record.id,
                        successor_landmark_track_id=None,
                        break_after_frame=active.last_frame,
                        successor_start_frame=None,
                        reason="occlusion_gap_exceeded",
                        decision_confidence=None,
                        source="tracker",
                        human_verified=False,
                        correction_id=None,
                    )
                )
                break_count += 1
        return break_count

    def build(
        self,
        track_id: str,
        payload: PoseTemporalAssociationBuildRequest,
    ) -> PoseTemporalBuildResponse:
        track = self._track(track_id)
        video = self._video(track.video_id)
        existing = self.session.scalar(
            select(PoseLandmarkObservation.id).where(
                PoseLandmarkObservation.parent_video_track_id == track_id
            )
        )
        if existing is not None:
            if not payload.replace_existing:
                raise ConflictError(
                    "Temporal pose records already exist for this video track; "
                    "set replace_existing=true to rebuild them"
                )
            self._clear_existing(track_id)

        pose_schema_id, pose_schema_revision, expanded_labels = self._schema_context(track)
        source_observations = self._source_observations(track, video, expanded_labels)
        if not source_observations:
            raise ValidationError("Video track does not contain pose observations to associate")

        parameters: dict[str, object] = {
            "max_gap_frames": payload.max_gap_frames,
            "max_normalized_displacement": float(payload.max_normalized_displacement),
            "ambiguity_margin": float(payload.ambiguity_margin),
            "confirm_after_observations": payload.confirm_after_observations,
            "cost_weights": {"motion": 0.7, "parent_geometry": 0.3},
            "ambiguity_policy": "leave_unresolved",
            "occurrence_index_is_temporal_identity": False,
        }
        parameters_hash = _parameters_hash(parameters)
        active_by_label: dict[str, dict[str, _ActiveTrack]] = {}
        created_tracks = 0
        created_observations = 0
        created_decisions = 0
        unresolved = 0
        identity_breaks = 0

        frame_groups: dict[int, list[_SourceObservation]] = {}
        for item in source_observations:
            frame_groups.setdefault(item.frame_index, []).append(item)

        for frame_index in sorted(frame_groups):
            identity_breaks += self._terminate_expired(
                active_by_label,
                frame_index,
                payload.max_gap_frames,
            )
            grouped_by_label: dict[str, list[_SourceObservation]] = {}
            for item in frame_groups[frame_index]:
                grouped_by_label.setdefault(item.semantic_label, []).append(item)

            for semantic_label, frame_items in grouped_by_label.items():
                frame_items.sort(key=lambda item: item.occurrence_index)
                active_for_label = active_by_label.setdefault(semantic_label, {})
                eligible_active = [
                    active
                    for active in active_for_label.values()
                    if frame_index - active.last_frame <= payload.max_gap_frames
                ]
                eligible_active.sort(key=lambda item: item.record.id)

                observations: list[PoseLandmarkObservation] = []
                for item in frame_items:
                    point = self._point_for_association(item)
                    observed = item.visibility_state in {"visible", "uncertain"} and point is not None
                    predicted = item.visibility_state == "occluded" and point is not None
                    observation = PoseLandmarkObservation(
                        observation_series_id=str(uuid4()),
                        revision=1,
                        supersedes_observation_id=None,
                        parent_video_track_id=track.id,
                        frame_index=item.frame_index,
                        time_s=item.time_s,
                        pose_schema_id=pose_schema_id,
                        pose_schema_revision=pose_schema_revision,
                        semantic_label=item.semantic_label,
                        occurrence_index=item.occurrence_index,
                        observed_x_px=item.x if observed else None,
                        observed_y_px=item.y if observed else None,
                        predicted_x_px=item.x if predicted else None,
                        predicted_y_px=item.y if predicted else None,
                        landmark_confidence=item.confidence,
                        visibility_state=item.visibility_state,
                        observation_source=item.observation_source,
                        source_model_id=track.source_model_id,
                        source_job_id=track.source_job_id,
                    )
                    self.session.add(observation)
                    observations.append(observation)
                    created_observations += 1
                self.session.flush()

                assignable_rows = [
                    index
                    for index, item in enumerate(frame_items)
                    if self._point_for_association(item) is not None
                ]
                candidate_lists: dict[int, list[_CandidateCost]] = {}
                for index in assignable_rows:
                    candidates: list[_CandidateCost] = []
                    for active in eligible_active:
                        candidate = self._candidate_cost(active, frame_items[index])
                        if (
                            candidate is not None
                            and candidate.total_cost
                            <= float(payload.max_normalized_displacement)
                        ):
                            candidates.append(candidate)
                    candidates.sort(key=lambda item: (item.total_cost, item.track_id))
                    candidate_lists[index] = candidates

                assignment_by_row: dict[int, _CandidateCost] = {}
                if assignable_rows and eligible_active:
                    unmatched_cost = float(payload.max_normalized_displacement) + 1e-6
                    impossible_cost = unmatched_cost + 1000.0
                    matrix: list[list[float]] = []
                    for row_index in assignable_rows:
                        by_track = {
                            candidate.track_id: candidate
                            for candidate in candidate_lists[row_index]
                        }
                        row = [
                            by_track.get(active.record.id).total_cost
                            if active.record.id in by_track
                            else impossible_cost
                            for active in eligible_active
                        ]
                        row.extend(
                            unmatched_cost if dummy == len(matrix) else impossible_cost
                            for dummy in range(len(assignable_rows))
                        )
                        matrix.append(row)

                    for local_row, column in _minimum_cost_assignment(matrix):
                        source_index = assignable_rows[local_row]
                        if column >= len(eligible_active):
                            continue
                        active = eligible_active[column]
                        candidate = next(
                            (
                                item
                                for item in candidate_lists[source_index]
                                if item.track_id == active.record.id
                            ),
                            None,
                        )
                        if candidate is not None:
                            assignment_by_row[source_index] = candidate

                for index, (item, observation) in enumerate(
                    zip(frame_items, observations, strict=True)
                ):
                    point = self._point_for_association(item)
                    candidates = candidate_lists.get(index, [])
                    assigned = assignment_by_row.get(index)
                    margin = (
                        candidates[1].total_cost - candidates[0].total_cost
                        if len(candidates) >= 2
                        else None
                    )
                    ambiguous = (
                        assigned is not None
                        and margin is not None
                        and margin < float(payload.ambiguity_margin)
                    )

                    if point is None:
                        decision = PoseLandmarkAssociationDecision(
                            observation_id=observation.id,
                            decision_revision=1,
                            supersedes_decision_id=None,
                            selected_landmark_track_id=None,
                            previous_observation_id=None,
                            association_state="unresolved",
                            association_confidence=None,
                            verification_state="unreviewed",
                            association_source="tracker",
                            candidate_margin=None,
                            total_cost=None,
                            cost_breakdown_json=None,
                            algorithm=ASSOCIATION_ALGORITHM,
                            algorithm_version=ASSOCIATION_ALGORITHM_VERSION,
                            parameters_hash=parameters_hash,
                        )
                        self.session.add(decision)
                        unresolved += 1
                        created_decisions += 1
                        continue

                    if ambiguous:
                        decision = PoseLandmarkAssociationDecision(
                            observation_id=observation.id,
                            decision_revision=1,
                            supersedes_decision_id=None,
                            selected_landmark_track_id=None,
                            previous_observation_id=None,
                            association_state="unresolved",
                            association_confidence=None,
                            verification_state="unreviewed",
                            association_source="tracker",
                            candidate_margin=margin,
                            total_cost=assigned.total_cost if assigned is not None else None,
                            cost_breakdown_json=(
                                {
                                    "motion": assigned.motion_cost,
                                    "parent_geometry": assigned.geometry_cost,
                                }
                                if assigned is not None
                                else None
                            ),
                            algorithm=ASSOCIATION_ALGORITHM,
                            algorithm_version=ASSOCIATION_ALGORITHM_VERSION,
                            parameters_hash=parameters_hash,
                        )
                        self.session.add(decision)
                        self.session.flush()
                        for rank, candidate in enumerate(candidates, start=1):
                            confidence = max(
                                0.0,
                                1.0
                                - candidate.total_cost
                                / float(payload.max_normalized_displacement),
                            )
                            self.session.add(
                                PoseLandmarkAssociationCandidate(
                                    association_decision_id=decision.id,
                                    candidate_landmark_track_id=candidate.track_id,
                                    rank=rank,
                                    total_cost=candidate.total_cost,
                                    normalized_confidence=confidence,
                                    motion_cost=candidate.motion_cost,
                                    geometry_cost=candidate.geometry_cost,
                                    appearance_cost=None,
                                    ordering_cost=None,
                                    shape_cost=None,
                                )
                            )
                        unresolved += 1
                        created_decisions += 1
                        continue

                    if assigned is None:
                        landmark_track = PoseLandmarkTrack(
                            parent_video_track_id=track.id,
                            pose_schema_id=pose_schema_id,
                            pose_schema_revision=pose_schema_revision,
                            semantic_label=semantic_label,
                            lifecycle_state="tentative",
                            first_frame=frame_index,
                            last_frame=frame_index,
                            origin="tracker",
                            source_model_id=track.source_model_id,
                            source_job_id=track.source_job_id,
                            association_algorithm=ASSOCIATION_ALGORITHM,
                            association_algorithm_version=ASSOCIATION_ALGORITHM_VERSION,
                            association_parameters_json=parameters,
                            association_parameters_hash=parameters_hash,
                        )
                        self.session.add(landmark_track)
                        self.session.flush()
                        center_x, center_y, diagonal = self._bbox_geometry(item.bbox)
                        active = _ActiveTrack(
                            record=landmark_track,
                            observation_count=1,
                            last_frame=frame_index,
                            last_x=point[0],
                            last_y=point[1],
                            previous_frame=None,
                            previous_x=None,
                            previous_y=None,
                            last_observation_id=observation.id,
                            last_center_x=center_x,
                            last_center_y=center_y,
                            last_diagonal=diagonal,
                        )
                        active_for_label[landmark_track.id] = active
                        created_tracks += 1
                        decision = PoseLandmarkAssociationDecision(
                            observation_id=observation.id,
                            decision_revision=1,
                            supersedes_decision_id=None,
                            selected_landmark_track_id=landmark_track.id,
                            previous_observation_id=None,
                            association_state="provisional",
                            association_confidence=None,
                            verification_state="unreviewed",
                            association_source="tracker",
                            candidate_margin=None,
                            total_cost=None,
                            cost_breakdown_json=None,
                            algorithm=ASSOCIATION_ALGORITHM,
                            algorithm_version=ASSOCIATION_ALGORITHM_VERSION,
                            parameters_hash=parameters_hash,
                        )
                        self.session.add(decision)
                        created_decisions += 1
                        continue

                    active = active_for_label[assigned.track_id]
                    gap = max(1, frame_index - active.last_frame)
                    raw_confidence = max(
                        0.0,
                        1.0
                        - assigned.total_cost
                        / float(payload.max_normalized_displacement),
                    )
                    gap_penalty = 1.0 / (1.0 + 0.15 * max(0, gap - 1))
                    association_confidence = raw_confidence * gap_penalty
                    if item.visibility_state == "occluded":
                        association_confidence *= 0.75

                    active.previous_frame = active.last_frame
                    active.previous_x = active.last_x
                    active.previous_y = active.last_y
                    active.last_frame = frame_index
                    active.last_x = point[0]
                    active.last_y = point[1]
                    active.last_observation_id, previous_observation_id = (
                        observation.id,
                        active.last_observation_id,
                    )
                    active.observation_count += 1
                    center_x, center_y, diagonal = self._bbox_geometry(item.bbox)
                    active.last_center_x = center_x
                    active.last_center_y = center_y
                    active.last_diagonal = diagonal
                    active.record.last_frame = frame_index
                    if active.observation_count >= payload.confirm_after_observations:
                        active.record.lifecycle_state = "confirmed"

                    decision = PoseLandmarkAssociationDecision(
                        observation_id=observation.id,
                        decision_revision=1,
                        supersedes_decision_id=None,
                        selected_landmark_track_id=active.record.id,
                        previous_observation_id=previous_observation_id,
                        association_state=(
                            "confirmed"
                            if active.record.lifecycle_state == "confirmed"
                            else "provisional"
                        ),
                        association_confidence=association_confidence,
                        verification_state="unreviewed",
                        association_source="tracker",
                        candidate_margin=margin,
                        total_cost=assigned.total_cost,
                        cost_breakdown_json={
                            "motion": assigned.motion_cost,
                            "parent_geometry": assigned.geometry_cost,
                        },
                        algorithm=ASSOCIATION_ALGORITHM,
                        algorithm_version=ASSOCIATION_ALGORITHM_VERSION,
                        parameters_hash=parameters_hash,
                    )
                    self.session.add(decision)
                    self.session.flush()
                    for rank, candidate in enumerate(candidates, start=1):
                        confidence = max(
                            0.0,
                            1.0
                            - candidate.total_cost
                            / float(payload.max_normalized_displacement),
                        )
                        self.session.add(
                            PoseLandmarkAssociationCandidate(
                                association_decision_id=decision.id,
                                candidate_landmark_track_id=candidate.track_id,
                                rank=rank,
                                total_cost=candidate.total_cost,
                                normalized_confidence=confidence,
                                motion_cost=candidate.motion_cost,
                                geometry_cost=candidate.geometry_cost,
                                appearance_cost=None,
                                ordering_cost=None,
                                shape_cost=None,
                            )
                        )
                    created_decisions += 1

        self.session.commit()
        return PoseTemporalBuildResponse(
            parent_video_track_id=track.id,
            created_landmark_tracks=created_tracks,
            created_observations=created_observations,
            created_association_decisions=created_decisions,
            unresolved_associations=unresolved,
            identity_breaks=identity_breaks,
        )

    def summary(self, track_id: str) -> PoseTemporalTrackSummaryResponse:
        self._track(track_id)
        tracks = list(
            self.session.scalars(
                select(PoseLandmarkTrack)
                .where(PoseLandmarkTrack.parent_video_track_id == track_id)
                .order_by(
                    PoseLandmarkTrack.semantic_label,
                    PoseLandmarkTrack.first_frame,
                    PoseLandmarkTrack.id,
                )
            )
        )
        observations = list(
            self.session.scalars(
                select(PoseLandmarkObservation)
                .where(PoseLandmarkObservation.parent_video_track_id == track_id)
                .order_by(
                    PoseLandmarkObservation.frame_index,
                    PoseLandmarkObservation.semantic_label,
                    PoseLandmarkObservation.occurrence_index,
                    PoseLandmarkObservation.revision,
                )
            )
        )
        observation_ids = [item.id for item in observations]
        decisions = (
            list(
                self.session.scalars(
                    select(PoseLandmarkAssociationDecision)
                    .where(
                        PoseLandmarkAssociationDecision.observation_id.in_(observation_ids)
                    )
                    .order_by(
                        PoseLandmarkAssociationDecision.observation_id,
                        PoseLandmarkAssociationDecision.decision_revision,
                    )
                )
            )
            if observation_ids
            else []
        )
        breaks = list(
            self.session.scalars(
                select(PoseLandmarkIdentityBreak)
                .where(PoseLandmarkIdentityBreak.parent_video_track_id == track_id)
                .order_by(PoseLandmarkIdentityBreak.break_after_frame)
            )
        )
        corrections = list(
            self.session.scalars(
                select(PoseLandmarkCorrection)
                .where(PoseLandmarkCorrection.parent_video_track_id == track_id)
                .order_by(PoseLandmarkCorrection.created_at, PoseLandmarkCorrection.id)
            )
        )
        return PoseTemporalTrackSummaryResponse(
            parent_video_track_id=track_id,
            landmark_tracks=[
                PoseLandmarkTrackResponse.model_validate(item) for item in tracks
            ],
            observations=[
                PoseLandmarkObservationResponse.model_validate(item)
                for item in observations
            ],
            association_decisions=[
                PoseLandmarkAssociationDecisionResponse.model_validate(item)
                for item in decisions
            ],
            identity_breaks=[
                PoseLandmarkIdentityBreakResponse.model_validate(item) for item in breaks
            ],
            corrections=[
                PoseLandmarkCorrectionResponse.model_validate(item) for item in corrections
            ],
        )

    def correct_association(
        self,
        observation_id: str,
        payload: PoseAssociationCorrectionRequest,
    ) -> PoseLandmarkAssociationDecisionResponse:
        observation = self.session.get(PoseLandmarkObservation, observation_id)
        if observation is None:
            raise NotFoundError("Pose landmark observation not found")
        current = self.session.scalar(
            select(PoseLandmarkAssociationDecision)
            .where(PoseLandmarkAssociationDecision.observation_id == observation.id)
            .order_by(PoseLandmarkAssociationDecision.decision_revision.desc())
        )
        if current is None:
            raise NotFoundError("Pose landmark association decision not found")

        selected_track: PoseLandmarkTrack | None = None
        if payload.selected_landmark_track_id is not None:
            selected_track = self.session.get(
                PoseLandmarkTrack,
                payload.selected_landmark_track_id,
            )
            if selected_track is None:
                raise NotFoundError("Pose landmark track not found")
            if selected_track.parent_video_track_id != observation.parent_video_track_id:
                raise ValidationError("Landmark identity must belong to the same parent video track")
            if selected_track.semantic_label != observation.semantic_label:
                raise ValidationError("Landmark identity must use the same semantic label")
            if (
                selected_track.pose_schema_id != observation.pose_schema_id
                or selected_track.pose_schema_revision != observation.pose_schema_revision
            ):
                raise ValidationError("Landmark identity must use the same pose schema revision")

        before = {
            "selected_landmark_track_id": current.selected_landmark_track_id,
            "association_state": current.association_state,
            "association_confidence": current.association_confidence,
            "verification_state": current.verification_state,
        }
        after = {
            "selected_landmark_track_id": payload.selected_landmark_track_id,
            "association_state": payload.association_state,
        }
        unchanged_identity = (
            current.selected_landmark_track_id == payload.selected_landmark_track_id
            and current.association_state == payload.association_state
        )
        correction = PoseLandmarkCorrection(
            parent_video_track_id=observation.parent_video_track_id,
            action="confirm_identity" if unchanged_identity else "reassign_identity",
            target_type="association",
            target_id=current.id,
            frame_start=observation.frame_index,
            frame_end=observation.frame_index,
            reason_code=payload.reason_code,
            note=payload.note,
            before_json=before,
            after_json=after,
            actor="local_user",
        )
        self.session.add(correction)
        self.session.flush()

        decision = PoseLandmarkAssociationDecision(
            observation_id=observation.id,
            decision_revision=current.decision_revision + 1,
            supersedes_decision_id=current.id,
            selected_landmark_track_id=payload.selected_landmark_track_id,
            previous_observation_id=current.previous_observation_id,
            association_state=payload.association_state,
            association_confidence=current.association_confidence,
            verification_state=(
                "human_confirmed" if unchanged_identity else "human_corrected"
            ),
            association_source="human",
            candidate_margin=current.candidate_margin,
            total_cost=current.total_cost,
            cost_breakdown_json=current.cost_breakdown_json,
            algorithm=current.algorithm,
            algorithm_version=current.algorithm_version,
            parameters_hash=current.parameters_hash,
        )
        self.session.add(decision)
        self.session.commit()
        self.session.refresh(decision)
        return PoseLandmarkAssociationDecisionResponse.model_validate(decision)

    def create_identity_break(
        self,
        landmark_track_id: str,
        payload: PoseIdentityBreakCreateRequest,
    ) -> PoseLandmarkIdentityBreakResponse:
        predecessor = self.session.get(PoseLandmarkTrack, landmark_track_id)
        if predecessor is None:
            raise NotFoundError("Pose landmark track not found")
        successor: PoseLandmarkTrack | None = None
        if payload.successor_landmark_track_id is not None:
            successor = self.session.get(
                PoseLandmarkTrack,
                payload.successor_landmark_track_id,
            )
            if successor is None:
                raise NotFoundError("Successor pose landmark track not found")
            if successor.parent_video_track_id != predecessor.parent_video_track_id:
                raise ValidationError("Successor identity must belong to the same parent track")
            if successor.semantic_label != predecessor.semantic_label:
                raise ValidationError("Successor identity must use the same semantic label")
            if (
                successor.pose_schema_id != predecessor.pose_schema_id
                or successor.pose_schema_revision != predecessor.pose_schema_revision
            ):
                raise ValidationError("Successor identity must use the same pose schema revision")

        correction = PoseLandmarkCorrection(
            parent_video_track_id=predecessor.parent_video_track_id,
            action="break_identity",
            target_type="landmark_track",
            target_id=predecessor.id,
            frame_start=payload.break_after_frame,
            frame_end=payload.successor_start_frame,
            reason_code=payload.reason,
            note=payload.note,
            before_json={
                "lifecycle_state": predecessor.lifecycle_state,
                "last_frame": predecessor.last_frame,
            },
            after_json={
                "lifecycle_state": "terminated",
                "last_frame": payload.break_after_frame,
                "successor_landmark_track_id": payload.successor_landmark_track_id,
            },
            actor="local_user",
        )
        self.session.add(correction)
        self.session.flush()
        identity_break = PoseLandmarkIdentityBreak(
            parent_video_track_id=predecessor.parent_video_track_id,
            predecessor_landmark_track_id=predecessor.id,
            successor_landmark_track_id=payload.successor_landmark_track_id,
            break_after_frame=payload.break_after_frame,
            successor_start_frame=payload.successor_start_frame,
            reason=payload.reason,
            decision_confidence=(
                float(payload.decision_confidence)
                if payload.decision_confidence is not None
                else None
            ),
            source="human",
            human_verified=True,
            correction_id=correction.id,
        )
        predecessor.lifecycle_state = "terminated"
        predecessor.last_frame = payload.break_after_frame
        predecessor.terminated_at = utc_now()
        self.session.add(identity_break)
        self.session.commit()
        self.session.refresh(identity_break)
        return PoseLandmarkIdentityBreakResponse.model_validate(identity_break)

    def _latest_decisions(
        self,
        observation_ids: list[str],
    ) -> dict[str, PoseLandmarkAssociationDecision]:
        if not observation_ids:
            return {}
        decisions = list(
            self.session.scalars(
                select(PoseLandmarkAssociationDecision)
                .where(PoseLandmarkAssociationDecision.observation_id.in_(observation_ids))
                .order_by(
                    PoseLandmarkAssociationDecision.observation_id,
                    PoseLandmarkAssociationDecision.decision_revision,
                )
            )
        )
        latest: dict[str, PoseLandmarkAssociationDecision] = {}
        for decision in decisions:
            latest[decision.observation_id] = decision
        return latest

    def export(
        self,
        track_id: str,
        export_format: str,
    ) -> PoseTemporalExportPayload:
        track = self._track(track_id)
        video = self._video(track.video_id)
        summary = self.summary(track_id)
        if not summary.observations:
            raise ValidationError("No canonical temporal pose observations are available to export")

        if export_format == "json":
            decision_ids = [item.id for item in summary.association_decisions]
            candidates = (
                list(
                    self.session.scalars(
                        select(PoseLandmarkAssociationCandidate)
                        .where(
                            PoseLandmarkAssociationCandidate.association_decision_id.in_(
                                decision_ids
                            )
                        )
                        .order_by(
                            PoseLandmarkAssociationCandidate.association_decision_id,
                            PoseLandmarkAssociationCandidate.rank,
                        )
                    )
                )
                if decision_ids
                else []
            )
            document = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "video_id": video.id,
                "video_filename": video.original_filename,
                "parent_video_track_id": track.id,
                "landmark_tracks": [
                    item.model_dump(mode="json") for item in summary.landmark_tracks
                ],
                "observations": [
                    item.model_dump(mode="json") for item in summary.observations
                ],
                "association_decisions": [
                    item.model_dump(mode="json") for item in summary.association_decisions
                ],
                "association_candidates": [
                    {
                        "id": item.id,
                        "association_decision_id": item.association_decision_id,
                        "candidate_landmark_track_id": item.candidate_landmark_track_id,
                        "rank": item.rank,
                        "total_cost": item.total_cost,
                        "normalized_confidence": item.normalized_confidence,
                        "motion_cost": item.motion_cost,
                        "geometry_cost": item.geometry_cost,
                        "appearance_cost": item.appearance_cost,
                        "ordering_cost": item.ordering_cost,
                        "shape_cost": item.shape_cost,
                    }
                    for item in candidates
                ],
                "identity_breaks": [
                    item.model_dump(mode="json") for item in summary.identity_breaks
                ],
                "human_corrections": [
                    item.model_dump(mode="json") for item in summary.corrections
                ],
            }
            return PoseTemporalExportPayload(
                filename=f"{video.original_filename.rsplit('.', 1)[0]}-pose-tracks.json",
                media_type="application/json",
                content=json.dumps(document, indent=2, sort_keys=True) + "\n",
            )

        if export_format != "csv":
            raise ValidationError("Unsupported temporal pose export format")

        observations = list(
            self.session.scalars(
                select(PoseLandmarkObservation)
                .where(PoseLandmarkObservation.parent_video_track_id == track.id)
                .order_by(
                    PoseLandmarkObservation.frame_index,
                    PoseLandmarkObservation.semantic_label,
                    PoseLandmarkObservation.occurrence_index,
                    PoseLandmarkObservation.revision,
                )
            )
        )
        latest_observations: dict[str, PoseLandmarkObservation] = {}
        for observation in observations:
            latest_observations[observation.observation_series_id] = observation
        effective_observations = list(latest_observations.values())
        effective_observations.sort(
            key=lambda item: (
                item.frame_index,
                item.semantic_label.casefold(),
                item.occurrence_index,
            )
        )
        latest_decisions = self._latest_decisions(
            [item.id for item in effective_observations]
        )
        breaks = summary.identity_breaks
        break_before = {
            (item.successor_landmark_track_id, item.successor_start_frame)
            for item in breaks
            if item.successor_landmark_track_id is not None
            and item.successor_start_frame is not None
        }
        break_after = {
            (item.predecessor_landmark_track_id, item.break_after_frame)
            for item in breaks
        }
        corrected_observation_ids = {
            item.observation_id
            for item in summary.association_decisions
            if item.verification_state in {"human_confirmed", "human_corrected"}
        }

        output = io.StringIO(newline="")
        fieldnames = [
            "video_id",
            "video_filename",
            "frame_index",
            "time_s",
            "parent_track_id",
            "pose_schema_id",
            "pose_schema_revision",
            "semantic_label",
            "occurrence_index",
            "landmark_track_id",
            "observed_x_px",
            "observed_y_px",
            "predicted_x_px",
            "predicted_y_px",
            "visibility_state",
            "landmark_confidence",
            "association_state",
            "association_confidence",
            "verification_state",
            "observation_source",
            "association_source",
            "observation_revision",
            "association_revision",
            "identity_break_before",
            "identity_break_after",
            "source_model_id",
            "source_job_id",
            "association_algorithm",
            "association_algorithm_version",
            "association_parameters_hash",
            "human_corrected",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for observation in effective_observations:
            decision = latest_decisions.get(observation.id)
            selected_track_id = (
                decision.selected_landmark_track_id if decision is not None else None
            )
            writer.writerow(
                {
                    "video_id": video.id,
                    "video_filename": video.original_filename,
                    "frame_index": observation.frame_index,
                    "time_s": observation.time_s,
                    "parent_track_id": track.id,
                    "pose_schema_id": observation.pose_schema_id,
                    "pose_schema_revision": observation.pose_schema_revision,
                    "semantic_label": observation.semantic_label,
                    "occurrence_index": observation.occurrence_index,
                    "landmark_track_id": selected_track_id or "",
                    "observed_x_px": (
                        observation.observed_x_px
                        if observation.observed_x_px is not None
                        else ""
                    ),
                    "observed_y_px": (
                        observation.observed_y_px
                        if observation.observed_y_px is not None
                        else ""
                    ),
                    "predicted_x_px": (
                        observation.predicted_x_px
                        if observation.predicted_x_px is not None
                        else ""
                    ),
                    "predicted_y_px": (
                        observation.predicted_y_px
                        if observation.predicted_y_px is not None
                        else ""
                    ),
                    "visibility_state": observation.visibility_state,
                    "landmark_confidence": (
                        observation.landmark_confidence
                        if observation.landmark_confidence is not None
                        else ""
                    ),
                    "association_state": (
                        decision.association_state if decision is not None else ""
                    ),
                    "association_confidence": (
                        decision.association_confidence
                        if decision is not None
                        and decision.association_confidence is not None
                        else ""
                    ),
                    "verification_state": (
                        decision.verification_state if decision is not None else ""
                    ),
                    "observation_source": observation.observation_source,
                    "association_source": (
                        decision.association_source if decision is not None else ""
                    ),
                    "observation_revision": observation.revision,
                    "association_revision": (
                        decision.decision_revision if decision is not None else ""
                    ),
                    "identity_break_before": (
                        selected_track_id,
                        observation.frame_index,
                    )
                    in break_before,
                    "identity_break_after": (
                        selected_track_id,
                        observation.frame_index,
                    )
                    in break_after,
                    "source_model_id": observation.source_model_id or "",
                    "source_job_id": observation.source_job_id or "",
                    "association_algorithm": (
                        decision.algorithm if decision is not None and decision.algorithm else ""
                    ),
                    "association_algorithm_version": (
                        decision.algorithm_version
                        if decision is not None and decision.algorithm_version
                        else ""
                    ),
                    "association_parameters_hash": (
                        decision.parameters_hash
                        if decision is not None and decision.parameters_hash
                        else ""
                    ),
                    "human_corrected": observation.id in corrected_observation_ids,
                }
            )

        return PoseTemporalExportPayload(
            filename=f"{video.original_filename.rsplit('.', 1)[0]}-pose-tracks.csv",
            media_type="text/csv",
            content=output.getvalue(),
        )

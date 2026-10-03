"""Persistent ethograms and deterministic behavior-dynamics analytics."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    BehaviorBoutRevision,
    BehaviorEthogramRevision,
    BehaviorStateDefinition,
    Project,
    VideoAsset,
    VideoTrack,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.behavior_dynamics import (
    BehaviorBoutCreateRequest,
    BehaviorBoutResponse,
    BehaviorChannelDynamics,
    BehaviorDynamicsRequest,
    BehaviorDynamicsResponse,
    BehaviorEthogramCreateRequest,
    BehaviorEthogramResponse,
    BehaviorStateDefinitionResponse,
    BehaviorStateDynamics,
    BehaviorTransitionDynamics,
)


class BehaviorDynamicsService:
    """Canonical behavior annotation and state-transition analytics."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None or project.archived_at is not None:
            raise NotFoundError("Project not found")
        return project

    def _track(self, track_id: str) -> VideoTrack:
        track = self.session.get(VideoTrack, track_id)
        if track is None or track.deleted_at is not None:
            raise NotFoundError("Video track not found")
        return track

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        if video.fps <= 0 or video.frame_count <= 0:
            raise ValidationError("Behavior dynamics require valid video fps and frame count")
        return video

    def _ethogram(self, ethogram_revision_id: str) -> BehaviorEthogramRevision:
        record = self.session.get(BehaviorEthogramRevision, ethogram_revision_id)
        if record is None:
            raise NotFoundError("Behavior ethogram revision not found")
        return record

    def _state(self, state_id: str) -> BehaviorStateDefinition:
        state = self.session.get(BehaviorStateDefinition, state_id)
        if state is None:
            raise NotFoundError("Behavior state not found")
        return state

    @staticmethod
    def _definition_hash(payload: BehaviorEthogramCreateRequest) -> str:
        document = {
            "name": payload.name.strip(),
            "description": payload.description,
            "states": [
                {
                    "code": item.code.strip(),
                    "label": item.label.strip(),
                    "channel": item.channel.strip(),
                    "description": item.description,
                    "sort_order": index,
                }
                for index, item in enumerate(payload.states)
            ],
        }
        encoded = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def create_ethogram(
        self,
        project_id: str,
        payload: BehaviorEthogramCreateRequest,
    ) -> BehaviorEthogramResponse:
        self._project(project_id)
        ethogram = BehaviorEthogramRevision(
            ethogram_series_id=str(uuid4()),
            project_id=project_id,
            revision=1,
            supersedes_revision_id=None,
            name=payload.name.strip(),
            description=payload.description,
            definition_sha256=self._definition_hash(payload),
            created_by="local_user",
        )
        self.session.add(ethogram)
        self.session.flush()
        states = [
            BehaviorStateDefinition(
                ethogram_revision_id=ethogram.id,
                code=item.code.strip(),
                label=item.label.strip(),
                channel=item.channel.strip(),
                description=item.description,
                sort_order=index,
            )
            for index, item in enumerate(payload.states)
        ]
        self.session.add_all(states)
        self.session.commit()
        self.session.refresh(ethogram)
        return self._ethogram_response(ethogram, states)

    def list_ethograms(self, project_id: str) -> list[BehaviorEthogramResponse]:
        self._project(project_id)
        records = list(
            self.session.scalars(
                select(BehaviorEthogramRevision)
                .where(BehaviorEthogramRevision.project_id == project_id)
                .order_by(
                    BehaviorEthogramRevision.created_at,
                    BehaviorEthogramRevision.id,
                )
            )
        )
        latest: dict[str, BehaviorEthogramRevision] = {}
        for record in records:
            current = latest.get(record.ethogram_series_id)
            if current is None or record.revision > current.revision:
                latest[record.ethogram_series_id] = record
        return [
            self._ethogram_response(record)
            for record in sorted(
                latest.values(),
                key=lambda item: (item.name.casefold(), item.ethogram_series_id),
            )
        ]

    def _ethogram_response(
        self,
        record: BehaviorEthogramRevision,
        states: list[BehaviorStateDefinition] | None = None,
    ) -> BehaviorEthogramResponse:
        if states is None:
            states = list(
                self.session.scalars(
                    select(BehaviorStateDefinition)
                    .where(BehaviorStateDefinition.ethogram_revision_id == record.id)
                    .order_by(
                        BehaviorStateDefinition.sort_order,
                        BehaviorStateDefinition.id,
                    )
                )
            )
        return BehaviorEthogramResponse(
            id=record.id,
            ethogram_series_id=record.ethogram_series_id,
            project_id=record.project_id,
            revision=record.revision,
            supersedes_revision_id=record.supersedes_revision_id,
            name=record.name,
            description=record.description,
            definition_sha256=record.definition_sha256,
            created_by=record.created_by,
            created_at=record.created_at,
            states=[
                BehaviorStateDefinitionResponse.model_validate(state)
                for state in states
            ],
        )

    @staticmethod
    def _track_frame_bounds(track: VideoTrack) -> tuple[int, int]:
        frames = sorted(
            int(item["frame"])
            for item in list(track.keyframes_json or [])
            if isinstance(item, dict) and isinstance(item.get("frame"), int)
        )
        if not frames:
            raise ValidationError("Behavior bouts require a track with source keyframes")
        return frames[0], frames[-1]

    def create_bout(
        self,
        track_id: str,
        payload: BehaviorBoutCreateRequest,
    ) -> BehaviorBoutResponse:
        track = self._track(track_id)
        video = self._video(track.video_id)
        ethogram = self._ethogram(payload.ethogram_revision_id)
        state = self._state(payload.behavior_state_id)
        if state.ethogram_revision_id != ethogram.id:
            raise ValidationError("Behavior state does not belong to the selected ethogram revision")
        if ethogram.project_id != video.project_id:
            raise ValidationError("Behavior ethogram belongs to a different project")

        first_frame, last_frame = self._track_frame_bounds(track)
        if payload.start_frame < first_frame or payload.end_frame > last_frame:
            raise ValidationError(
                "Behavior bout must stay within the selected track frame range"
            )

        existing = self._effective_bouts(track.id, ethogram.id)
        same_channel = [
            (bout, bout_state)
            for bout, bout_state in existing
            if bout_state.channel == state.channel
        ]
        for bout, bout_state in same_channel:
            overlaps = not (
                payload.end_frame < bout.start_frame
                or payload.start_frame > bout.end_frame
            )
            if overlaps:
                raise ValidationError(
                    "Behavior bouts cannot overlap within the same ethogram channel"
                )
            adjacent_same_state = (
                bout_state.id == state.id
                and (
                    payload.start_frame == bout.end_frame + 1
                    or bout.start_frame == payload.end_frame + 1
                )
            )
            if adjacent_same_state:
                raise ValidationError(
                    "Adjacent bouts with the same behavior state should be one continuous bout"
                )

        record = BehaviorBoutRevision(
            bout_series_id=str(uuid4()),
            revision=1,
            supersedes_bout_id=None,
            video_track_id=track.id,
            ethogram_revision_id=ethogram.id,
            behavior_state_id=state.id,
            start_frame=payload.start_frame,
            end_frame=payload.end_frame,
            source=payload.source,
            confidence=(
                float(payload.confidence)
                if payload.confidence is not None
                else None
            ),
            review_status="verified" if payload.source == "manual" else "unreviewed",
            source_track_revision=track.revision,
            source_model_id=None,
            source_job_id=None,
            is_deleted=False,
            revision_reason="manual_annotation"
            if payload.source == "manual"
            else "imported_annotation",
            note=payload.note,
            created_by="local_user",
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._bout_response(record, state, track, video)

    def _effective_bouts(
        self,
        track_id: str,
        ethogram_revision_id: str | None = None,
    ) -> list[tuple[BehaviorBoutRevision, BehaviorStateDefinition]]:
        statement = (
            select(BehaviorBoutRevision, BehaviorStateDefinition)
            .join(
                BehaviorStateDefinition,
                BehaviorStateDefinition.id == BehaviorBoutRevision.behavior_state_id,
            )
            .where(BehaviorBoutRevision.video_track_id == track_id)
        )
        if ethogram_revision_id is not None:
            statement = statement.where(
                BehaviorBoutRevision.ethogram_revision_id == ethogram_revision_id
            )
        rows = list(self.session.execute(statement))
        latest: dict[str, tuple[BehaviorBoutRevision, BehaviorStateDefinition]] = {}
        for bout, state in rows:
            current = latest.get(bout.bout_series_id)
            if current is None or bout.revision > current[0].revision:
                latest[bout.bout_series_id] = (bout, state)
        effective = [
            item for item in latest.values() if not item[0].is_deleted
        ]
        effective.sort(
            key=lambda item: (
                item[1].channel.casefold(),
                item[0].start_frame,
                item[0].end_frame,
                item[1].sort_order,
                item[0].id,
            )
        )
        return effective

    def list_bouts(
        self,
        track_id: str,
        ethogram_revision_id: str | None = None,
    ) -> list[BehaviorBoutResponse]:
        track = self._track(track_id)
        video = self._video(track.video_id)
        return [
            self._bout_response(bout, state, track, video)
            for bout, state in self._effective_bouts(track.id, ethogram_revision_id)
        ]

    @staticmethod
    def _bout_response(
        bout: BehaviorBoutRevision,
        state: BehaviorStateDefinition,
        track: VideoTrack,
        video: VideoAsset,
    ) -> BehaviorBoutResponse:
        frame_count = bout.end_frame - bout.start_frame + 1
        return BehaviorBoutResponse(
            id=bout.id,
            bout_series_id=bout.bout_series_id,
            revision=bout.revision,
            supersedes_bout_id=bout.supersedes_bout_id,
            video_track_id=bout.video_track_id,
            ethogram_revision_id=bout.ethogram_revision_id,
            behavior_state_id=bout.behavior_state_id,
            behavior_code=state.code,
            behavior_label=state.label,
            channel=state.channel,
            start_frame=bout.start_frame,
            end_frame=bout.end_frame,
            start_time_seconds=bout.start_frame / video.fps,
            end_time_seconds=bout.end_frame / video.fps,
            duration_seconds=frame_count / video.fps,
            source=bout.source,
            confidence=bout.confidence,
            review_status=bout.review_status,
            source_track_revision=bout.source_track_revision,
            stale_against_track=bout.source_track_revision != track.revision,
            revision_reason=bout.revision_reason,
            note=bout.note,
            created_by=bout.created_by,
            created_at=bout.created_at,
        )

    def analyze(
        self,
        track_id: str,
        payload: BehaviorDynamicsRequest,
    ) -> BehaviorDynamicsResponse:
        track = self._track(track_id)
        video = self._video(track.video_id)
        ethogram = self._ethogram(payload.ethogram_revision_id)
        if ethogram.project_id != video.project_id:
            raise ValidationError("Behavior ethogram belongs to a different project")

        first_frame, last_frame = self._track_frame_bounds(track)
        start_frame = (
            payload.start_frame if payload.start_frame is not None else first_frame
        )
        end_frame = payload.end_frame if payload.end_frame is not None else last_frame
        if start_frame < first_frame or end_frame > last_frame:
            raise ValidationError(
                "Behavior dynamics frame range must stay within the selected track"
            )

        rows = self._effective_bouts(track.id, ethogram.id)
        rows = [
            (bout, state)
            for bout, state in rows
            if bout.end_frame >= start_frame and bout.start_frame <= end_frame
        ]
        states = list(
            self.session.scalars(
                select(BehaviorStateDefinition)
                .where(BehaviorStateDefinition.ethogram_revision_id == ethogram.id)
                .order_by(
                    BehaviorStateDefinition.channel,
                    BehaviorStateDefinition.sort_order,
                    BehaviorStateDefinition.id,
                )
            )
        )
        states_by_channel: dict[str, list[BehaviorStateDefinition]] = defaultdict(list)
        for state in states:
            states_by_channel[state.channel].append(state)

        evaluated_frames = end_frame - start_frame + 1
        evaluated_seconds = evaluated_frames / video.fps
        stale_count = sum(
            1 for bout, _state in rows if bout.source_track_revision != track.revision
        )
        channels: list[BehaviorChannelDynamics] = []

        for channel in sorted(states_by_channel, key=str.casefold):
            channel_rows = [
                (bout, state)
                for bout, state in rows
                if state.channel == channel
            ]
            clipped: list[tuple[BehaviorBoutRevision, BehaviorStateDefinition, int, int]] = []
            for bout, state in channel_rows:
                clipped_start = max(start_frame, bout.start_frame)
                clipped_end = min(end_frame, bout.end_frame)
                if clipped_start <= clipped_end:
                    clipped.append((bout, state, clipped_start, clipped_end))
            clipped.sort(key=lambda item: (item[2], item[3], item[0].id))

            dwell_frames: Counter[str] = Counter()
            bout_durations: dict[str, list[float]] = defaultdict(list)
            for _bout, state, clipped_start, clipped_end in clipped:
                frames = clipped_end - clipped_start + 1
                dwell_frames[state.id] += frames
                bout_durations[state.id].append(frames / video.fps)

            labeled_frames = sum(dwell_frames.values())
            transition_counts: Counter[tuple[str, str]] = Counter()
            outgoing_counts: Counter[str] = Counter()
            for first, second in zip(clipped, clipped[1:], strict=False):
                _first_bout, first_state, _first_start, first_end = first
                _second_bout, second_state, second_start, _second_end = second
                if second_start != first_end + 1:
                    continue
                transition_counts[(first_state.id, second_state.id)] += 1
                outgoing_counts[first_state.id] += 1

            state_lookup = {state.id: state for state in states_by_channel[channel]}
            state_summaries: list[BehaviorStateDynamics] = []
            for state in states_by_channel[channel]:
                frames = dwell_frames[state.id]
                durations = bout_durations.get(state.id, [])
                state_summaries.append(
                    BehaviorStateDynamics(
                        behavior_state_id=state.id,
                        behavior_code=state.code,
                        behavior_label=state.label,
                        channel=channel,
                        bout_count=len(durations),
                        dwell_frames=frames,
                        dwell_seconds=frames / video.fps,
                        fraction_of_evaluated_time=frames / evaluated_frames,
                        fraction_of_labeled_time=(
                            frames / labeled_frames if labeled_frames else 0.0
                        ),
                        mean_bout_seconds=(
                            sum(durations) / len(durations) if durations else None
                        ),
                        maximum_bout_seconds=max(durations) if durations else None,
                    )
                )

            transitions = [
                BehaviorTransitionDynamics(
                    channel=channel,
                    from_behavior_state_id=from_id,
                    from_behavior_code=state_lookup[from_id].code,
                    to_behavior_state_id=to_id,
                    to_behavior_code=state_lookup[to_id].code,
                    count=count,
                    probability_from_state=count / outgoing_counts[from_id],
                )
                for (from_id, to_id), count in sorted(
                    transition_counts.items(),
                    key=lambda item: (
                        state_lookup[item[0][0]].sort_order,
                        state_lookup[item[0][1]].sort_order,
                    ),
                )
            ]
            channels.append(
                BehaviorChannelDynamics(
                    channel=channel,
                    evaluated_frames=evaluated_frames,
                    evaluated_seconds=evaluated_seconds,
                    labeled_frames=labeled_frames,
                    labeled_seconds=labeled_frames / video.fps,
                    unlabeled_frames=evaluated_frames - labeled_frames,
                    unlabeled_seconds=(evaluated_frames - labeled_frames) / video.fps,
                    coverage_fraction=labeled_frames / evaluated_frames,
                    states=state_summaries,
                    transitions=transitions,
                )
            )

        return BehaviorDynamicsResponse(
            track_id=track.id,
            video_id=video.id,
            track_number=track.track_number,
            ethogram_revision_id=ethogram.id,
            ethogram_definition_sha256=ethogram.definition_sha256,
            start_frame=start_frame,
            end_frame=end_frame,
            fps=video.fps,
            provenance_status="stale" if stale_count else "current",
            provenance_warning=(
                "One or more behavior bouts were attached to an older video-track revision; "
                "review those labels before treating identity-linked behavior as current."
                if stale_count
                else None
            ),
            stale_bout_count=stale_count,
            channels=channels,
        )

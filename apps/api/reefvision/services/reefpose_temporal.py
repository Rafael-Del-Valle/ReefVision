"""Prepare event-supervised temporal features from frozen ReefPose records."""

from itertools import pairwise
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    ModelRegistration,
    PoseIdentityAssociationRun,
    PoseMeasurementRun,
    PoseMeasurementSample,
    PoseMeasurementSeries,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.reefpose_temporal import (
    TemporalClip,
    TemporalDatasetManifest,
    TemporalDatasetRequest,
    TemporalDatasetResponse,
    TemporalFeature,
    TemporalFrame,
)
from reefvision.schemas.reefpose_validation import EventWindow, ReferenceEvent
from reefvision.services.reefpose_validation import ReferenceService, frozen_recording
from reefvision.storage.datasets import canonical_json_sha256

MAX_DATASET_SAMPLES = 100_000


def _frames(
    series: list[PoseMeasurementSeries],
    samples: list[PoseMeasurementSample],
    windows: list[EventWindow],
    events: list[ReferenceEvent],
    unobservable_frames: set[int],
) -> list[TemporalFrame]:
    time_by_frame: dict[int, float] = {}
    by_series: dict[str, dict[int, PoseMeasurementSample]] = {channel.id: {} for channel in series}
    for sample in samples:
        if abs(time_by_frame.setdefault(sample.frame_index, sample.time_s) - sample.time_s) > 1e-6:
            raise ValidationError("Temporal features disagree on the source frame time")
        by_series[sample.series_id][sample.frame_index] = sample
    times = sorted(time_by_frame.items())
    if any(left[1] >= right[1] for left, right in pairwise(times)):
        raise ValidationError("Temporal feature times must increase with source frames")
    frames: list[TemporalFrame] = []
    window_index = event_index = 0
    for frame, time_s in times:
        while window_index < len(windows) and time_s >= windows[window_index].end_s:
            window_index += 1
        if window_index == len(windows):
            break
        if time_s < windows[window_index].start_s:
            continue
        while event_index < len(events) and time_s >= events[event_index].end_s:
            event_index += 1
        event = events[event_index] if event_index < len(events) else None
        target: int | None = 0
        if event is not None and event.start_s <= time_s:
            target = 1 if event.state == "complete" and event.quality == "scored" else None
        values: list[float | None] = []
        confidence: list[float | None] = []
        for channel in series:
            channel_sample = by_series[channel.id].get(frame)
            value = (
                channel_sample.pixel_value
                if channel_sample is not None and channel_sample.valid
                else None
            )
            values.append(value)
            confidence.append(
                channel_sample.confidence
                if channel_sample is not None and value is not None
                else None
            )
        frames.append(
            TemporalFrame(
                frame_index=frame,
                time_s=time_s,
                window_index=window_index,
                values=values,
                confidence=confidence,
                reference_unobservable=frame in unobservable_frames,
                target=(
                    target
                    if frame not in unobservable_frames and any(v is not None for v in values)
                    else None
                ),
            )
        )
    return frames


def export_temporal_training_data(
    session: Session, project_id: str, reference_id: str, payload: TemporalDatasetRequest
) -> TemporalDatasetResponse:
    reference = ReferenceService(session).get(project_id, reference_id)
    recordings = {
        raw["video_id"]: frozen_recording(raw) for raw in reference.manifest["recordings"]
    }
    reference_video_revisions = {
        raw["video_id"]: raw.get("video_revision") for raw in reference.manifest["recordings"]
    }
    if len(set(payload.feature_ids)) != len(payload.feature_ids):
        raise ValidationError("Temporal feature IDs must be unique")

    remaining_samples = MAX_DATASET_SAMPLES
    seen_individuals: set[tuple[str, str]] = set()
    seen_tracks: set[tuple[str, str]] = set()
    clips: list[TemporalClip] = []
    features: list[TemporalFeature] = []
    schema_hash: str | None = None
    for request in payload.clips:
        run = session.get(PoseMeasurementRun, str(request.measurement_run_id))
        if run is None or run.project_id != project_id:
            raise NotFoundError("Pose measurement run was not found")
        recording = recordings.get(run.video_id)
        if recording is None:
            raise ValidationError("The measurement video is absent from this frozen reference")
        if recording.split != "development":
            raise ValidationError("Held-out recordings are excluded from temporal training data")
        if (
            run.status != "completed"
            or run.result_sha256 is None
            or run.video_sha256 != recording.video_sha256
            or run.video_revision != reference_video_revisions[run.video_id]
            or run.pose_schema_id != str(recording.schema_id)
            or run.pose_schema_revision != recording.schema_revision
            or run.pose_schema_content_hash != recording.schema_sha256
        ):
            raise ValidationError("Completed measurements must match the frozen video and anatomy")
        source = session.get(PoseIdentityAssociationRun, run.source_identity_run_id)
        if source is None or source.project_id != project_id or source.video_id != run.video_id:
            raise ValidationError("The source pose association run does not match")
        model = (
            session.get(ModelRegistration, source.source_model_id)
            if source.source_model_id is not None
            else None
        )
        key = (run.video_id, request.reference_individual_id)
        track = (run.video_id, str(request.animal_identity_id))
        if key in seen_individuals or track in seen_tracks:
            raise ValidationError("Each video individual and source track may appear only once")
        seen_individuals.add(key)
        seen_tracks.add(track)

        annotation = next(
            (item for item in recording.annotations if item.rater_id == payload.rater_id), None
        )
        windows = sorted(
            (
                window
                for window in recording.event_windows
                if window.individual_id == request.reference_individual_id
                and window.label == payload.label
            ),
            key=lambda window: window.start_s,
        )
        if annotation is None or (not annotation.blinded and not annotation.adjudicates):
            raise ValidationError("Choose a blinded rater or adjudication in the frozen reference")
        if not windows:
            raise ValidationError(
                "Temporal training requires declared review windows for each clip"
            )
        events = sorted(
            (
                event
                for event in annotation.events
                if event.individual_id == request.reference_individual_id
                and event.label == payload.label
            ),
            key=lambda event: (event.start_s, event.end_s, event.id),
        )
        if any(a.end_s > b.start_s for a, b in pairwise(events)):
            raise ValidationError("Temporal training requires non-overlapping events for the label")

        channels = {
            channel.definition_id: channel
            for channel in session.scalars(
                select(PoseMeasurementSeries).where(
                    PoseMeasurementSeries.measurement_run_id == run.id,
                    PoseMeasurementSeries.animal_identity_id == str(request.animal_identity_id),
                    PoseMeasurementSeries.definition_id.in_(payload.feature_ids),
                )
            )
        }
        if set(channels) != set(payload.feature_ids):
            raise ValidationError("The selected track must contain every requested feature")
        series = [channels[feature_id] for feature_id in payload.feature_ids]
        definitions = {definition["id"]: definition for definition in run.definitions_json}
        if not set(payload.feature_ids) <= definitions.keys():
            raise ValidationError("The selected run is missing a frozen feature definition")
        clip_features = [
            TemporalFeature(
                definition_id=channel.definition_id,
                landmark_ids=channel.landmark_ids_json,
                formula_version=channel.formula_version,
                definition_sha256=canonical_json_sha256(
                    {
                        "definition": {
                            key: value
                            for key, value in definitions[channel.definition_id].items()
                            if key != "name"
                        },
                        "maximum_gap_s": run.configuration_json.get("maximum_gap_s", 0.25),
                    }
                ),
                unit=channel.pixel_unit,
            )
            for channel in series
        ]
        if schema_hash is None:
            schema_hash, features = recording.schema_sha256, clip_features
        elif schema_hash != recording.schema_sha256 or features != clip_features:
            raise ValidationError(
                "Temporal clips must use the same anatomy and feature definitions"
            )

        samples = list(
            session.scalars(
                select(PoseMeasurementSample)
                .where(
                    PoseMeasurementSample.series_id.in_([channel.id for channel in series]),
                    PoseMeasurementSample.time_s >= windows[0].start_s,
                    PoseMeasurementSample.time_s < windows[-1].end_s,
                )
                .order_by(PoseMeasurementSample.frame_index, PoseMeasurementSample.series_id)
                .limit(remaining_samples + 1)
            )
        )
        remaining_samples -= len(samples)
        if remaining_samples < 0:
            raise ValidationError("Temporal dataset has too many samples; request fewer clips")
        unobservable = {
            state.frame
            for state in annotation.frame_states
            if state.individual_id == request.reference_individual_id
            and state.label == payload.label
            and state.state in {"ambiguous", "missing"}
        }
        frames = _frames(series, samples, windows, events, unobservable)
        if not any(frame.target is not None for frame in frames):
            raise ValidationError("No usable labeled measurement frames in the selected clip")
        clips.append(
            TemporalClip(
                video_id=recording.video_id,
                video_sha256=recording.video_sha256,
                group_id=recording.group_id,
                reference_individual_id=request.reference_individual_id,
                annotation_sha256=canonical_json_sha256(annotation.model_dump(mode="json")),
                measurement_run_id=request.measurement_run_id,
                measurement_sha256=run.result_sha256,
                measurement_input_sha256=run.input_manifest_sha256,
                animal_identity_id=request.animal_identity_id,
                identity_run_id=run.source_identity_run_id,
                identity_run_revision=run.source_identity_run_revision,
                source_pose_model_id=UUID(model.id) if model is not None else None,
                source_pose_model_sha256=model.sha256 if model is not None else None,
                series_sha256=[channel.series_sha256 for channel in series],
                windows=windows,
                events=events,
                frames=frames,
            )
        )
    assert schema_hash is not None
    manifest = TemporalDatasetManifest(
        reference_id=reference.id,
        reference_sha256=reference.manifest_sha256,
        data_kind=reference.data_kind,
        pose_schema_sha256=schema_hash,
        rater_id=payload.rater_id,
        label=payload.label,
        features=features,
        clips=sorted(clips, key=lambda clip: (str(clip.video_id), clip.reference_individual_id)),
    )
    return TemporalDatasetResponse(
        manifest=manifest, sha256=canonical_json_sha256(manifest.model_dump(mode="json"))
    )

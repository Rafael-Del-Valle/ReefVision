"""Pair video model outcomes on the same frozen ReefPose validation evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from math import hypot, isfinite
from statistics import fmean
from typing import Any, Literal
from unicodedata import normalize

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Job,
    ModelRegistration,
    PoseIdentityAssociationRun,
    PoseIdentityObservation,
    VideoAsset,
)
from reefvision.domain.errors import ValidationError
from reefvision.domain.pose_evaluation import PoseEvaluationInstance
from reefvision.domain.reefpose_agreement import rate
from reefvision.jobs.reefpose_validation import completed_report
from reefvision.schemas.reefpose_validation import (
    ReferenceAnnotation,
    ReferenceRecording,
    ValidationConfiguration,
)
from reefvision.services.reefpose_validation import ReferenceService, frozen_recording
from reefvision.services.reefpose_validation_analysis import _pose_and_identity
from reefvision.services.temporal_reefpose_sources import (
    GROUP_FIELDS,
    frame_training_lineage,
    source_model,
)
from reefvision.storage.datasets import canonical_json_sha256

VideoTask = Literal["pose", "tracking", "event"]
Row = dict[str, Any]
Measurement = int | float | None
Pair = tuple[Row, Row]
Instances = list[tuple[str, PoseEvaluationInstance]]

_INPUT_FIELDS = (
    "schema_version",
    "reference_id",
    "reference_sha256",
    "scored_reference_manifest",
    "data_kind",
    "split",
    "rater_id",
    "models",
    "prediction_sources",
    "tracker_protocol",
    "development_lock_sha256",
    "configurations",
    "bootstrap_seed",
)
_TRACKING_PARAMETERS = ("algorithm", "algorithm_version", "parameters_sha256")


def _normalized(value: str) -> str:
    return normalize("NFKC", value).strip().casefold()


def _index(rows: list[Row], key: str) -> dict[str, Row]:
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ValidationError(f"Duplicate {key} in frozen video scoring evidence")
    return result


def _registered_model(
    session: Session, project_id: str, model_id: str, report: Row, *, historical: bool
) -> ModelRegistration:
    model = source_model(session, project_id, model_id)
    models = report["models"]
    if model.task != "pose" or set(models) != {model_id}:
        raise ValidationError("The scored job must bind exactly the selected pose checkpoint")
    if not historical and (model.metadata_json or {}).get("exchange_media_missing") is True:
        raise ValidationError(
            "The selected checkpoint weights were omitted from the restored project"
        )
    snapshot = models[model_id]
    if snapshot["checkpoint_sha256"] != model.sha256 or snapshot["id"] != model.id:
        raise ValidationError("The registered checkpoint does not match the frozen scoring job")
    return model


def _held_out_groups(
    session: Session, project_id: str, frozen: list[Row], *, historical: bool
) -> tuple[set[str], dict[str, VideoAsset]]:
    partitions: dict[str, str] = {}
    animals: dict[str, str] = {}
    held_out = set()
    group_tokens = set()
    videos = {}
    for entry in frozen:
        group = _normalized(entry["group_id"])
        split = entry["split"]
        if partitions.setdefault(group, split) != split:
            raise ValidationError("A recording group overlaps development and held-out data")
        for subject in entry["individuals"]:
            animal = _normalized(subject["id"])
            if animals.setdefault(animal, group) != group:
                raise ValidationError(
                    "An animal identifier is shared by supposedly independent groups"
                )
            if split == "test":
                group_tokens.add(f"group:animal:{animal}")
        if split != "test":
            continue
        held_out.add(group)
        group_tokens.update((f"group:{group}", f"group:recording:{group}"))
        video = session.get(VideoAsset, entry["video_id"])
        geometry = entry["video_geometry"]
        if (
            video is None
            or video.project_id != project_id
            or video.sha256 != entry["video_sha256"]
            or (
                video.width_px,
                video.height_px,
                video.frame_count,
                video.fps,
                video.duration_seconds,
            )
            != (
                geometry["width"],
                geometry["height"],
                geometry["frames"],
                geometry["fps"],
                geometry["duration_s"],
            )
            or not isfinite(video.fps)
            or video.fps <= 0
        ):
            raise ValidationError(
                "Held-out navigation requires the original scoped video geometry and hash"
            )
        metadata = video.metadata_json or {}
        if not historical and metadata.get("exchange_media_missing") is True:
            raise ValidationError(
                "The original held-out video was omitted from the restored project"
            )
        for name in GROUP_FIELDS:
            value = metadata.get(name)
            if isinstance(value, str) and value.strip():
                normalized = _normalized(value)
                group_tokens.add(f"group:{normalized}")
                if name == "animal_id":
                    group_tokens.add(f"group:animal:{normalized}")
                elif name == "recording_group":
                    group_tokens.add(f"group:recording:{normalized}")
        videos[video.id] = video
    if len(held_out) < 2:
        raise ValidationError(
            "Paired video comparison requires at least two independent held-out groups"
        )
    return group_tokens, videos


def _require_disjoint_training(
    session: Session,
    model: ModelRegistration,
    cohort: dict[str, VideoAsset],
    group_tokens: set[str],
) -> None:
    lineage = frame_training_lineage(session, model)
    if not lineage["complete"] or not lineage.get("declared_groups"):
        raise ValidationError(
            "Checkpoint training and selection need frozen recording and animal lineage"
        )
    videos = {video.sha256 for video in cohort.values()}
    for recording in lineage["recordings"]:
        if recording["sha256"] in videos or group_tokens & {
            _normalized(token) for token in recording["groups"]
        }:
            raise ValidationError(
                "Checkpoint training or selection overlaps a held-out video, recording, or animal"
            )


def _check_input(
    session: Session, report: Row, job_id: str, project_id: str, model: ModelRegistration
) -> None:
    job = session.get(Job, job_id)
    assert job is not None  # Scoped and loaded by completed_report.
    if (
        canonical_json_sha256({key: report[key] for key in _INPUT_FIELDS}) != report["input_sha256"]
        or (job.request_json or {}).get("input_sha256") != report["input_sha256"]
        or report["selected_configuration_index"] != 0
        or report["configurations"] != [report["selected_configuration"]]
    ):
        raise ValidationError("The frozen scoring input or selected configuration changed")
    lock_id = (job.request_json or {}).get("payload", {}).get("development_job_id")
    if not isinstance(lock_id, str):
        raise ValidationError("Held-out scoring requires a completed development protocol")
    lock = completed_report(session, project_id, lock_id)
    if (
        lock["split"] != "development"
        or lock["result_sha256"] != report["development_lock_sha256"]
        or lock["reference_sha256"] != report["reference_sha256"]
        or lock["selected_configuration"] != report["selected_configuration"]
        or set(lock["models"]) != {model.id}
        or lock["models"][model.id]["checkpoint_sha256"] != model.sha256
    ):
        raise ValidationError("The scoring job does not match its frozen development protocol")


def _upstream_protocol(source: Row) -> Row | None:
    protocol = source.get("upstream_protocol")
    if protocol is None:
        return None
    # Architecture/provider versions are the models being compared, not tuning knobs.
    return {key: val for key, val in protocol.items() if key not in {"provider", "version"}}


def _check_sources(pair: Pair) -> None:
    left, right = pair
    if _upstream_protocol(left) != _upstream_protocol(right):
        raise ValidationError("Video jobs used different upstream tracking settings")
    if (
        left["algorithm"] is not None
        and right["algorithm"] is not None
        and any(left[key] != right[key] for key in _TRACKING_PARAMETERS)
    ):
        raise ValidationError("Video jobs used different identity association settings")


def _original_observations(
    session: Session, project_id: str, video: VideoAsset, source: Row, model: ModelRegistration
) -> list[Row]:
    if source["model_id"] != model.id:
        raise ValidationError("A recording prediction does not match the selected checkpoint")
    if source["algorithm"] is None:
        zero = session.get(Job, source["id"])
        if (
            zero is None
            or zero.project_id != project_id
            or zero.job_type != "video_tracking"
            or zero.status != "succeeded"
            or not isinstance(zero.result_json, dict)
            or zero.result_json.get("video_id") != video.id
            or zero.result_json.get("model_id") != model.id
            or zero.result_json.get("detection_count") != 0
            or zero.result_json.get("pose_track_hashes") != {}
            or zero.result_json.get("pose_input_hashes")
            != {
                "video_sha256": video.sha256,
                "model_sha256": model.sha256,
            }
        ):
            raise ValidationError("Zero detections require the original completed tracking receipt")
        rows: list[Row] = []
    else:
        run = session.get(PoseIdentityAssociationRun, source["id"])
        if (
            run is None
            or run.project_id != project_id
            or run.video_id != video.id
            or run.status != "completed"
            or run.source_model_id != model.id
            or run.algorithm != source["algorithm"]
            or run.algorithm_version != source["algorithm_version"]
            or run.parameters_sha256 != source["parameters_sha256"]
            or run.input_manifest_sha256 != source["input_manifest_sha256"]
        ):
            raise ValidationError("The original association run is unavailable or incompatible")
        rows = [
            {
                "id": row.id,
                "identity_id": row.animal_identity_id,
                "frame": row.frame_index,
                "time_s": row.time_s,
                "bbox": row.bbox_json,
                "landmarks": row.landmarks_json,
                "association_confidence": row.association_confidence,
                "detection_key": row.source_detection_key,
                "source_track_id": row.source_video_track_id,
            }
            for row in session.scalars(
                select(PoseIdentityObservation)
                .where(
                    PoseIdentityObservation.association_run_id == run.id,
                    PoseIdentityObservation.revision == 1,
                    PoseIdentityObservation.assignment_source == "model",
                )
                .order_by(PoseIdentityObservation.frame_index, PoseIdentityObservation.id)
            )
        ]
    if canonical_json_sha256(rows) != source["observations_sha256"]:
        raise ValidationError("Original scored video observations no longer match their checksum")
    return rows


def _metric(name: str, unit: str, left: Measurement, right: Measurement) -> Row:
    def finite(value: Measurement) -> Measurement:
        if value is not None and not isinstance(value, bool) and isfinite(value):
            return value
        return None

    return {"name": name, "unit": unit, "left": finite(left), "right": finite(right)}


def _observation(
    media_id: str,
    metrics: list[Row],
    *,
    frame: int | None = None,
    seconds: float | None = None,
    exclusion: str | None = None,
) -> Row:
    return {
        "media_kind": "video",
        "media_id": media_id,
        "metrics": metrics,
        **({"frame": frame} if frame is not None else {}),
        **({"seconds": seconds} if seconds is not None else {}),
        **({"exclusion": exclusion} if exclusion else {}),
    }


def _pose_frames(video_id: str, pair: tuple[Instances, Instances], excluded: set[int]) -> list[Row]:
    visible: Counter[int] = Counter()
    absent: Counter[int] = Counter()
    for _, instance in pair[0]:
        frame = int(instance.instance_id.rsplit(":", 1)[1])
        visible[frame] += sum(point.visibility == "visible" for point in instance.references)
        absent[frame] += sum(
            point.visibility in {"absent", "out_of_frame"} for point in instance.references
        )

    def errors(
        instances: Instances,
    ) -> tuple[dict[int, dict[tuple[str, str], tuple[float, float]]], Counter[int]]:
        by_frame: dict[int, dict[tuple[str, str], tuple[float, float]]] = defaultdict(dict)
        extra: Counter[int] = Counter()
        for animal, instance in instances:
            frame = int(instance.instance_id.rsplit(":", 1)[1])
            estimates = {point.landmark_id: point for point in instance.estimates if point.visible}
            for reference in instance.references:
                point = estimates.get(reference.landmark_id)
                if point is None:
                    continue
                if reference.visibility in {"absent", "out_of_frame"}:
                    extra[frame] += 1
                elif reference.visibility == "visible":
                    distance = hypot(reference.x - point.x, reference.y - point.y)
                    by_frame[frame][(animal, reference.landmark_id)] = (
                        distance,
                        distance / instance.normalization_length,
                    )
        return by_frame, extra

    left, left_extra = errors(pair[0])
    right, right_extra = errors(pair[1])
    rows = []
    for frame in sorted(set(visible) | excluded):
        if frame in excluded:
            rows.append(
                _observation(
                    video_id, [], frame=frame, exclusion="Reference frame is uncertain or unscored"
                )
            )
            continue
        a, b = left[frame], right[frame]
        common = sorted(a.keys() & b.keys())
        rows.append(
            _observation(
                video_id,
                [
                    _metric("visible_reference_landmarks", "count", visible[frame], visible[frame]),
                    _metric("visible_landmarks_localized", "count", len(a), len(b)),
                    _metric(
                        "visible_landmarks_missing",
                        "count",
                        visible[frame] - len(a),
                        visible[frame] - len(b),
                    ),
                    _metric(
                        "absent_or_out_of_frame_reference_landmarks",
                        "count",
                        absent[frame],
                        absent[frame],
                    ),
                    _metric(
                        "false_visible_landmarks",
                        "count",
                        left_extra[frame] if absent[frame] else None,
                        right_extra[frame] if absent[frame] else None,
                    ),
                    _metric("jointly_localized_landmarks", "count", len(common), len(common)),
                    _metric(
                        "joint_landmark_mean_error",
                        "px",
                        fmean(a[key][0] for key in common) if common else None,
                        fmean(b[key][0] for key in common) if common else None,
                    ),
                    _metric(
                        "joint_normalized_landmark_mean_error",
                        "fraction",
                        fmean(a[key][1] for key in common) if common else None,
                        fmean(b[key][1] for key in common) if common else None,
                    ),
                ],
                frame=frame,
            )
        )
    return rows or [
        _observation(video_id, [], exclusion="No scored anatomical landmark observations")
    ]


def _identity_frames(
    record: ReferenceRecording,
    annotation: ReferenceAnnotation,
    sources: Pair,
    outcomes: tuple[Row, Row],
    assignments: tuple[dict[tuple[str, int], str], dict[tuple[str, int], str]],
) -> list[Row]:
    video_id = str(record.video_id)
    expected = Counter(
        pose.frame for pose in annotation.poses if pose.state == "scored" and pose.bbox is not None
    )
    excluded = {pose.frame for pose in annotation.poses if pose.state != "scored"}
    coverage = set(expected) | set(annotation.empty_identity_frames)
    exhaustive = record.exhaustive_identity_coverage
    predicted = tuple(Counter(row["frame"] for row in source["observations"]) for source in sources)
    matches = tuple(Counter(frame for _, frame in item) for item in assignments)
    correct = tuple(
        Counter(
            frame
            for (animal, frame), actual in matched.items()
            if actual == outcome["identity_mapping"].get(animal)
        )
        for matched, outcome in zip(assignments, outcomes, strict=True)
    )
    switches = tuple(Counter(row["frame"] for row in item["switches"]) for item in outcomes)
    observations = []
    first_scored = min(coverage - excluded, default=None)
    for frame in sorted(coverage | excluded):
        if frame in excluded:
            observations.append(
                _observation(
                    video_id,
                    [],
                    frame=frame,
                    exclusion="Reference frame excluded from identity scoring",
                )
            )
            continue
        counts = [
            _metric("frame_reference_identities", "count", expected[frame], expected[frame]),
            _metric("frame_spatial_matches", "count", matches[0][frame], matches[1][frame]),
            _metric("frame_identity_correct", "count", correct[0][frame], correct[1][frame]),
            _metric(
                "frame_identity_misses",
                "count",
                expected[frame] - correct[0][frame],
                expected[frame] - correct[1][frame],
            ),
            _metric(
                "frame_spatial_misses",
                "count",
                expected[frame] - matches[0][frame],
                expected[frame] - matches[1][frame],
            ),
            _metric(
                "frame_unmatched_detections",
                "count",
                predicted[0][frame] - matches[0][frame] if exhaustive else None,
                predicted[1][frame] - matches[1][frame] if exhaustive else None,
            ),
            _metric("frame_identity_switches", "count", switches[0][frame], switches[1][frame]),
        ]
        if frame == first_scored:
            for key in ("id_true_positives", "id_false_negatives", "fragmentations"):
                counts.append(
                    _metric(f"recording_{key}", "count", outcomes[0].get(key), outcomes[1].get(key))
                )
            key = "id_f1" if exhaustive else "conditional_id_f1"
            ratios = tuple(
                rate(
                    2 * row["id_true_positives"],
                    2 * row["id_true_positives"]
                    + row["id_false_positives"]
                    + row["id_false_negatives"],
                )
                for row in outcomes
            )
            counts.append(_metric(f"recording_{key}", "fraction", ratios[0], ratios[1]))
            counts.append(
                _metric(
                    "recording_id_false_positives",
                    "count",
                    outcomes[0]["id_false_positives"] if exhaustive else None,
                    outcomes[1]["id_false_positives"] if exhaustive else None,
                )
            )
        observations.append(_observation(video_id, counts, frame=frame))
    return observations or [
        _observation(video_id, [], exclusion="No scored identity reference frames")
    ]


def _event_windows(record: ReferenceRecording, outcomes: Pair) -> list[Row]:
    def index(rows: list[Row]) -> dict[tuple[str, str, float], Row]:
        return {(row["individual_id"], row["label"], row["start_s"]): row for row in rows}

    def unmatched(rows: list[Row], label: str, start: float, end: float, state: str) -> int:
        return sum(
            row[state]["fp"]
            for row in rows
            if row["individual_id"].startswith("unmatched:")
            and row["label"] == label
            and row["start_s"] == start
            and row.get("end_s") == end
            and state in row
        )

    video_id = str(record.video_id)
    left, right = (index(row["events"]) for row in outcomes)
    results = []
    for window in sorted(
        record.event_windows, key=lambda row: (row.start_s, row.label, row.individual_id)
    ):
        key = (window.individual_id, window.label, window.start_s)
        a, b = left.get(key), right.get(key)
        if a is None or b is None or "excluded" in a or "excluded" in b:
            results.append(
                _observation(
                    video_id,
                    [],
                    seconds=window.start_s,
                    exclusion="Event window is ambiguous or unavailable in one scored report",
                )
            )
            continue
        counts = []
        timing = []
        for state in ("complete", "partial"):
            lhs, rhs = a[state], b[state]
            truth_count = lhs["tp"] + lhs["fn"]
            if truth_count != rhs["tp"] + rhs["fn"]:
                raise ValidationError("The jobs do not score the same event reference denominator")
            # In exhaustive coverage, unmatched animals share the declared time span.
            # Count their spurious events once per span, on the first reference individual.
            include_unmatched = (
                record.exhaustive_event_coverage
                and window.individual_id == record.individuals[0].id
            )
            fp_left = lhs["fp"] + (
                unmatched(outcomes[0]["events"], window.label, window.start_s, window.end_s, state)
                if include_unmatched
                else 0
            )
            fp_right = rhs["fp"] + (
                unmatched(outcomes[1]["events"], window.label, window.start_s, window.end_s, state)
                if include_unmatched
                else 0
            )
            scope = "" if record.exhaustive_event_coverage else "_in_reference_windows"
            matches_left, matches_right = (
                _index(lhs["matches"], "reference"),
                _index(rhs["matches"], "reference"),
            )
            common = sorted(matches_left.keys() & matches_right.keys())
            counts.extend(
                [
                    _metric(f"{state}_reference_events", "count", truth_count, truth_count),
                    _metric(f"{state}_event_matches", "count", lhs["tp"], rhs["tp"]),
                    _metric(f"{state}_event_misses", "count", lhs["fn"], rhs["fn"]),
                    _metric(f"{state}_event_extras{scope}", "count", fp_left, fp_right),
                    _metric(
                        f"{state}_event_count_error{scope}",
                        "count",
                        fp_left - lhs["fn"],
                        fp_right - rhs["fn"],
                    ),
                    _metric(f"{state}_jointly_matched_events", "count", len(common), len(common)),
                ]
            )
            for identifier in common:
                first, second = matches_left[identifier], matches_right[identifier]
                if first["reference_start_s"] != second["reference_start_s"]:
                    raise ValidationError(
                        "Matched event timestamps disagree with the common reference"
                    )
                errors = []
                for boundary in ("onset", "offset", "duration", "peak"):
                    metric_key = f"{boundary}_error_s"
                    x, y = first[metric_key], second[metric_key]
                    errors.append(
                        _metric(
                            f"{state}_joint_{boundary}_absolute_error",
                            "s",
                            abs(x) if x is not None and y is not None else None,
                            abs(y) if x is not None and y is not None else None,
                        )
                    )
                timing.append(_observation(video_id, errors, seconds=first["reference_start_s"]))
        results.append(_observation(video_id, counts, seconds=window.start_s))
        results.extend(timing)
    return results or [
        _observation(video_id, [], exclusion="No event scoring windows were declared")
    ]


def _compare_video(
    session: Session,
    project_id: str,
    task: VideoTask,
    source_ids: Sequence[str],
    model_ids: Sequence[str],
    *,
    historical: bool,
) -> Row:
    if (
        len(source_ids) != 2
        or len(set(source_ids)) != 2
        or len(model_ids) != 2
        or len(set(model_ids)) != 2
    ):
        raise ValidationError(
            "Comparison requires two distinct scoring jobs and registered checkpoints"
        )
    left, right = (completed_report(session, project_id, source_id) for source_id in source_ids)
    pair = (left, right)
    if any(
        row["schema_version"] != "reefpose-scientific-validation-1" or row["split"] != "test"
        for row in pair
    ):
        raise ValidationError("Both jobs must score a frozen held-out ReefPose test split")
    if any(
        left[key] != right[key]
        for key in (
            "reference_id",
            "reference_sha256",
            "scored_reference_manifest",
            "data_kind",
            "rater_id",
            "selected_configuration",
        )
    ):
        raise ValidationError(
            "The jobs must use the same frozen reference, rater, and comparison configuration"
        )
    reference = ReferenceService(session).get(project_id, left["reference_id"])
    held_out = [row for row in reference.manifest["recordings"] if row["split"] == "test"]
    if (
        reference.manifest_sha256 != left["reference_sha256"]
        or left["scored_reference_manifest"] != {**reference.manifest, "recordings": held_out}
        or reference.data_kind != left["data_kind"]
    ):
        raise ValidationError(
            "The evaluation reference is not the complete immutable held-out cohort"
        )
    groups, videos = _held_out_groups(
        session, project_id, reference.manifest["recordings"], historical=historical
    )
    first_model, second_model = (
        _registered_model(session, project_id, model_id, report, historical=historical)
        for model_id, report in zip(model_ids, pair, strict=True)
    )
    if first_model.sha256 == second_model.sha256:
        raise ValidationError("Both registrations identify the same checkpoint bytes")
    for job, model, report in zip(source_ids, (first_model, second_model), pair, strict=True):
        _check_input(session, report, job, project_id, model)
        _require_disjoint_training(session, model, videos, groups)
    sources_a, sources_b = (_index(report["prediction_sources"], "video_id") for report in pair)
    outcomes_a, outcomes_b = (_index(report["recordings"], "video_id") for report in pair)
    if any(set(rows) != set(videos) for rows in (sources_a, sources_b, outcomes_a, outcomes_b)):
        raise ValidationError("Both jobs must include the same complete held-out recordings")
    config = ValidationConfiguration.model_validate(left["selected_configuration"])

    output: dict[str, list[Row]] = defaultdict(list)
    for row in sorted(held_out, key=lambda item: (item["group_id"], item["video_id"])):
        video = videos[row["video_id"]]
        record = frozen_recording(row)
        annotation = next(
            (item for item in record.annotations if item.rater_id == left["rater_id"]), None
        )
        if annotation is None:
            raise ValidationError("The frozen rater does not cover all held-out recordings")
        source_pair = (sources_a[video.id], sources_b[video.id])
        _check_sources(source_pair)
        observations = tuple(
            {
                **source,
                "observations": _original_observations(session, project_id, video, source, model),
            }
            for source, model in zip(source_pair, (first_model, second_model), strict=True)
        )
        if task == "event":
            results = _event_windows(record, (outcomes_a[video.id], outcomes_b[video.id]))
        else:
            names = {point["id"]: point["name"] for point in row["schema"]["landmarks"]}
            lscore, rscore = (
                _pose_and_identity(record, annotation, source, config, names)
                for source in observations
            )
            if task == "pose":
                excluded = {pose.frame for pose in annotation.poses if pose.state != "scored"}
                results = _pose_frames(video.id, (lscore[1], rscore[1]), excluded)
            else:
                results = _identity_frames(
                    record,
                    annotation,
                    (observations[0], observations[1]),
                    (lscore[0], rscore[0]),
                    (lscore[2], rscore[2]),
                )
        output[record.group_id].extend(results)

    descriptions = {
        "pose": "Localization errors use only the same visible landmarks localized by both models.",
        "tracking": (
            "Identity association metrics use declared reference coverage. "
            "Spatial matches and identity correctness are separate."
        ),
        "event": (
            "Timing errors compare common matched reference events. "
            "Extras are scoped to the declared windows and coverage."
        ),
    }
    return {
        "reference_id": reference.id,
        "reference_sha256": reference.manifest_sha256,
        "source_sha256": [row["result_sha256"] for row in pair],
        "groups": [
            {"group_id": group, "observations": observations}
            for group, observations in sorted(output.items())
        ],
        "method": "paired_heldout_reefpose_v1",
        "limitations": [
            descriptions[task],
            "Group independence depends on the frozen local recording and animal declarations.",
            "Coordinates describe a two-dimensional projection. "
            "Missing support does not count as measured error.",
            "Synthetic engineering fixture."
            if reference.data_kind == "synthetic"
            else "Biological validity depends on the reference and independent review evidence.",
        ],
    }


def compare_video_models(
    session: Session,
    project_id: str,
    task: VideoTask,
    source_ids: Sequence[str],
    model_ids: Sequence[str],
    *,
    historical: bool = False,
) -> dict[str, Any]:
    """Return comparable held-out observations using original scored data and model identity."""
    if task not in ("pose", "tracking", "event"):
        raise ValidationError("Unknown held-out video comparison task")
    try:
        return _compare_video(
            session, project_id, task, source_ids, model_ids, historical=historical
        )
    except (KeyError, TypeError, ValueError, IndexError, OverflowError, ZeroDivisionError) as exc:
        raise ValidationError(
            "Frozen video comparison evidence is incomplete or malformed"
        ) from exc

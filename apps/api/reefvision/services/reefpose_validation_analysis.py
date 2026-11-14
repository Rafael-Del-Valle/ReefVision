"""Apply the existing pose, identity and movement engines to independent references."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict
from itertools import combinations
from math import hypot
from statistics import fmean
from typing import Any, cast

from reefvision.domain.pose_anatomical_measurement import (
    AnatomicalLandmark,
    AnatomicalObservation,
    MeasurementCalibration,
    MeasurementDefinition,
    calculate_measurement_series,
)
from reefvision.domain.pose_biological_events import (
    CycleDefinition,
    EventSignalSample,
    detect_biological_events,
)
from reefvision.domain.pose_evaluation import (
    PoseEvaluationInstance,
    PoseLandmarkEstimate,
    PoseLandmarkReference,
    evaluate_pose_instances,
)
from reefvision.domain.pose_identity_evaluation import (
    IdentityObservation,
    evaluate_pose_identities,
    match_identity_frame,
)
from reefvision.domain.reefpose_agreement import (
    ScoredEvent,
    cluster_interval,
    event_agreement,
    icc_absolute,
    measurement_agreement,
    rate,
)
from reefvision.schemas.reefpose_validation import (
    EventWindow,
    ReferenceAnnotation,
    ReferenceEvent,
    ReferenceMeasurement,
    ReferenceRecording,
    ValidationConfiguration,
)


def _scored(event: ReferenceEvent) -> ScoredEvent:
    return ScoredEvent(
        event.id,
        event.start_s,
        event.end_s if event.offset_observed else None,
        event.peak_s,
        event.state,
        event.amplitude,
        event.amplitude_unit,
        event.onset_observed,
    )


def _inside(event: ScoredEvent, window: EventWindow) -> bool:
    return window.start_s <= event.start < window.end_s and (
        event.end is None or event.end <= window.end_s
    )


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tp, fp, fn = (sum(row[key] for row in rows) for key in ("tp", "fp", "fn"))
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": rate(tp, tp + fp),
        "recall": rate(tp, tp + fn),
        "f1": rate(2 * tp, 2 * tp + fp + fn),
        "count_error": fp - fn,
    }


def _rater_agreement(
    records: list[ReferenceRecording],
    config: ValidationConfiguration,
    seed: int,
) -> dict[str, Any]:
    measurements: dict[tuple[str, str], dict[tuple[str, str, int], dict[str, float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    groups = {str(record.video_id): record.group_id for record in records}
    event_pairs: list[dict[str, Any]] = []
    adjudications = []
    for record in records:
        video = str(record.video_id)
        raters = [item for item in record.annotations if not item.adjudicates]
        for item in record.annotations:
            if item.adjudicates:
                adjudications.append(
                    {
                        "video_id": video,
                        "rater_id": item.rater_id,
                        "source_raters": item.adjudicates,
                        "note": item.adjudication_note,
                    }
                )
        for item in raters:
            for sample in item.measurements:
                if sample.state == "scored" and sample.value is not None:
                    key = (video, sample.individual_id, sample.frame)
                    measurements[(sample.definition_id, sample.unit)][key][item.rater_id] = (
                        sample.value
                    )
        for left, right in combinations(sorted(raters, key=lambda item: item.rater_id), 2):
            for window in record.event_windows:

                def events(
                    item: ReferenceAnnotation, window: EventWindow = window
                ) -> list[ScoredEvent]:
                    return [
                        _scored(event)
                        for event in item.events
                        if event.individual_id == window.individual_id
                        and event.label == window.label
                        and event.quality == "scored"
                        and event.state == "complete"
                        and _inside(_scored(event), window)
                    ]

                if any(
                    event.quality == "ambiguous"
                    and event.label == window.label
                    and event.individual_id == window.individual_id
                    and _inside(_scored(event), window)
                    for item in (left, right)
                    for event in item.events
                ):
                    continue
                event_pairs.append(
                    {
                        "video_id": video,
                        "individual_id": window.individual_id,
                        "label": window.label,
                        "raters": [left.rater_id, right.rater_id],
                        **event_agreement(
                            events(left),
                            events(right),
                            config.onset_tolerance_s,
                            config.offset_tolerance_s,
                        ),
                    }
                )
    icc = []
    for (definition, unit), units in sorted(measurements.items()):
        raters_set = sorted({rater for row in units.values() for rater in row})
        balanced = {
            key: [row[rater] for rater in raters_set]
            for key, row in sorted(units.items())
            if set(row) == set(raters_set)
        }
        by_group: dict[str, list[list[float]]] = defaultdict(list)
        for key, values in balanced.items():
            by_group[groups[key[0]]].append(values)
        circular = any(
            item.id == definition and item.kind in {"body_axis_orientation", "direction"}
            for item in config.definitions
        )
        pairwise = []
        for left_id, right_id in combinations(raters_set, 2):
            pairs = [
                (row[left_id], row[right_id])
                for row in units.values()
                if left_id in row and right_id in row
            ]
            pairwise.append(
                {
                    "raters": [left_id, right_id],
                    **measurement_agreement(pairs, circular=circular),
                }
            )
        icc.append(
            {
                "definition_id": definition,
                "unit": unit,
                "raters": raters_set,
                "complete_units": len(balanced),
                "total_units": len(units),
                "icc_a1": None if circular else icc_absolute(list(balanced.values())),
                "ci95": None if circular else cluster_interval(by_group, icc_absolute, seed),
                "pairwise": pairwise,
            }
        )
    return {"measurements": icc, "events": event_pairs, "adjudications": adjudications}


def _pose_and_identity(
    record: ReferenceRecording,
    reference: ReferenceAnnotation,
    source: dict[str, Any],
    config: ValidationConfiguration,
    names: dict[str, str],
) -> tuple[dict[str, Any], list[tuple[str, PoseEvaluationInstance]], dict[tuple[str, int], str]]:
    truth_by_frame: dict[int, list[IdentityObservation]] = defaultdict(list)
    predicted_by_frame: dict[int, list[IdentityObservation]] = defaultdict(list)
    estimates: dict[tuple[str, int], dict[str, Any]] = {}
    for pose in reference.poses:
        if pose.state == "scored" and pose.bbox is not None:
            truth_by_frame[pose.frame].append(
                IdentityObservation(pose.individual_id, pose.frame, pose.bbox)
            )
    unscored = {pose.frame for pose in reference.poses if pose.state != "scored"}
    scored_frames = set(truth_by_frame) | set(reference.empty_identity_frames)
    for obs in source["observations"]:
        frame = obs["frame"]
        identity = obs["identity_id"] or f"unassigned:{obs['id']}"
        if frame in scored_frames:
            estimates[(identity, frame)] = obs
            predicted_by_frame[frame].append(
                IdentityObservation(
                    identity,
                    frame,
                    tuple(obs["bbox"]),
                )
            )
    matches: dict[tuple[str, int], str] = {}
    for frame, truth in sorted(truth_by_frame.items()):
        for left, right in match_identity_frame(
            truth, predicted_by_frame[frame], config.iou_threshold
        ):
            matches[(left.identity_id, frame)] = right.identity_id
    truth_rows = [
        item for frame, rows in truth_by_frame.items() if frame not in unscored for item in rows
    ]
    matched_prediction_keys = {(frame, prediction) for (_, frame), prediction in matches.items()}
    prediction_rows = [
        item
        for frame, rows in predicted_by_frame.items()
        if frame not in unscored
        for item in rows
        if record.exhaustive_identity_coverage
        or (item.frame_index, item.identity_id) in matched_prediction_keys
    ]
    report: dict[str, Any] = (
        asdict(
            evaluate_pose_identities(
                truth_rows, prediction_rows, iou_threshold=config.iou_threshold
            )
        )
        if truth_rows
        else {
            "identity_mapping": {},
            "per_identity": [],
            "id_true_positives": 0,
            "id_false_negatives": 0,
            "id_false_positives": len(prediction_rows),
        }
    )
    switches = []
    recovery = []
    last: dict[str, tuple[int, str]] = {}
    occlusions: set[str] = set()
    instances = []
    pixel_errors = []
    occluded_errors = []
    crossing_hits = crossing_total = 0
    for pose in sorted(reference.poses, key=lambda item: (item.frame, item.individual_id)):
        key = (pose.individual_id, pose.frame)
        matched = matches.get(key)
        if pose.state == "occluded":
            occlusions.add(pose.individual_id)
        if pose.state != "scored" or pose.bbox is None:
            continue
        if pose.crossing and pose.frame not in unscored:
            crossing_total += 1
            crossing_hits += int(
                matched is not None
                and matched == report["identity_mapping"].get(pose.individual_id)
            )
        if matched and pose.frame not in unscored:
            prior = last.get(pose.individual_id)
            if prior and matched != prior[1]:
                switches.append(
                    {
                        "individual_id": pose.individual_id,
                        "frame": pose.frame,
                        "previous": prior[1],
                        "current": matched,
                    }
                )
            if pose.individual_id in occlusions:
                recovery.append(
                    {
                        "individual_id": pose.individual_id,
                        "frame": pose.frame,
                        "same_identity": prior is not None and prior[1] == matched,
                    }
                )
                occlusions.remove(pose.individual_id)
            last[pose.individual_id] = (pose.frame, matched)
        points = {
            p["landmark_id"]: p
            for p in estimates.get((matched or "", pose.frame), {}).get("landmarks", [])
            if p.get("x") is not None and p.get("y") is not None
        }
        refs = tuple(
            PoseLandmarkReference(
                p.id,
                names[p.id],
                p.x or 0,
                p.y or 0,
                p.visibility,
            )
            for p in pose.landmarks
            if p.visibility != "uncertain"
        )
        if not refs:
            continue
        predictions = tuple(
            PoseLandmarkEstimate(
                landmark_id,
                p["x"],
                p["y"],
                p.get("confidence") or 0,
                p.get("visibility") == "visible",
            )
            for landmark_id, p in sorted(points.items())
            if landmark_id in names
        )
        instances.append(
            (
                pose.individual_id,
                PoseEvaluationInstance(
                    f"{record.video_id}:{pose.individual_id}:{pose.frame}",
                    refs,
                    predictions,
                    hypot(pose.bbox[2], pose.bbox[3]),
                ),
            )
        )
        for point in pose.landmarks:
            if (
                point.id in points
                and point.x is not None
                and point.y is not None
                and points[point.id].get("visibility") in {"visible", "occluded"}
            ):
                error = hypot(points[point.id]["x"] - point.x, points[point.id]["y"] - point.y)
                if point.visibility == "visible" and points[point.id]["visibility"] == "visible":
                    pixel_errors.append(error)
                elif point.visibility == "occluded":
                    occluded_errors.append(error)
    report.update(
        switches=switches,
        occlusion_recovery=recovery,
        crossing_total=crossing_total,
        crossing_identity_matches=crossing_hits,
        excluded_identity_frames=sorted(unscored),
        identity_precision_scope=(
            "all_predictions_on_scored_frames"
            if record.exhaustive_identity_coverage
            else "matched_predictions_only"
        ),
        mean_localization_error_px=fmean(pixel_errors) if pixel_errors else None,
        mean_occluded_error_px=fmean(occluded_errors) if occluded_errors else None,
        occluded_localized_count=len(occluded_errors),
        calibrated_error=(
            {
                "unit": record.calibration.unit,
                "coordinate_space": "projected_2d",
                "mean_error": fmean(pixel_errors) / record.calibration.pixels_per_unit,
            }
            if record.calibration and pixel_errors
            else None
        ),
    )
    if not record.exhaustive_identity_coverage:
        report["conditional_id_f1"] = report.pop("id_f1", None)
        report["conditional_id_precision"] = report.pop("id_precision", None)
    return report, instances, matches


def _movement(
    record: ReferenceRecording,
    reference: ReferenceAnnotation,
    source: dict[str, Any],
    config: ValidationConfiguration,
    identity_map: dict[str, str],
    frame_matches: dict[tuple[str, int], str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calibration = (
        MeasurementCalibration(record.calibration.pixels_per_unit, record.calibration.unit)
        if record.calibration
        else None
    )
    fps = source["fps"]
    by_identity: dict[str, list[AnatomicalObservation]] = defaultdict(list)
    for item in source["observations"]:
        identity_id = item["identity_id"]
        if identity_id is None:
            continue
        confidence = item["association_confidence"]
        excluded = config.minimum_association_confidence > 0 and (
            confidence is None or confidence < config.minimum_association_confidence
        )
        by_identity[identity_id].append(
            AnatomicalObservation(
                item["id"],
                1,
                identity_id,
                item["frame"],
                item["time_s"] if item["time_s"] is not None else item["frame"] / fps,
                "source_pixels",
                confidence,
                tuple(AnatomicalLandmark(**point) for point in item["landmarks"])
                if not excluded
                else (),
            )
        )
    measurement_reports = []
    event_reports = []
    cycles = {cycle.label: cycle for cycle in config.events}
    subjects = [
        (individual.id, identity_map.get(individual.id), False) for individual in record.individuals
    ]
    if record.exhaustive_event_coverage:
        subjects.extend(
            (f"unmatched:{identity}", identity, True)
            for identity in sorted(set(by_identity) - set(identity_map.values()))
        )
    for individual_id, predicted_id, unmatched in subjects:
        observations = by_identity.get(predicted_id or "", [])
        known_assignments = {
            frame: individual
            for (individual, frame), prediction in frame_matches.items()
            if prediction == predicted_id
        }
        wrong_frames = {
            frame
            for frame, assigned in known_assignments.items()
            if not unmatched and assigned != individual_id
        }
        observations = [item for item in observations if item.frame_index not in wrong_frames]
        series = {
            item.id: calculate_measurement_series(
                observations,
                MeasurementDefinition(item.id, item.kind, tuple(item.landmark_ids), item.options),
                calibration,
                maximum_gap_s=config.maximum_gap_s,
            )
            for item in config.definitions
            if observations
        }
        reference_pairs: dict[tuple[str, str], list[ReferenceMeasurement]] = defaultdict(list)
        for sample in reference.measurements:
            if not unmatched and sample.individual_id == individual_id:
                reference_pairs[(sample.definition_id, sample.unit)].append(sample)
        for (definition, unit), rows in sorted(reference_pairs.items()):
            signal = series.get(definition)
            values: dict[int, float] = {}
            if signal and unit in {signal.pixel_unit, signal.physical_unit}:
                for observed in signal.samples:
                    value = (
                        observed.physical_value
                        if unit == signal.physical_unit
                        else observed.pixel_value
                    )
                    if observed.valid and value is not None:
                        values[observed.frame_index] = value
            scored = [row for row in rows if row.state == "scored" and row.value is not None]
            pairs = [
                (row.value, values[row.frame])
                for row in scored
                if row.frame in values and row.value is not None
            ]
            circular = bool(
                signal and signal.measurement_kind in {"direction", "body_axis_orientation"}
            )
            analysis = measurement_agreement(pairs, circular=circular)
            sensitivity = None
            if (
                record.calibration
                and record.calibration.relative_uncertainty
                and signal
                and unit == signal.physical_unit
            ):
                u = record.calibration.relative_uncertainty
                scales = [1 - u, 1 + u]
                if signal.measurement_kind != "curvature":
                    scales = [1 / scale for scale in scales]
                sensitivity = [
                    {
                        "pixels_per_unit_multiplier": multiplier,
                        **measurement_agreement([(ref, pred * scale) for ref, pred in pairs]),
                    }
                    for multiplier, scale in zip([1 - u, 1 + u], scales, strict=True)
                ]
            measurement_reports.append(
                {
                    "individual_id": individual_id,
                    "definition_id": definition,
                    "unit": unit,
                    "coordinate_space": "projected_2d"
                    if signal and unit == signal.physical_unit
                    else "source_image",
                    "reference_n": len(scored),
                    "availability": (
                        "matched"
                        if pairs
                        else "unit_or_calibration_unavailable"
                        if signal and unit not in {signal.pixel_unit, signal.physical_unit}
                        else "no_matched_samples"
                    ),
                    "ambiguous_or_missing": len(rows) - len(scored),
                    "matched_frames": [row.frame for row in scored if row.frame in values],
                    "calibration_sensitivity": sensitivity,
                    **analysis,
                }
            )
        detected_by_label: dict[str, list[ScoredEvent]] = {}
        states_by_label: dict[str, dict[int, str]] = {}
        for label, cycle in cycles.items():
            signal = series.get(cycle.definition_id)
            if signal is None:
                continue
            if cycle.unit not in {signal.physical_unit, signal.pixel_unit}:
                raise ValueError(f"Cycle {label} unit {cycle.unit} is unavailable for this series")
            samples = [
                EventSignalSample(
                    sample.frame_index,
                    sample.time_s,
                    sample.physical_value
                    if cycle.unit == signal.physical_unit
                    else sample.pixel_value,
                    sample.confidence,
                    sample.valid,
                    individual_id,
                )
                for sample in signal.samples
            ]
            candidates = detect_biological_events(
                samples, CycleDefinition(**cycle.detector_options())
            )
            # Instantaneous threshold state is separate from event-cycle matching.
            states_by_label[label] = {
                sample.frame_index: "open" if sample.value >= cycle.open_threshold else "closed"
                for sample in samples
                if sample.valid
                and sample.value is not None
                and (sample.value >= cycle.open_threshold or sample.value <= cycle.close_threshold)
            }
            detected_by_label[label] = [
                ScoredEvent(
                    str(i),
                    event.start_time_s,
                    event.end_time_s,
                    event.peak_time_s,
                    "complete" if event.cycle_state == "complete" else "partial",
                    event.amplitude,
                    cycle.unit,
                    event.cycle_state != "partial_start",
                )
                for i, event in enumerate(candidates.events)
                if event.accepted or event.cycle_state != "complete"
            ]
        for window in record.event_windows:
            window_owner = record.individuals[0].id if unmatched else individual_id
            if window.individual_id != window_owner or window.label not in cycles:
                continue
            relevant = [
                event
                for event in reference.events
                if not unmatched
                and event.label == window.label
                and event.individual_id == individual_id
                and _inside(_scored(event), window)
            ]
            ambiguous = any(
                event.quality == "ambiguous"
                and event.label == window.label
                and (unmatched or event.individual_id == individual_id)
                and _inside(_scored(event), window)
                for event in reference.events
            )
            if ambiguous:
                event_reports.append(
                    {
                        "individual_id": individual_id,
                        "label": window.label,
                        "excluded": "ambiguous_reference",
                        "start_s": window.start_s,
                    }
                )
                continue
            detected = [
                event
                for event in detected_by_label.get(window.label, [])
                if _inside(event, window)
                and not any(
                    event.start <= frame / fps <= (event.end or window.end_s)
                    for frame in wrong_frames
                )
            ]
            scored_events: dict[str, Any] = {
                "individual_id": individual_id,
                "label": window.label,
                "start_s": window.start_s,
                "end_s": window.end_s,
                "reference_events": [asdict(_scored(event)) for event in relevant],
                "predicted_events": [asdict(event) for event in detected],
            }
            for state in ("complete", "partial"):
                scored_events[state] = event_agreement(
                    [_scored(item) for item in relevant if item.state == state],
                    [item for item in detected if item.state == state],
                    config.onset_tolerance_s,
                    config.offset_tolerance_s,
                )
            scored_events["frequency_error_hz"] = scored_events["complete"]["count_error"] / (
                window.end_s - window.start_s
            )
            scored_events["frequency_reference_hz"] = len(
                [event for event in relevant if event.state == "complete"]
            ) / (window.end_s - window.start_s)
            scored_events["frequency_prediction_hz"] = (
                scored_events["frequency_reference_hz"] + scored_events["frequency_error_hz"]
            )
            states = states_by_label.get(window.label, {})
            frame_pairs = [
                (item.state, states.get(item.frame))
                for item in reference.frame_states
                if item.individual_id == individual_id
                and item.label == window.label
                and item.state in {"open", "closed"}
                and window.start_s <= item.frame / fps < window.end_s
            ]
            scored_events["frame_state"] = {
                "reference_count": len(frame_pairs),
                "unclassified": sum(predicted is None for _, predicted in frame_pairs),
                "correct": sum(expected == predicted for expected, predicted in frame_pairs),
                "accuracy": rate(sum(a == b for a, b in frame_pairs), len(frame_pairs)),
            }
            event_reports.append(scored_events)
    return measurement_reports, event_reports


def analyze(
    records: list[tuple[ReferenceRecording, ReferenceAnnotation, dict[str, Any], dict[str, str]]],
    configurations: list[ValidationConfiguration],
    seed: int,
    progress: Callable[[], None],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    details = []
    for index, config in enumerate(configurations):
        rows = []
        all_instances = []
        species: dict[str, list[PoseEvaluationInstance]] = defaultdict(list)
        conditions: dict[str, list[PoseEvaluationInstance]] = defaultdict(list)
        by_individual: dict[str, list[PoseEvaluationInstance]] = defaultdict(list)
        pose_clusters: dict[str, list[tuple[float, int]]] = defaultdict(list)
        measurement_clusters: dict[tuple[str, str], dict[str, list[tuple[float, float]]]] = (
            defaultdict(lambda: defaultdict(list))
        )
        grouped_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        grouped_partial: dict[str, list[dict[str, Any]]] = defaultdict(list)
        id_totals: dict[str, int] = defaultdict(int)
        exhaustive_identity = all(record.exhaustive_identity_coverage for record, *_ in records)
        for record, annotation, source, names in records:
            identity, instances, frame_matches = _pose_and_identity(
                record, annotation, source, config, names
            )
            measures, events = _movement(
                record, annotation, source, config, identity["identity_mapping"], frame_matches
            )
            grouped_events[record.group_id].extend(
                row["complete"] for row in events if "complete" in row
            )
            grouped_partial[record.group_id].extend(
                row["partial"] for row in events if "partial" in row
            )
            for key in (
                "id_true_positives",
                "id_false_positives",
                "id_false_negatives",
                "identity_switches",
                "fragmentations",
            ):
                id_totals[key] += identity.get(key, 0)
            individuals = {item.id: item.species for item in record.individuals}
            for individual, instance in instances:
                all_instances.append(instance)
                species[individuals[individual]].append(instance)
                conditions[record.conditions].append(instance)
                by_individual[f"{record.video_id}:{individual}"].append(instance)
            if instances:
                local_pose = evaluate_pose_instances([instance for _, instance in instances])
                if local_pose.nme is not None:
                    n = local_pose.matched_visible_count
                    pose_clusters[record.group_id].append((local_pose.nme * n, n))
            for measurement in measures:
                measurement_key = (measurement["definition_id"], measurement["unit"])
                measurement_clusters[measurement_key][record.group_id].extend(
                    (
                        point["mean"] - point["difference"] / 2,
                        point["mean"] + point["difference"] / 2,
                    )
                    for point in measurement["points"]
                )
            rows.append(
                {
                    "video_id": str(record.video_id),
                    "group_id": record.group_id,
                    "conditions": record.conditions,
                    "fps": source["fps"],
                    "identity": identity,
                    "measurements": measures,
                    "events": events,
                    "individuals": individuals,
                    "rater_id": annotation.rater_id,
                    "reference_kind": "adjudicated"
                    if annotation.adjudicates
                    else "individual_rater",
                }
            )
            progress()
        complete = _totals([row for items in grouped_events.values() for row in items])
        candidates.append(
            {
                "configuration_index": index,
                "complete": complete,
                "partial": _totals([row for items in grouped_partial.values() for row in items]),
                "complete_f1_ci95": cluster_interval(
                    grouped_events,
                    lambda values: cast(float | None, _totals(values)["f1"]),
                    seed,
                ),
            }
        )
        pck = tuple(sorted(config.pck_thresholds))
        pose_metrics = (
            evaluate_pose_instances(all_instances, pck_thresholds=pck) if all_instances else None
        )
        tp, fp, fn = (
            id_totals[f"id_{suffix}"]
            for suffix in ("true_positives", "false_positives", "false_negatives")
        )
        details.append(
            {
                "recordings": rows,
                "identity": {
                    **id_totals,
                    "id_f1": rate(2 * tp, 2 * tp + fp + fn) if exhaustive_identity else None,
                    "id_precision": rate(tp, tp + fp) if exhaustive_identity else None,
                    "conditional_id_f1": (
                        rate(2 * tp, 2 * tp + fp + fn) if not exhaustive_identity else None
                    ),
                    "id_recall": rate(tp, tp + fn),
                    "precision_scope": "exhaustive" if exhaustive_identity else "conditional",
                },
                "pose": asdict(pose_metrics) if pose_metrics else None,
                "pose_nme_ci95": cluster_interval(
                    pose_clusters,
                    lambda values: rate(
                        sum(error for error, _ in values), sum(n for _, n in values)
                    ),
                    seed,
                ),
                "pose_by_individual": {
                    key: asdict(evaluate_pose_instances(values, pck_thresholds=pck))
                    for key, values in sorted(by_individual.items())
                },
                "measurement_summary": [
                    {
                        "definition_id": definition,
                        "unit": unit,
                        "bias_ci95": cluster_interval(
                            {group: values for group, values in groups.items() if values},
                            lambda values: (
                                fmean(pred - truth for truth, pred in values) if values else None
                            ),
                            seed,
                        ),
                        **measurement_agreement(
                            [pair for group in sorted(groups) for pair in groups[group]]
                        ),
                    }
                    for (definition, unit), groups in sorted(measurement_clusters.items())
                ],
                "pose_by_species": {
                    key: asdict(evaluate_pose_instances(values, pck_thresholds=pck))
                    for key, values in sorted(species.items())
                },
                "pose_by_condition": {
                    key: asdict(evaluate_pose_instances(values, pck_thresholds=pck))
                    for key, values in sorted(conditions.items())
                },
            }
        )
    selected = max(
        range(len(candidates)),
        key=lambda index: (
            candidates[index]["complete"]["f1"]
            if candidates[index]["complete"]["f1"] is not None
            else -1,
            -index,
        ),
    )
    return {
        **details[selected],
        "sensitivity": candidates,
        "selected_configuration_index": selected,
        "inter_observer": _rater_agreement(
            [record for record, *_ in records], configurations[selected], seed
        ),
    }

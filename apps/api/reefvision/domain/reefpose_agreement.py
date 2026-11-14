"""Deterministic scientific agreement statistics."""

from collections.abc import Callable
from dataclasses import dataclass
from math import sqrt
from random import Random
from statistics import fmean, stdev
from typing import Any, TypeVar

from reefvision.domain.pose_identity_tracking import minimum_cost_assignment

T = TypeVar("T")


@dataclass(frozen=True)
class ScoredEvent:
    id: str
    start: float
    end: float | None
    peak: float | None = None
    state: str = "complete"
    amplitude: float | None = None
    amplitude_unit: str | None = None
    onset_observed: bool = True


def rate(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def event_agreement(
    reference: list[ScoredEvent],
    predictions: list[ScoredEvent],
    onset_tolerance: float,
    offset_tolerance: float,
) -> dict[str, Any]:
    truth = sorted(reference, key=lambda row: (row.start, row.end or row.start, row.id))
    predicted = sorted(predictions, key=lambda row: (row.start, row.end or row.start, row.id))
    # Eligible pairs cost at most 2. A missed reference costs more than all timing
    # differences combined so maximum cardinality takes priority over timing.
    missed_cost = float(2 * len(truth) + 1)
    costs = []
    for item in truth:
        row = []
        for candidate in predicted:
            onset_known = item.onset_observed and candidate.onset_observed
            onset = abs(candidate.start - item.start) if onset_known else 0.0
            offset = (
                abs(candidate.end - item.end)
                if candidate.end is not None and item.end is not None
                else 0.0
            )
            eligible = (
                item.state == candidate.state
                and (
                    onset_known
                    or (candidate.end is not None and item.end is not None)
                    or (
                        candidate.peak is not None
                        and item.peak is not None
                        and abs(candidate.peak - item.peak)
                        <= max(onset_tolerance, offset_tolerance)
                    )
                )
                and onset <= onset_tolerance + 1e-12
                and offset <= offset_tolerance + 1e-12
            )
            row.append(
                onset / max(onset_tolerance, 1e-12) + offset / max(offset_tolerance, 1e-12)
                if eligible
                else 2 * missed_cost
            )
        costs.append(row + [missed_cost] * len(truth))
    matches: list[dict[str, Any]] = []
    used: set[int] = set()
    missed: list[str] = []
    for index, column in enumerate(minimum_cost_assignment(costs) if truth else []):
        item = truth[index]
        if column >= len(predicted):
            missed.append(item.id)
            continue
        candidate = predicted[column]
        used.add(column)
        matches.append(
            {
                "reference": item.id,
                "prediction": candidate.id,
                "reference_start_s": item.start,
                "prediction_start_s": candidate.start,
                "onset_error_s": (
                    candidate.start - item.start
                    if candidate.onset_observed and item.onset_observed
                    else None
                ),
                "offset_error_s": (
                    candidate.end - item.end
                    if candidate.end is not None and item.end is not None
                    else None
                ),
                "duration_error_s": (
                    (candidate.end - candidate.start) - (item.end - item.start)
                    if candidate.end is not None
                    and item.end is not None
                    and candidate.onset_observed
                    and item.onset_observed
                    else None
                ),
                "peak_error_s": (
                    candidate.peak - item.peak
                    if candidate.peak is not None and item.peak is not None
                    else None
                ),
                "amplitude_error": (
                    candidate.amplitude - item.amplitude
                    if candidate.amplitude is not None
                    and item.amplitude is not None
                    and candidate.amplitude_unit == item.amplitude_unit
                    else None
                ),
                "amplitude_unit": item.amplitude_unit,
            }
        )
    tp = len(matches)
    return {
        "tp": tp,
        "fp": len(predicted) - tp,
        "fn": len(truth) - tp,
        "precision": rate(tp, len(predicted)),
        "recall": rate(tp, len(truth)),
        "f1": rate(2 * tp, len(predicted) + len(truth)),
        "count_error": len(predicted) - len(truth),
        "timing_errors": {
            key: {
                "n": len(errors),
                "bias": fmean(errors) if errors else None,
                "mae": fmean(map(abs, errors)) if errors else None,
                "rmse": sqrt(fmean(value**2 for value in errors)) if errors else None,
            }
            for key in ("onset_error_s", "offset_error_s", "duration_error_s", "peak_error_s")
            for errors in [[match[key] for match in matches if match[key] is not None]]
        },
        "matches": matches,
        "missed": missed,
        "spurious": [item.id for i, item in enumerate(predicted) if i not in used],
    }


def measurement_agreement(
    pairs: list[tuple[float, float]],
    *,
    circular: bool = False,
    independent: bool = False,
) -> dict[str, Any]:
    differences = [
        (estimate - reference + 180) % 360 - 180 if circular else estimate - reference
        for reference, estimate in pairs
    ]
    bias = fmean(differences) if differences else None
    sd = stdev(differences) if len(differences) > 1 else None
    return {
        "n": len(pairs),
        "bias": bias,
        "difference_sd": sd,
        "mae": fmean(map(abs, differences)) if differences else None,
        "rmse": sqrt(fmean(value**2 for value in differences)) if differences else None,
        "limits_of_agreement": (
            [bias - 1.96 * sd, bias + 1.96 * sd]
            if independent and not circular and bias is not None and sd is not None
            else None
        ),
        "points": [
            {"mean": reference + difference / 2, "difference": difference}
            for (reference, _), difference in zip(pairs, differences, strict=True)
        ],
    }


def icc_absolute(rows: list[list[float]]) -> float | None:
    """Two-way absolute-agreement single-rating ICC(A,1) on a balanced matrix."""
    n = len(rows)
    if n < 2 or len(rows[0]) < 2:
        return None
    k = len(rows[0])
    if any(len(row) != k for row in rows):
        raise ValueError("ICC requires a balanced rater matrix")
    subjects = [fmean(row) for row in rows]
    raters = [fmean(column) for column in zip(*rows, strict=True)]
    grand = fmean(subjects)
    subject_ms = k * sum((value - grand) ** 2 for value in subjects) / (n - 1)
    rater_ms = n * sum((value - grand) ** 2 for value in raters) / (k - 1)
    residual_ms = sum(
        (value - subjects[i] - raters[j] + grand) ** 2
        for i, row in enumerate(rows)
        for j, value in enumerate(row)
    ) / ((n - 1) * (k - 1))
    return rate(
        subject_ms - residual_ms,
        (subject_ms + (k - 1) * residual_ms + k * (rater_ms - residual_ms) / n),
    )


def cluster_interval(
    groups: dict[str, list[T]],
    statistic: Callable[[list[T]], float | None],
    seed: int,
) -> list[float] | None:
    """Percentile interval over top-level recording groups, with replacement."""
    clusters = [groups[key] for key in sorted(groups)]
    if len(clusters) < 5:
        return None
    random = Random(seed)
    values = []
    for _ in range(500):
        value = statistic(
            [row for cluster in random.choices(clusters, k=len(clusters)) for row in cluster]
        )
        if value is not None:
            values.append(value)
    if len(values) < 450:
        return None
    values.sort()
    return [values[int((len(values) - 1) * p)] for p in (0.025, 0.975)]

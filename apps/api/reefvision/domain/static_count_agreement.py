"""Summarize static-image pairs while respecting the declared sampling groups."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import fmean
from uuid import UUID

from reefvision.domain.reefpose_agreement import (
    cluster_interval,
    icc_absolute,
    measurement_agreement,
)
from reefvision.schemas.scientific_comparison import Limit
from reefvision.schemas.static_comparison import (
    CountStatus,
    StaticClass,
    StaticClassCount,
    StaticComparisonRequest,
    StaticImageResult,
    StaticModelEvidence,
    StaticPairedDifference,
    StaticPrediction,
    StaticReferenceImage,
    StaticStatistics,
)


@dataclass(frozen=True)
class CountPair:
    group: str | None
    reference: int
    prediction: int

    @property
    def error(self) -> int:
        return self.prediction - self.reference


def score_image(
    image: StaticReferenceImage,
    model: StaticModelEvidence,
    classes: list[StaticClass],
    observation: StaticImageResult,
) -> StaticImageResult:
    references = Counter(row.class_id for row in image.annotations)
    predictions = Counter(row.class_id for row in observation.raw_predictions)
    mismatched = any(
        not _registered_output(model, prediction.label, prediction.class_index)
        for prediction in observation.raw_predictions
    )
    unmapped = sorted(
        {
            row.label
            for row in observation.raw_predictions
            if row.class_id is None and row.label in model.labels
        }
    )
    mapped = set(model.mapping.values())
    counts = []
    for cls in classes:
        status: CountStatus
        count = None
        if observation.status != "inferred":
            status = observation.status
        elif cls.id not in mapped:
            status = "class_not_mapped"
        elif mismatched:
            status = "output_class_mismatch"
        else:
            status = "scored"
            count = predictions[cls.id]
        counts.append(
            StaticClassCount(
                class_id=cls.id, reference=references[cls.id], prediction=count, status=status
            )
        )
    message = observation.message
    if observation.status == "inferred" and unmapped and not mismatched:
        message = "Excluded unmapped detector classes: " + ", ".join(unmapped)
    return observation.model_copy(update={"counts": counts, "message": message})


def count_pairs(
    images: list[StaticImageResult],
    groups: dict[UUID, str | None],
    class_id: UUID | None,
) -> dict[UUID, CountPair]:
    pairs = {}
    for image in images:
        counts = [row for row in image.counts if class_id is None or row.class_id == class_id]
        predictions = [row.prediction for row in counts if row.prediction is not None]
        if counts and len(predictions) == len(counts):
            pairs[image.image_id] = CountPair(
                groups[image.image_id], sum(row.reference for row in counts), sum(predictions)
            )
    return pairs


def _interval(
    values: list[tuple[str | None, int]], options: StaticComparisonRequest
) -> Limit | None:
    if not options.independent_groups or any(group is None for group, _ in values):
        return None
    grouped: dict[str, list[int]] = defaultdict(list)
    for group, value in values:
        if group is not None:
            grouped[group].append(value)
    bounds = cluster_interval(grouped, fmean, options.bootstrap_seed)
    return (bounds[0], bounds[1]) if bounds else None


def statistics(rows: list[CountPair], options: StaticComparisonRequest) -> StaticStatistics:
    groups = {row.group for row in rows if row.group is not None}
    independent = options.independent_groups and len(groups) == len(rows) and len(rows) >= 3
    pairs = [(float(row.reference), float(row.prediction)) for row in rows]
    agreement = measurement_agreement(
        pairs, independent=independent and options.homoscedastic_normal_differences
    )
    percentages = [row.error / row.reference * 100 for row in rows if row.reference]
    bounds = agreement["limits_of_agreement"]
    return StaticStatistics(
        observation_count=len(rows),
        frozen_group_count=len(groups),
        independent_group_count=len(groups) if options.independent_groups else None,
        ungrouped_observation_count=sum(row.group is None for row in rows),
        zero_reference_count=len(rows) - len(percentages),
        percentage_denominator=len(percentages),
        bias=agreement["bias"],
        mean_absolute_error=agreement["mae"],
        root_mean_squared_error=agreement["rmse"],
        mean_absolute_percentage_error=fmean(map(abs, percentages)) if percentages else None,
        mean_signed_percentage_error=fmean(percentages) if percentages else None,
        limits_of_agreement=(bounds[0], bounds[1]) if bounds is not None else None,
        icc=icc_absolute([list(pair) for pair in pairs], consistency=options.icc == "C,1")
        if independent and options.icc
        else None,
        bias_ci95=_interval([(row.group, row.error) for row in rows], options),
        mae_ci95=_interval([(row.group, abs(row.error)) for row in rows], options),
    )


def paired_difference(
    left: dict[UUID, CountPair], right: dict[UUID, CountPair], options: StaticComparisonRequest
) -> StaticPairedDifference:
    shared = [(left[key], right[key]) for key in sorted(left.keys() & right.keys())]
    changes = [(a.group, abs(b.error) - abs(a.error)) for a, b in shared]
    groups = {group for group, _ in changes if group is not None}
    return StaticPairedDifference(
        observation_count=len(changes),
        frozen_group_count=len(groups),
        independent_group_count=len(groups) if options.independent_groups else None,
        ungrouped_observation_count=sum(group is None for group, _ in changes),
        absolute_error_change=fmean(value for _, value in changes) if changes else None,
        absolute_error_change_ci95=_interval(changes, options),
    )


def prediction_class(model: StaticModelEvidence, label: str, index: int | None) -> UUID | None:
    return model.mapping.get(label) if _registered_output(model, label, index) else None


def _registered_output(model: StaticModelEvidence, label: str, index: int | None) -> bool:
    return (
        label in model.labels
        if index is None
        else (0 <= index < len(model.labels) and model.labels[index] == label)
    )


def valid_prediction_mapping(model: StaticModelEvidence, prediction: StaticPrediction) -> bool:
    return prediction.class_id == prediction_class(model, prediction.label, prediction.class_index)

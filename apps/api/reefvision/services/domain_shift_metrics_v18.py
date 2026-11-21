"""Equal-weight acquisition group summaries with independent-domain uncertainty."""

from collections import defaultdict
from importlib import import_module
from math import isfinite, sqrt
from statistics import fmean, variance
from typing import Any, Literal

from pydantic import ValidationError as SchemaError

from reefvision.domain.errors import ValidationError
from reefvision.schemas.domain_shift_v18 import DomainShiftDraft
from reefvision.schemas.paired_models_v15 import PairedGroup

Lineage = Literal["held_out", "exploratory", "overlap"]
ASSUMPTIONS = [
    "Average complete paired scores within each acquisition group, then give groups equal weight.",
    "The shift is target minus reference. The paired gap compares (right minus left) by domain.",
    "Welch intervals assume independent groups and approximately normal group-level estimates.",
    "Missing and excluded groups can change the interpretation of complete-group estimates.",
    "The estimates are conditional on the frozen dataset and declared independent units.",
]


def _difference(reference: list[float], target: list[float]) -> dict[str, Any]:
    first = fmean(reference) if reference else None
    second = fmean(target) if target else None
    point = second - first if first is not None and second is not None else None
    result: dict[str, Any] = {
        "reference_n": len(reference),
        "target_n": len(target),
        "reference_mean": first,
        "target_mean": second,
        "target_minus_reference": point,
        "se": None,
        "df": None,
        "ci95": None,
        "interval_status": "insufficient_complete_groups",
    }
    if point is None or min(len(reference), len(target)) < 2:
        return result
    left = variance(reference) / len(reference)
    right = variance(target) / len(target)
    total = left + right
    if not isfinite(total):
        result["interval_status"] = "precision_unavailable"
        return result
    result["se"] = sqrt(total)
    if total == 0:
        result["interval_status"] = "zero_between_group_variation"
        return result
    df = 1 / ((left / total) ** 2 / (len(reference) - 1) + (right / total) ** 2 / (len(target) - 1))
    result["df"] = df
    try:
        critical = float(import_module("scipy.stats").t.ppf(0.975, df))
    except ImportError:
        result["interval_status"] = "statistics_runtime_unavailable"
        return result
    half_width = critical * result["se"]
    lower, upper = point - half_width, point + half_width
    if not (isfinite(lower) and isfinite(upper) and lower < point < upper):
        result["interval_status"] = "precision_unavailable"
        return result
    result["ci95"] = [lower, upper]
    result["interval_status"] = "available"
    return result


def summarize_domain_shift(
    draft: DomainShiftDraft,
    grouped: list[dict[str, Any]],
    lineage: Lineage,
) -> dict[str, Any]:
    try:
        groups = [PairedGroup.model_validate(row) for row in grouped]
    except SchemaError as exc:
        raise ValidationError("The frozen comparison observations cannot be read") from exc
    by_name = {row.group_id.strip().casefold(): row for row in groups}
    if len(by_name) != len(groups):
        raise ValidationError("The frozen comparison contains duplicate acquisition groups")
    image_ids = [observation.media_id for row in groups for observation in row.observations]
    if len(image_ids) != len(set(image_ids)) or any(
        observation.media_kind != "image" for row in groups for observation in row.observations
    ):
        raise ValidationError("Independent domain evidence requires each frozen image once")
    report: list[dict[str, Any]] = []
    samples: dict[tuple[str, str], dict[str, list[tuple[float, float]]]] = defaultdict(
        lambda: {"reference": [], "target": []}
    )
    used: set[str] = set()
    for key, roster in (("reference", draft.reference), ("target", draft.target)):
        for requested in roster.groups:
            normalized = requested.casefold()
            group = by_name.get(normalized)
            if group is None:
                report.append(
                    {
                        "group_id": requested,
                        "domain": key,
                        "status": "missing",
                        "observations": 0,
                        "exclusions": ["No matching acquisition group in the frozen evidence"],
                        "metrics": [],
                    }
                )
                continue
            used.add(normalized)
            estimates: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
            reasons: list[str] = []
            for obs in group.observations:
                if obs.exclusion:
                    reasons.append(obs.exclusion)
                    continue
                if len({(metric.name, metric.unit) for metric in obs.metrics}) != len(obs.metrics):
                    raise ValidationError("A frozen image contains duplicate scores for one metric")
                for metric in obs.metrics:
                    name = (metric.name, metric.unit)
                    if metric.left is None or metric.right is None:
                        continue
                    estimates[name].append((metric.left, metric.right))
            summary = []
            if lineage == "held_out":
                for (name, unit), values in sorted(estimates.items()):
                    first, second = (fmean(side) for side in zip(*values, strict=True))
                    samples[(name, unit)][key].append((first, second))
                    summary.append(
                        {
                            "name": name,
                            "unit": unit,
                            "left": first,
                            "right": second,
                            "paired_gap": second - first,
                            "paired_images": len(values),
                        }
                    )
            status = "withheld" if lineage != "held_out" else "included" if summary else "excluded"
            if status == "excluded" and not reasons:
                reasons = ["No complete paired score against usable frozen ground truth"]
            report.append(
                {
                    "group_id": group.group_id,
                    "domain": key,
                    "status": status,
                    "observations": len(group.observations),
                    "exclusions": sorted(set(reasons)),
                    "metrics": summary,
                }
            )
    metrics = []
    for (name, unit), domain in sorted(samples.items()):
        reference, target = domain["reference"], domain["target"]
        metrics.append(
            {
                "name": name,
                "unit": unit,
                "left": _difference([a for a, _ in reference], [a for a, _ in target]),
                "right": _difference([b for _, b in reference], [b for _, b in target]),
                "paired_gap": _difference(
                    [b - a for a, b in reference], [b - a for a, b in target]
                ),
            }
        )
    return {
        "status": "scored"
        if any(row["left"]["target_minus_reference"] is not None for row in metrics)
        else "withheld",
        "lineage": lineage,
        "groups": report,
        "outside_declared_roster": sorted(by_name[key].group_id for key in by_name.keys() - used),
        "metrics": metrics,
        "assumptions": ASSUMPTIONS,
    }

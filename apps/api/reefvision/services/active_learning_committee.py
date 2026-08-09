"""Transparent multi-model committee disagreement scoring for active learning."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

COMMITTEE_FORMULA_ID = "detection_committee_disagreement_v1"
COMMITTEE_FORMULA_VERSION = "1.0.0"
COMMITTEE_WEIGHTS = {
    "count_disagreement": 0.55,
    "confidence_disagreement": 0.30,
    "missing_model_fraction": 0.15,
}


def score_committee_disagreement(
    *,
    model_ids: list[str],
    model_names: dict[str, str],
    predictions: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Return a bounded, explainable committee-disagreement score.

    Detection count disagreement treats a selected model with no prediction as a zero count.
    Confidence disagreement is calculated across models that produced at least one prediction;
    missing models are represented separately so absence is not double-counted.
    """

    ordered_ids = list(dict.fromkeys(model_ids))
    if len(ordered_ids) < 2:
        raise ValueError("Committee scoring requires at least two distinct models")

    confidences: dict[str, list[float]] = defaultdict(list)
    selected = set(ordered_ids)
    for prediction in predictions:
        model_id = str(prediction.get("model_id") or "")
        if model_id not in selected:
            continue
        try:
            confidence = float(prediction.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidences[model_id].append(min(max(confidence, 0.0), 1.0))

    per_model: list[dict[str, Any]] = []
    counts: list[int] = []
    present_means: list[float] = []
    for model_id in ordered_ids:
        values = confidences.get(model_id, [])
        count = len(values)
        mean_confidence = sum(values) / count if count else None
        counts.append(count)
        if mean_confidence is not None:
            present_means.append(mean_confidence)
        per_model.append(
            {
                "model_id": model_id,
                "model_name": model_names.get(model_id, model_id),
                "count": count,
                "mean_confidence": mean_confidence,
            }
        )

    maximum_count = max(counts, default=0)
    minimum_count = min(counts, default=0)
    count_disagreement = (
        (maximum_count - minimum_count) / maximum_count if maximum_count > 0 else 0.0
    )
    confidence_disagreement = (
        max(present_means) - min(present_means) if len(present_means) >= 2 else 0.0
    )
    missing_model_fraction = sum(1 for count in counts if count == 0) / len(ordered_ids)
    normalized_score = (
        COMMITTEE_WEIGHTS["count_disagreement"] * count_disagreement
        + COMMITTEE_WEIGHTS["confidence_disagreement"] * confidence_disagreement
        + COMMITTEE_WEIGHTS["missing_model_fraction"] * missing_model_fraction
    )
    score = min(max(normalized_score * 100.0, 0.0), 100.0)

    model_summary = ", ".join(
        (
            f"{item['model_name']}={item['count']} detections"
            + (
                f" @ {item['mean_confidence']:.2f} mean confidence"
                if item["mean_confidence"] is not None
                else " @ no predictions"
            )
        )
        for item in per_model
    )
    reason_summary = (
        f"Committee disagreement score {score:.1f}/100: {model_summary}. "
        f"Count disagreement {count_disagreement:.2f}, confidence disagreement "
        f"{confidence_disagreement:.2f}, missing-model fraction {missing_model_fraction:.2f}."
    )

    return {
        "formula_id": COMMITTEE_FORMULA_ID,
        "formula_version": COMMITTEE_FORMULA_VERSION,
        "weights": dict(COMMITTEE_WEIGHTS),
        "score": score,
        "count_disagreement": count_disagreement,
        "confidence_disagreement": confidence_disagreement,
        "missing_model_fraction": missing_model_fraction,
        "per_model": per_model,
        "reason_summary": reason_summary,
    }

"""Conservative active-learning ranking.

This module ranks data for human review. It never promotes a prediction to a
verified annotation automatically.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActiveLearningSignals:
    mean_confidence: float
    class_entropy: float
    disagreement: float
    novelty: float
    qc_severity: float
    already_reviewed: bool = False


@dataclass(frozen=True, slots=True)
class ActiveLearningScore:
    score: float
    reasons: tuple[str, ...]


def rank_sample(signals: ActiveLearningSignals) -> ActiveLearningScore:
    if signals.already_reviewed:
        return ActiveLearningScore(0.0, ("already reviewed",))

    uncertainty = 1.0 - min(max(signals.mean_confidence, 0.0), 1.0)
    components = {
        "low confidence": uncertainty * 0.35,
        "class ambiguity": min(max(signals.class_entropy, 0.0), 1.0) * 0.20,
        "model disagreement": min(max(signals.disagreement, 0.0), 1.0) * 0.20,
        "visual novelty": min(max(signals.novelty, 0.0), 1.0) * 0.15,
        "quality-control risk": min(max(signals.qc_severity, 0.0), 1.0) * 0.10,
    }
    score = sum(components.values())
    reasons = tuple(
        name
        for name, contribution in sorted(components.items(), key=lambda item: item[1], reverse=True)
        if contribution >= 0.05
    )
    return ActiveLearningScore(score=round(score, 6), reasons=reasons)

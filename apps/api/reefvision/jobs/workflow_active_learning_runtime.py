"""Enrich fusion active-learning nodes with probabilities from reviewable predictions."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.db.models import ClassificationPrediction, WorkflowArtifact, WorkflowRun
from reefvision.jobs import workflow_runs, workflow_science_runtime


def _normalized_mean_probability(
    predictions: list[ClassificationPrediction],
) -> tuple[float, ...] | None:
    """Aggregate region-level classifier distributions into one image distribution.

    Class labels are aligned by their stored probability-map keys before averaging. The
    resulting vector is normalized again because multi-label providers and rounded storage
    values do not necessarily sum to exactly one. This provides deterministic image-level
    uncertainty without discarding the original prediction records or review provenance.
    """

    labels = sorted(
        {
            str(label)
            for prediction in predictions
            for label in (prediction.probabilities_json or {})
        }
    )
    if not labels:
        return None
    sums = {label: 0.0 for label in labels}
    usable = 0
    for prediction in predictions:
        probabilities = prediction.probabilities_json or {}
        if not probabilities:
            continue
        usable += 1
        for label in labels:
            try:
                value = float(probabilities.get(label, 0.0))
            except (TypeError, ValueError):
                value = 0.0
            sums[label] += max(0.0, value)
    if usable == 0:
        return None
    averaged = [sums[label] / usable for label in labels]
    total = sum(averaged)
    if total <= 0:
        return None
    return tuple(value / total for value in averaged)


def _prediction_probabilities(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    inputs: list[WorkflowArtifact],
) -> dict[str, list[float]]:
    payloads = [workflow_runs._artifact_payload(item) for item in inputs]
    prediction_ids = workflow_runs._list_values(
        payloads,
        "classification_prediction_ids",
    )
    if not prediction_ids:
        return {}
    with factory() as session:
        predictions = list(
            session.scalars(
                select(ClassificationPrediction)
                .where(
                    ClassificationPrediction.project_id == run.project_id,
                    ClassificationPrediction.id.in_(prediction_ids),
                )
                .order_by(
                    ClassificationPrediction.image_id,
                    ClassificationPrediction.created_at,
                    ClassificationPrediction.id,
                )
            )
        )
    by_image: dict[str, list[ClassificationPrediction]] = defaultdict(list)
    for prediction in predictions:
        by_image[prediction.image_id].append(prediction)
    result: dict[str, list[float]] = {}
    for image_id, items in by_image.items():
        aggregated = _normalized_mean_probability(items)
        if aggregated is not None:
            result[image_id] = list(aggregated)
    return result


def _active_learning_from_predictions(
    factory: sessionmaker[Session],
    run: WorkflowRun,
    configuration: dict[str, Any],
    inputs: list[WorkflowArtifact],
) -> workflow_runs.ArtifactOutputs:
    enriched = dict(configuration)
    configured = enriched.get("probabilities")
    if not isinstance(configured, dict) or not configured:
        inferred = _prediction_probabilities(factory, run, inputs)
        if inferred:
            enriched["probabilities"] = inferred
            enriched["probability_source"] = "classification_predictions"
    outputs = workflow_science_runtime._workflow_active_learning(
        factory,
        run,
        enriched,
        inputs,
    )
    review_batch = outputs.get("review_batch")
    if review_batch is not None:
        artifact_type, payload = review_batch
        payload = dict(payload)
        provenance = dict(payload.get("provenance", {}))
        provenance["probability_source"] = str(
            enriched.get("probability_source", "workflow_configuration")
        )
        payload["provenance"] = provenance
        outputs["review_batch"] = (artifact_type, payload)
    return outputs


workflow_runs._active_learning = _active_learning_from_predictions

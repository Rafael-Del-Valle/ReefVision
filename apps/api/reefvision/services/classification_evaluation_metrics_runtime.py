"""Add scientifically standard multiclass agreement metrics to classification evaluation."""

from __future__ import annotations

from math import sqrt
from typing import Any

from reefvision.schemas.classification_evaluation import (
    ClassificationEvaluationRequest,
    ClassificationEvaluationResponse,
)
from reefvision.services.classification_evaluation import ClassificationEvaluationService

_ORIGINAL_EVALUATE = ClassificationEvaluationService.evaluate


def _matthews_correlation_coefficient(
    response: ClassificationEvaluationResponse,
) -> float:
    """Generalized multiclass MCC from the confusion matrix."""

    n = response.sample_count
    if n <= 0:
        return 0.0
    actual: dict[str, int] = {}
    predicted: dict[str, int] = {}
    correct = 0
    for cell in response.confusion_matrix:
        actual[cell.actual_label_class_id] = actual.get(cell.actual_label_class_id, 0) + cell.count
        predicted[cell.predicted_label_class_id] = (
            predicted.get(cell.predicted_label_class_id, 0) + cell.count
        )
        if cell.actual_label_class_id == cell.predicted_label_class_id:
            correct += cell.count
    labels = set(actual) | set(predicted)
    cross = sum(actual.get(label, 0) * predicted.get(label, 0) for label in labels)
    numerator = correct * n - cross
    predicted_square = sum(value * value for value in predicted.values())
    actual_square = sum(value * value for value in actual.values())
    denominator = sqrt((n * n - predicted_square) * (n * n - actual_square))
    if denominator <= 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denominator))


def _cohen_kappa(response: ClassificationEvaluationResponse) -> float:
    n = response.sample_count
    if n <= 0:
        return 0.0
    actual: dict[str, int] = {}
    predicted: dict[str, int] = {}
    for cell in response.confusion_matrix:
        actual[cell.actual_label_class_id] = actual.get(cell.actual_label_class_id, 0) + cell.count
        predicted[cell.predicted_label_class_id] = (
            predicted.get(cell.predicted_label_class_id, 0) + cell.count
        )
    labels = set(actual) | set(predicted)
    observed = response.accuracy
    expected = sum(
        actual.get(label, 0) * predicted.get(label, 0) for label in labels
    ) / float(n * n)
    denominator = 1.0 - expected
    if denominator <= 0:
        return 0.0
    return max(-1.0, min(1.0, (observed - expected) / denominator))


def _evaluate_with_agreement_metrics(
    self: ClassificationEvaluationService,
    project_id: str,
    request: ClassificationEvaluationRequest,
) -> ClassificationEvaluationResponse:
    response = _ORIGINAL_EVALUATE(self, project_id, request)
    # Standard multiclass balanced accuracy is the unweighted mean of class recalls.
    balanced_accuracy = response.macro_recall
    return response.model_copy(
        update={
            "balanced_accuracy": balanced_accuracy,
            "matthews_correlation_coefficient": _matthews_correlation_coefficient(response),
            "cohen_kappa": _cohen_kappa(response),
        }
    )


def install_classification_evaluation_metrics_runtime() -> None:
    current: Any = ClassificationEvaluationService.evaluate
    if current is not _evaluate_with_agreement_metrics:
        ClassificationEvaluationService.evaluate = _evaluate_with_agreement_metrics


install_classification_evaluation_metrics_runtime()

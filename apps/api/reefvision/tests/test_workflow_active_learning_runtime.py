from types import SimpleNamespace

import pytest

from reefvision.jobs.workflow_active_learning_runtime import _normalized_mean_probability


def test_workflow_active_learning_aggregates_classifier_probability_maps() -> None:
    predictions = [
        SimpleNamespace(probabilities_json={"open": 0.8, "closed": 0.2}),
        SimpleNamespace(probabilities_json={"open": 0.6, "closed": 0.4}),
    ]

    result = _normalized_mean_probability(predictions)  # type: ignore[arg-type]

    assert result == pytest.approx((0.3, 0.7))


def test_workflow_active_learning_aligns_missing_labels_and_normalizes() -> None:
    predictions = [
        SimpleNamespace(probabilities_json={"a": 0.6, "b": 0.4}),
        SimpleNamespace(probabilities_json={"b": 0.5, "c": 0.5}),
    ]

    result = _normalized_mean_probability(predictions)  # type: ignore[arg-type]

    assert result == pytest.approx((0.3, 0.45, 0.25))


def test_workflow_active_learning_ignores_empty_probability_records() -> None:
    predictions = [
        SimpleNamespace(probabilities_json={}),
        SimpleNamespace(probabilities_json={"open": 2.0, "closed": 1.0}),
    ]

    result = _normalized_mean_probability(predictions)  # type: ignore[arg-type]

    assert result == pytest.approx((1.0 / 3.0, 2.0 / 3.0))

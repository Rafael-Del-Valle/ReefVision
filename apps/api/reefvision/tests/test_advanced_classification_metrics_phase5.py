from __future__ import annotations

import numpy as np
import pytest

from reefvision.ml.classification_metrics import (
    binary_curve,
    cohen_kappa,
    isotonic_correctness,
    multiclass_matthews,
    optimal_f1_threshold,
    precision_recall_auc,
    roc_auc,
    temperature_scale_probabilities,
    top_k_accuracy,
)


def test_multiclass_reliability_metrics_and_curves() -> None:
    confusion = np.asarray([[8, 2], [1, 9]], dtype=np.int64)
    assert multiclass_matthews(confusion) == pytest.approx(0.704, rel=0.02)
    assert cohen_kappa(confusion) == pytest.approx(0.7)

    curve = binary_curve(
        [0.95, 0.8, 0.6, 0.2],
        [True, True, False, False],
    )
    assert roc_auc(curve) == pytest.approx(1.0)
    assert precision_recall_auc(curve) is not None
    threshold, f1 = optimal_f1_threshold(curve)
    assert threshold >= 0.8
    assert f1 == pytest.approx(1.0)


def test_top_k_temperature_and_isotonic_calibration() -> None:
    rows = [
        {"A": 0.8, "B": 0.15, "C": 0.05},
        {"A": 0.2, "B": 0.7, "C": 0.1},
        {"A": 0.4, "B": 0.35, "C": 0.25},
    ]
    actual = ["A", "B", "C"]
    assert top_k_accuracy(rows, actual, k=1) == pytest.approx(2 / 3)
    assert top_k_accuracy(rows, actual, k=3) == pytest.approx(1.0)

    temperature, loss = temperature_scale_probabilities(rows, actual)
    assert temperature > 0
    assert loss is not None
    assert loss >= 0

    blocks = isotonic_correctness(
        [0.2, 0.4, 0.6, 0.8],
        [False, True, False, True],
    )
    assert sum(block.count for block in blocks) == 4
    calibrated = [block.calibrated_probability for block in blocks]
    assert calibrated == sorted(calibrated)

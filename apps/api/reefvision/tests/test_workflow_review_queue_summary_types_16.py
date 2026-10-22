"""Regression tests for scientific QC mean typing on saved workflow retries."""

from __future__ import annotations

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.workflow_review_queue_integrity import (
    validate_saved_queue_snapshot,
)
from reefvision.tests.test_workflow_review_queue_integrity_16 import snapshot


@pytest.mark.parametrize("value", [50.0, 50])
def test_saved_summary_accepts_finite_numeric_average(value: float | int) -> None:
    queue, items = snapshot()
    queue.summary_json["average_score"] = value
    validate_saved_queue_snapshot(queue, items)


@pytest.mark.parametrize(
    "value",
    ["50.0", True, False, None, float("nan"), float("inf"), -float("inf")],
)
def test_saved_summary_rejects_non_numeric_or_nonfinite_average(value: object) -> None:
    queue, items = snapshot()
    queue.summary_json["average_score"] = value
    with pytest.raises(ValidationError, match="snapshot failed integrity"):
        validate_saved_queue_snapshot(queue, items)

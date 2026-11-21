"""Deterministic, overflow-safe descriptive means for scientific summaries.

The caller must validate observations and the true experimental unit.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from reefvision.domain.errors import ValidationError


def finite_descriptive_mean(values: Iterable[float]) -> float:
    """Compute an order-independent finite mean with a scaled overflow fallback."""
    ordered = sorted(values)
    if not ordered:
        raise ValidationError("Cannot summarize an empty scientific sample")
    if not all(math.isfinite(value) for value in ordered):
        raise ValidationError("Scientific mean requires finite values")
    count = len(ordered)
    try:
        result = math.fsum(ordered) / count
    except OverflowError:
        result = math.fsum(value / count for value in ordered)
    if not math.isfinite(result):
        raise ValidationError("Scientific mean is not finite")
    return result

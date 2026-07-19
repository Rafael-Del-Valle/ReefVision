"""Provider-free agreement, reliability, rank, and bootstrap statistics."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ConfidenceInterval:
    lower: float
    upper: float


def pearson(first: Sequence[float], second: Sequence[float]) -> float | None:
    if len(first) < 2 or len(first) != len(second):
        return None
    x = np.asarray(first, dtype=np.float64)
    y = np.asarray(second, dtype=np.float64)
    x_centered = x - x.mean()
    y_centered = y - y.mean()
    denominator = float(math.sqrt(np.dot(x_centered, x_centered) * np.dot(y_centered, y_centered)))
    if denominator <= 0:
        return None
    return float(np.clip(np.dot(x_centered, y_centered) / denominator, -1, 1))


def _average_ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(float(value) for value in values), key=lambda item: item[1])
    ranks = [0.0] * len(indexed)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for index in range(start, end):
            ranks[indexed[index][0]] = average_rank
        start = end
    return ranks


def spearman(first: Sequence[float], second: Sequence[float]) -> float | None:
    if len(first) < 2 or len(first) != len(second):
        return None
    return pearson(_average_ranks(first), _average_ranks(second))


def concordance_correlation(
    first: Sequence[float],
    second: Sequence[float],
) -> float | None:
    if len(first) < 2 or len(first) != len(second):
        return None
    x = np.asarray(first, dtype=np.float64)
    y = np.asarray(second, dtype=np.float64)
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    x_variance = float(np.mean((x - x_mean) ** 2))
    y_variance = float(np.mean((y - y_mean) ** 2))
    covariance = float(np.mean((x - x_mean) * (y - y_mean)))
    denominator = x_variance + y_variance + (x_mean - y_mean) ** 2
    if denominator <= 0:
        return 1.0 if np.array_equal(x, y) else None
    return float(np.clip(2 * covariance / denominator, -1, 1))


def icc_two_way_absolute_single(
    first: Sequence[float],
    second: Sequence[float],
) -> float | None:
    """ICC(A,1), equivalent to two-way random absolute-agreement single measures."""

    if len(first) < 2 or len(first) != len(second):
        return None
    ratings = np.column_stack((first, second)).astype(np.float64)
    targets, raters = ratings.shape
    grand_mean = float(ratings.mean())
    target_means = ratings.mean(axis=1)
    rater_means = ratings.mean(axis=0)
    ss_targets = raters * float(np.sum((target_means - grand_mean) ** 2))
    ss_raters = targets * float(np.sum((rater_means - grand_mean) ** 2))
    residuals = ratings - target_means[:, None] - rater_means[None, :] + grand_mean
    ss_error = float(np.sum(residuals * residuals))
    ms_targets = ss_targets / (targets - 1)
    ms_raters = ss_raters / (raters - 1)
    ms_error = ss_error / ((targets - 1) * (raters - 1))
    denominator = ms_targets + (raters - 1) * ms_error + raters * (ms_raters - ms_error) / targets
    if math.isclose(denominator, 0.0, abs_tol=1e-15):
        return 1.0 if np.array_equal(ratings[:, 0], ratings[:, 1]) else None
    return float(np.clip((ms_targets - ms_error) / denominator, -1, 1))


def bootstrap_paired(
    first: Sequence[float],
    second: Sequence[float],
    statistic: Callable[[np.ndarray, np.ndarray], float | None],
    *,
    iterations: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> ConfidenceInterval | None:
    if len(first) < 2 or len(first) != len(second) or iterations < 1:
        return None
    x = np.asarray(first, dtype=np.float64)
    y = np.asarray(second, dtype=np.float64)
    generator = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(iterations):
        indices = generator.integers(0, len(x), size=len(x))
        observed = statistic(x[indices], y[indices])
        if observed is not None and math.isfinite(float(observed)):
            values.append(float(observed))
    if not values:
        return None
    alpha = (1 - confidence) / 2
    return ConfidenceInterval(
        lower=float(np.quantile(values, alpha)),
        upper=float(np.quantile(values, 1 - alpha)),
    )


def mean_bias(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.mean(first - second))


def mean_absolute_error(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.mean(np.abs(first - second)))

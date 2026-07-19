"""Deterministic active-learning selection strategies and explanations."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

SelectionStrategy = Literal[
    "uncertainty",
    "least_confidence",
    "margin",
    "entropy",
    "farthest_point",
    "k_center",
    "kmeans_representative",
    "cluster_balanced",
    "density_aware",
    "pareto_uncertainty_diversity",
    "ensemble_disagreement",
]


@dataclass(frozen=True)
class SelectionCandidate:
    candidate_id: str
    embedding: tuple[float, ...] | None = None
    probabilities: tuple[float, ...] = ()
    ensemble_probabilities: tuple[tuple[float, ...], ...] = ()
    base_score: float = 0.0
    group_id: str | None = None
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True)
class SelectionResult:
    candidate_id: str
    rank: int
    score: float
    uncertainty: float
    diversity: float
    density: float
    disagreement: float
    cluster_id: int | None
    group_id: str | None
    explanation: tuple[str, ...]


def _normalize(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [0.0 if math.isclose(high, 0.0) else 1.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def entropy(probabilities: Sequence[float]) -> float:
    values = np.asarray(probabilities, dtype=np.float64)
    values = values[np.isfinite(values) & (values > 0)]
    if values.size == 0:
        return 0.0
    values = values / values.sum()
    raw = float(-np.sum(values * np.log(values)))
    maximum = math.log(len(values)) if len(values) > 1 else 1.0
    return raw / maximum if maximum else 0.0


def margin_uncertainty(probabilities: Sequence[float]) -> float:
    values = sorted((float(value) for value in probabilities), reverse=True)
    if not values:
        return 0.0
    if len(values) == 1:
        return 1 - values[0]
    return 1 - max(0.0, min(1.0, values[0] - values[1]))


def least_confidence(probabilities: Sequence[float]) -> float:
    return 1 - max((float(value) for value in probabilities), default=1.0)


def ensemble_disagreement(
    ensemble_probabilities: Sequence[Sequence[float]],
) -> float:
    if len(ensemble_probabilities) < 2:
        return 0.0
    matrix = np.asarray(ensemble_probabilities, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        return 0.0
    row_sums = matrix.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1
    matrix = matrix / row_sums
    mean_probabilities = matrix.mean(axis=0)
    predictive_entropy = entropy(mean_probabilities)
    expected_entropy = float(np.mean([entropy(row) for row in matrix]))
    return max(0.0, predictive_entropy - expected_entropy)


def _embedding_matrix(
    candidates: Sequence[SelectionCandidate],
) -> tuple[np.ndarray, list[int]]:
    indices = [index for index, item in enumerate(candidates) if item.embedding]
    if not indices:
        return np.empty((0, 0), dtype=np.float64), []
    dimension = len(candidates[indices[0]].embedding or ())
    if any(len(candidates[index].embedding or ()) != dimension for index in indices):
        raise ValueError("All available embeddings must share one dimension")
    matrix = np.asarray(
        [candidates[index].embedding for index in indices],
        dtype=np.float64,
    )
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return matrix / norms, indices


def _pairwise_distances(matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return np.empty((0, 0), dtype=np.float64)
    return np.clip(1 - matrix @ matrix.T, 0, 2)


def _kmeans(
    matrix: np.ndarray,
    cluster_count: int,
    *,
    seed: int,
    iterations: int = 50,
) -> tuple[np.ndarray, np.ndarray]:
    if len(matrix) == 0:
        return np.empty((0,), dtype=np.int64), np.empty((0, 0), dtype=np.float64)
    cluster_count = max(1, min(cluster_count, len(matrix)))
    generator = random.Random(seed)
    centers = [matrix[generator.randrange(len(matrix))]]
    while len(centers) < cluster_count:
        distances = np.min(
            np.stack([1 - matrix @ center for center in centers], axis=1),
            axis=1,
        )
        centers.append(matrix[int(np.argmax(distances))])
    center_matrix = np.asarray(centers)
    assignments = np.full(len(matrix), -1, dtype=np.int64)
    for _ in range(iterations):
        next_assignments = np.argmin(1 - matrix @ center_matrix.T, axis=1)
        if np.array_equal(assignments, next_assignments):
            break
        assignments = next_assignments
        next_centers: list[np.ndarray] = []
        for cluster_id in range(cluster_count):
            members = matrix[assignments == cluster_id]
            if len(members) == 0:
                next_centers.append(center_matrix[cluster_id])
                continue
            center = members.mean(axis=0)
            norm = float(np.linalg.norm(center))
            next_centers.append(center / norm if norm else center)
        center_matrix = np.asarray(next_centers)
    return assignments, center_matrix


def _pareto_front(values: Sequence[tuple[float, float]]) -> set[int]:
    front: set[int] = set()
    for index, (first, second) in enumerate(values):
        dominated = any(
            other_index != index
            and other_first >= first
            and other_second >= second
            and (other_first > first or other_second > second)
            for other_index, (other_first, other_second) in enumerate(values)
        )
        if not dominated:
            front.add(index)
    return front


def select_candidates(
    candidates: Sequence[SelectionCandidate],
    *,
    budget: int,
    strategy: SelectionStrategy,
    seed: int = 0,
    group_limit: int | None = None,
    uncertainty_weight: float = 0.5,
    diversity_weight: float = 0.3,
    density_weight: float = 0.1,
    disagreement_weight: float = 0.1,
    base_score_weight: float = 0.1,
) -> list[SelectionResult]:
    if budget < 1:
        raise ValueError("Selection budget must be positive")
    if group_limit is not None and group_limit < 1:
        raise ValueError("Group limit must be positive")
    if not candidates:
        return []
    matrix, embedding_indices = _embedding_matrix(candidates)
    pairwise = _pairwise_distances(matrix)
    candidate_to_embedding = {
        candidate_index: embedding_index
        for embedding_index, candidate_index in enumerate(embedding_indices)
    }
    uncertainty_raw: list[float] = []
    disagreement_raw: list[float] = []
    for candidate in candidates:
        if strategy == "margin":
            uncertainty_raw.append(margin_uncertainty(candidate.probabilities))
        elif strategy == "least_confidence":
            uncertainty_raw.append(least_confidence(candidate.probabilities))
        else:
            uncertainty_raw.append(entropy(candidate.probabilities))
        disagreement_raw.append(
            ensemble_disagreement(candidate.ensemble_probabilities)
        )
    uncertainty = _normalize(uncertainty_raw)
    disagreement = _normalize(disagreement_raw)
    base_scores = _normalize([float(item.base_score) for item in candidates])
    density_raw = [0.0] * len(candidates)
    if len(matrix) > 1:
        nearest_count = min(5, len(matrix) - 1)
        for embedding_index, candidate_index in enumerate(embedding_indices):
            distances = np.sort(pairwise[embedding_index][pairwise[embedding_index] > 0])
            if distances.size:
                density_raw[candidate_index] = 1 / (
                    float(np.mean(distances[:nearest_count])) + 1e-9
                )
    density = _normalize(density_raw)
    cluster_count = min(max(1, budget), max(1, len(matrix)))
    assignments, centers = _kmeans(matrix, cluster_count, seed=seed)
    cluster_ids: list[int | None] = [None] * len(candidates)
    for embedding_index, candidate_index in enumerate(embedding_indices):
        cluster_ids[candidate_index] = int(assignments[embedding_index])
    pareto = _pareto_front(
        list(zip(uncertainty, density, strict=True))
    )

    selected: list[int] = []
    selected_details: dict[int, tuple[float, float]] = {}
    group_counts: dict[str, int] = defaultdict(int)
    remaining = set(range(len(candidates)))

    def allowed(index: int) -> bool:
        group = candidates[index].group_id
        return group_limit is None or group is None or group_counts[group] < group_limit

    def current_diversity(index: int) -> float:
        embedding_index = candidate_to_embedding.get(index)
        if embedding_index is None:
            return 0.0
        selected_embeddings = [
            candidate_to_embedding[item]
            for item in selected
            if item in candidate_to_embedding
        ]
        if not selected_embeddings:
            return float(np.mean(pairwise[embedding_index])) if len(matrix) > 1 else 1.0
        return float(np.min(pairwise[embedding_index, selected_embeddings]))

    while remaining and len(selected) < min(budget, len(candidates)):
        scored: list[tuple[float, str, int, float]] = []
        for index in remaining:
            if not allowed(index):
                continue
            diversity = current_diversity(index)
            if strategy in {"farthest_point", "k_center"}:
                strategy_score = diversity
            elif strategy == "kmeans_representative":
                embedding_index = candidate_to_embedding.get(index)
                cluster_id = cluster_ids[index]
                strategy_score = (
                    float(np.dot(matrix[embedding_index], centers[cluster_id]))
                    if embedding_index is not None and cluster_id is not None
                    else -1.0
                )
            elif strategy == "cluster_balanced":
                cluster_id = cluster_ids[index]
                cluster_selected = sum(
                    cluster_ids[item] == cluster_id for item in selected
                )
                strategy_score = uncertainty[index] + diversity - cluster_selected
            elif strategy == "density_aware":
                strategy_score = uncertainty[index] * 0.7 + density[index] * 0.3
            elif strategy == "pareto_uncertainty_diversity":
                strategy_score = (
                    (1.0 if index in pareto else 0.0)
                    + uncertainty[index]
                    + diversity
                )
            elif strategy == "ensemble_disagreement":
                strategy_score = disagreement[index]
            else:
                strategy_score = uncertainty[index]
            combined = strategy_score + (
                uncertainty_weight * uncertainty[index]
                + diversity_weight * diversity
                + density_weight * density[index]
                + disagreement_weight * disagreement[index]
                + base_score_weight * base_scores[index]
            )
            scored.append(
                (combined, candidates[index].candidate_id, index, diversity)
            )
        if not scored:
            break
        score, _candidate_id, index, diversity = max(
            scored,
            key=lambda item: (item[0], item[1]),
        )
        selected.append(index)
        selected_details[index] = (score, diversity)
        remaining.remove(index)
        if candidates[index].group_id is not None:
            group_counts[candidates[index].group_id] += 1

    results: list[SelectionResult] = []
    for rank, index in enumerate(selected, start=1):
        score, diversity = selected_details[index]
        explanations = [f"strategy={strategy}"]
        if candidates[index].probabilities:
            explanations.append(f"uncertainty={uncertainty[index]:.4f}")
        if candidates[index].embedding:
            explanations.append(f"diversity={diversity:.4f}")
        if candidates[index].ensemble_probabilities:
            explanations.append(f"disagreement={disagreement[index]:.4f}")
        if cluster_ids[index] is not None:
            explanations.append(f"cluster={cluster_ids[index]}")
        results.append(
            SelectionResult(
                candidate_id=candidates[index].candidate_id,
                rank=rank,
                score=score,
                uncertainty=uncertainty[index],
                diversity=diversity,
                density=density[index],
                disagreement=disagreement[index],
                cluster_id=cluster_ids[index],
                group_id=candidates[index].group_id,
                explanation=tuple(explanations),
            )
        )
    return results

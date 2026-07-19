"""Multi-strategy active-learning selection schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator

StrategyName = Literal[
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


class ActiveLearningCandidate(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=500)
    embedding: list[FiniteFloat] | None = Field(default=None, max_length=100_000)
    probabilities: list[FiniteFloat] = Field(default_factory=list, max_length=100_000)
    ensemble_probabilities: list[list[FiniteFloat]] = Field(
        default_factory=list,
        max_length=1000,
    )
    base_score: FiniteFloat = 0
    group_id: str | None = Field(default=None, max_length=500)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_probabilities(self) -> ActiveLearningCandidate:
        for probabilities in [self.probabilities, *self.ensemble_probabilities]:
            if any(value < 0 for value in probabilities):
                raise ValueError("Probabilities cannot be negative")
            if probabilities and sum(probabilities) <= 0:
                raise ValueError("Probability vectors must have positive mass")
        dimensions = {len(item) for item in self.ensemble_probabilities}
        if len(dimensions) > 1:
            raise ValueError("Ensemble probability vectors must share a dimension")
        return self


class ActiveLearningStrategyRequest(BaseModel):
    strategy: StrategyName
    budget: int = Field(ge=1, le=100_000)
    candidates: list[ActiveLearningCandidate] = Field(min_length=1, max_length=1_000_000)
    seed: int = 0
    group_limit: int | None = Field(default=None, ge=1)
    uncertainty_weight: FiniteFloat = Field(default=0.5, ge=0)
    diversity_weight: FiniteFloat = Field(default=0.3, ge=0)
    density_weight: FiniteFloat = Field(default=0.1, ge=0)
    disagreement_weight: FiniteFloat = Field(default=0.1, ge=0)
    base_score_weight: FiniteFloat = Field(default=0.1, ge=0)

    @model_validator(mode="after")
    def unique_candidates(self) -> ActiveLearningStrategyRequest:
        identifiers = [item.candidate_id for item in self.candidates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Active-learning candidate identifiers must be unique")
        return self


class ActiveLearningSelectionRow(BaseModel):
    candidate_id: str
    rank: int = Field(ge=1)
    score: float
    uncertainty: float = Field(ge=0, le=1)
    diversity: float = Field(ge=0)
    density: float = Field(ge=0, le=1)
    disagreement: float = Field(ge=0, le=1)
    cluster_id: int | None = Field(default=None, ge=0)
    group_id: str | None
    explanation: list[str]


class ActiveLearningStrategyResponse(BaseModel):
    strategy: StrategyName
    requested_budget: int = Field(ge=1)
    selected_count: int = Field(ge=0)
    missing_embedding_candidate_ids: list[str]
    selections: list[ActiveLearningSelectionRow]
    warnings: list[str]

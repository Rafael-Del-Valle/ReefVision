"""Multi-strategy active-learning selection endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from reefvision.schemas.active_learning_strategies import (
    ActiveLearningStrategyRequest,
    ActiveLearningStrategyResponse,
)
from reefvision.services.active_learning_strategies import (
    ActiveLearningStrategyService,
)

router = APIRouter(tags=["active-learning-strategies"])


@router.post(
    "/active-learning/select-strategy",
    response_model=ActiveLearningStrategyResponse,
)
def select_active_learning_strategy(
    payload: ActiveLearningStrategyRequest,
) -> ActiveLearningStrategyResponse:
    return ActiveLearningStrategyService().select(payload)

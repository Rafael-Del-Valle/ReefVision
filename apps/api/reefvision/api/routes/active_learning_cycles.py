"""Persisted active-learning retraining-cycle endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.active_learning_cycles import (
    ActiveLearningCycleCreateRequest,
    ActiveLearningCycleListResponse,
    ActiveLearningCycleResponse,
    ActiveLearningCycleStopRequest,
    ActiveLearningDatasetRecordRequest,
    ActiveLearningEvaluationRequest,
    ActiveLearningNextCycleRequest,
    ActiveLearningPromotionResponse,
    ActiveLearningReviewProgressRequest,
    ActiveLearningSelectionRecordRequest,
    ActiveLearningTrainingRecordRequest,
)
from reefvision.services.active_learning_cycle_api import (
    PublicActiveLearningCycleService,
)

router = APIRouter(tags=["active-learning-cycles"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/projects/{project_id}/active-learning-cycles",
    response_model=ActiveLearningCycleListResponse,
)
def list_active_learning_cycles(
    project_id: str,
    session: DbSession,
) -> ActiveLearningCycleListResponse:
    return ActiveLearningCycleListResponse(
        cycles=PublicActiveLearningCycleService(session).list(project_id)
    )


@router.post(
    "/projects/{project_id}/active-learning-cycles",
    response_model=ActiveLearningCycleResponse,
)
def create_active_learning_cycle(
    project_id: str,
    payload: ActiveLearningCycleCreateRequest,
    session: DbSession,
) -> ActiveLearningCycleResponse:
    return PublicActiveLearningCycleService(session).create(project_id, payload)


@router.get(
    "/active-learning-cycles/{cycle_id}",
    response_model=ActiveLearningCycleResponse,
)
def get_active_learning_cycle(
    cycle_id: str,
    session: DbSession,
) -> ActiveLearningCycleResponse:
    return PublicActiveLearningCycleService(session).get(cycle_id)


@router.post(
    "/active-learning-cycles/{cycle_id}/selection",
    response_model=ActiveLearningCycleResponse,
)
def record_active_learning_selection(
    cycle_id: str,
    payload: ActiveLearningSelectionRecordRequest,
    session: DbSession,
) -> ActiveLearningCycleResponse:
    return PublicActiveLearningCycleService(session).record_selection(cycle_id, payload)


@router.post(
    "/active-learning-cycles/{cycle_id}/review-progress",
    response_model=ActiveLearningCycleResponse,
)
def record_active_learning_review_progress(
    cycle_id: str,
    payload: ActiveLearningReviewProgressRequest,
    session: DbSession,
) -> ActiveLearningCycleResponse:
    return PublicActiveLearningCycleService(session).record_review_progress(
        cycle_id,
        payload,
    )


@router.post(
    "/active-learning-cycles/{cycle_id}/dataset",
    response_model=ActiveLearningCycleResponse,
)
def attach_active_learning_dataset(
    cycle_id: str,
    payload: ActiveLearningDatasetRecordRequest,
    session: DbSession,
) -> ActiveLearningCycleResponse:
    return PublicActiveLearningCycleService(session).record_dataset(cycle_id, payload)


@router.post(
    "/active-learning-cycles/{cycle_id}/training",
    response_model=ActiveLearningCycleResponse,
)
def attach_active_learning_training(
    cycle_id: str,
    payload: ActiveLearningTrainingRecordRequest,
    session: DbSession,
) -> ActiveLearningCycleResponse:
    return PublicActiveLearningCycleService(session).record_training(cycle_id, payload)


@router.post(
    "/active-learning-cycles/{cycle_id}/evaluate",
    response_model=ActiveLearningPromotionResponse,
)
def evaluate_active_learning_candidate(
    cycle_id: str,
    payload: ActiveLearningEvaluationRequest,
    session: DbSession,
) -> ActiveLearningPromotionResponse:
    return PublicActiveLearningCycleService(session).evaluate_and_promote(
        cycle_id,
        payload,
    )


@router.post(
    "/active-learning-cycles/{cycle_id}/next",
    response_model=ActiveLearningCycleResponse,
)
def create_next_active_learning_cycle(
    cycle_id: str,
    payload: ActiveLearningNextCycleRequest,
    session: DbSession,
) -> ActiveLearningCycleResponse:
    return PublicActiveLearningCycleService(session).create_next(cycle_id, payload)


@router.post(
    "/active-learning-cycles/{cycle_id}/stop",
    response_model=ActiveLearningCycleResponse,
)
def stop_active_learning_cycle(
    cycle_id: str,
    payload: ActiveLearningCycleStopRequest,
    session: DbSession,
) -> ActiveLearningCycleResponse:
    return PublicActiveLearningCycleService(session).stop(cycle_id, payload.reason)

"""Pose-specific Active Learning endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.pose_active_learning import (
    PoseActiveLearningCandidateResponse,
    PoseActiveLearningExportManifestResponse,
    PoseActiveLearningReviewRequest,
    PoseActiveLearningRoundCreateRequest,
    PoseActiveLearningRoundResponse,
)
from reefvision.services.pose_active_learning import (
    PoseActiveLearningService,
)

router = APIRouter(tags=["pose-active-learning"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/pose-active-learning-rounds",
    response_model=PoseActiveLearningRoundResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_pose_active_learning_round(
    project_id: str,
    payload: PoseActiveLearningRoundCreateRequest,
    session: DbSession,
) -> PoseActiveLearningRoundResponse:
    return PoseActiveLearningService(session).create_round(
        project_id,
        payload,
    )


@router.get(
    "/projects/{project_id}/pose-active-learning-rounds",
    response_model=list[PoseActiveLearningRoundResponse],
)
def list_pose_active_learning_rounds(
    project_id: str,
    session: DbSession,
    video_id: Annotated[str | None, Query(max_length=36)] = None,
) -> list[PoseActiveLearningRoundResponse]:
    return PoseActiveLearningService(session).list_rounds(
        project_id,
        video_id,
    )


@router.get(
    "/pose-active-learning-rounds/{round_id}/candidates",
    response_model=list[PoseActiveLearningCandidateResponse],
)
def list_pose_active_learning_candidates(
    round_id: str,
    session: DbSession,
) -> list[PoseActiveLearningCandidateResponse]:
    return PoseActiveLearningService(session).list_candidates(round_id)


@router.put(
    "/pose-active-learning-candidates/{candidate_id}/review",
    response_model=PoseActiveLearningCandidateResponse,
)
def review_pose_active_learning_candidate(
    candidate_id: str,
    payload: PoseActiveLearningReviewRequest,
    session: DbSession,
) -> PoseActiveLearningCandidateResponse:
    return PoseActiveLearningService(session).review_candidate(
        candidate_id,
        payload,
    )


@router.get(
    "/pose-active-learning-rounds/{round_id}/retraining-manifest",
    response_model=PoseActiveLearningExportManifestResponse,
)
def pose_active_learning_retraining_manifest(
    round_id: str,
    session: DbSession,
) -> PoseActiveLearningExportManifestResponse:
    return PoseActiveLearningService(session).export_manifest(round_id)

"""Prediction proposal list and review endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.predictions import (
    PredictionAcceptRequest,
    PredictionBulkReviewRequest,
    PredictionBulkReviewResponse,
    PredictionListResponse,
    PredictionReviewResponse,
)
from reefvision.services.segmentation_predictions import SegmentationPredictionService

router = APIRouter(tags=["predictions"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/images/{image_id}/prediction-proposals", response_model=PredictionListResponse
)
def list_predictions(
    image_id: str,
    session: DbSession,
    model_id: str | None = None,
    label_class_id: str | None = None,
    min_confidence: float | None = None,
    review_status: str | None = None,
) -> PredictionListResponse:
    return SegmentationPredictionService(session).list_for_image(
        image_id,
        model_id=model_id,
        label_class_id=label_class_id,
        min_confidence=min_confidence,
        review_status=review_status,
    )


@router.post(
    "/prediction-proposals/{proposal_id}/accept",
    response_model=PredictionReviewResponse,
)
def accept_prediction(
    proposal_id: str, payload: PredictionAcceptRequest, session: DbSession
) -> PredictionReviewResponse:
    return SegmentationPredictionService(session).accept(proposal_id, payload)


@router.post(
    "/prediction-proposals/{proposal_id}/reject",
    response_model=PredictionReviewResponse,
)
def reject_prediction(
    proposal_id: str, session: DbSession
) -> PredictionReviewResponse:
    return SegmentationPredictionService(session).reject(proposal_id)


@router.post(
    "/prediction-proposals/bulk-review", response_model=PredictionBulkReviewResponse
)
def bulk_review_predictions(
    payload: PredictionBulkReviewRequest, session: DbSession
) -> PredictionBulkReviewResponse:
    return SegmentationPredictionService(session).bulk_review(payload)

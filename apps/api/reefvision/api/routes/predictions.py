"""Prediction proposal list and review endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.mask_refinements import MaskRefinementGeometryRequest
from reefvision.schemas.predictions import (
    PredictionAcceptRequest,
    PredictionBulkReviewRequest,
    PredictionBulkReviewResponse,
    PredictionListResponse,
    PredictionProposalResponse,
    PredictionReviewResponse,
)
from reefvision.services.semantic_predictions import SemanticPredictionService

router = APIRouter(tags=["predictions"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> SemanticPredictionService:
    return SemanticPredictionService(session, request.app.state.settings)


@router.get("/images/{image_id}/prediction-proposals", response_model=PredictionListResponse)
def list_predictions(
    image_id: str,
    request: Request,
    session: DbSession,
    model_id: str | None = None,
    label_class_id: str | None = None,
    min_confidence: float | None = None,
    review_status: str | None = None,
) -> PredictionListResponse:
    return service(request, session).list_for_image(
        image_id,
        model_id=model_id,
        label_class_id=label_class_id,
        min_confidence=min_confidence,
        review_status=review_status,
    )


@router.get("/prediction-proposals/{proposal_id}/mask")
def get_prediction_mask(
    proposal_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    return FileResponse(
        service(request, session).raster_mask_file(proposal_id),
        media_type="image/png",
        filename=f"{proposal_id}.png",
    )


@router.put("/prediction-proposals/{proposal_id}/mask", response_model=PredictionProposalResponse)
def edit_prediction_mask(
    proposal_id: str,
    payload: MaskRefinementGeometryRequest,
    request: Request,
    session: DbSession,
) -> PredictionProposalResponse:
    return service(request, session).edit_raster_mask(proposal_id, payload.mask_png_base64)


@router.post(
    "/prediction-proposals/{proposal_id}/accept",
    response_model=PredictionReviewResponse,
)
def accept_prediction(
    proposal_id: str,
    payload: PredictionAcceptRequest,
    request: Request,
    session: DbSession,
) -> PredictionReviewResponse:
    return service(request, session).accept(proposal_id, payload)


@router.post(
    "/prediction-proposals/{proposal_id}/reject",
    response_model=PredictionReviewResponse,
)
def reject_prediction(
    proposal_id: str,
    request: Request,
    session: DbSession,
) -> PredictionReviewResponse:
    return service(request, session).reject(proposal_id)


@router.post("/prediction-proposals/bulk-review", response_model=PredictionBulkReviewResponse)
def bulk_review_predictions(
    payload: PredictionBulkReviewRequest,
    request: Request,
    session: DbSession,
) -> PredictionBulkReviewResponse:
    return service(request, session).bulk_review(payload)

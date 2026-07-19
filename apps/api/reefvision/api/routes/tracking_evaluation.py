"""Tracker-independent reference evaluation endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from reefvision.schemas.tracking_evaluation import (
    TrackingEvaluationRequest,
    TrackingEvaluationResponse,
)
from reefvision.services.tracking_evaluation import TrackingEvaluationService

router = APIRouter(tags=["tracking-evaluation"])


@router.post("/tracking/evaluate", response_model=TrackingEvaluationResponse)
def evaluate_tracking(payload: TrackingEvaluationRequest) -> TrackingEvaluationResponse:
    return TrackingEvaluationService().evaluate(payload)

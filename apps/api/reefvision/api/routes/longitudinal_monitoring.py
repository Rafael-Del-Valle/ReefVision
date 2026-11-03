"""Initial, nonpersistent longitudinal ecology analysis API."""

from __future__ import annotations

from fastapi import APIRouter

from reefvision.domain.longitudinal_monitoring import analyze_longitudinal
from reefvision.schemas.longitudinal_monitoring import (
    LongitudinalAnalysisRequest,
    LongitudinalAnalysisResponse,
)

router = APIRouter(tags=["ecological monitoring"])


@router.post(
    "/ecology/longitudinal-analysis",
    response_model=LongitudinalAnalysisResponse,
    summary="Exploratory organism-level repeated measurement changes",
)
def longitudinal_analysis(
    request: LongitudinalAnalysisRequest,
) -> LongitudinalAnalysisResponse:
    return analyze_longitudinal(request)

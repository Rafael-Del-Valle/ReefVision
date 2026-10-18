"""Exploratory paired count comparison endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from reefvision.domain.model_agreement import compare_paired_counts
from reefvision.schemas.model_agreement import (
    PairedCountComparisonRequest,
    PairedCountComparisonResponse,
)

router = APIRouter(tags=["ecological monitoring"])


@router.post(
    "/ecology/paired-count-comparison",
    response_model=PairedCountComparisonResponse,
    summary="Descriptive paired human–model counts (unverified)",
)
def paired_count_comparison(
    request: PairedCountComparisonRequest,
) -> PairedCountComparisonResponse:
    return compare_paired_counts(request)

"""Exploratory paired count comparison endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response

from reefvision.domain.model_agreement import compare_paired_counts
from reefvision.schemas.model_agreement import (
    PairedCountComparisonRequest,
    PairedCountComparisonResponse,
)
from reefvision.services.ecology_paired_count_export import render_paired_count_csv

router = APIRouter(tags=["ecological monitoring"])


@router.post(
    "/ecology/paired-count-comparison",
    response_model=PairedCountComparisonResponse,
    summary="Descriptive paired human-model counts (unverified)",
)
def paired_count_comparison(
    request: PairedCountComparisonRequest,
) -> PairedCountComparisonResponse:
    return compare_paired_counts(request)


@router.post(
    "/ecology/paired-count-comparison/report.csv",
    summary="Unverified reproducible human-model count CSV",
)
def export_paired_count_comparison(request: PairedCountComparisonRequest) -> Response:
    comparison = compare_paired_counts(request)
    return Response(
        content=render_paired_count_csv(comparison),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="reefvision-paired-counts.csv"'
        },
    )

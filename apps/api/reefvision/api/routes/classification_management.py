"""Bulk classification review, model comparison, and scientific file downloads."""

from __future__ import annotations

import io
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.classification_management import (
    BulkClassificationReviewRequest,
    BulkClassificationReviewResponse,
    ClassificationComparisonResponse,
)
from reefvision.services.classification_management import (
    ClassificationManagementService,
    ScientificClassificationFileService,
)

router = APIRouter(tags=["classification-management"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/classification-predictions/bulk-review",
    response_model=BulkClassificationReviewResponse,
)
def bulk_review_classification_predictions(
    project_id: str,
    payload: BulkClassificationReviewRequest,
    session: DbSession,
) -> BulkClassificationReviewResponse:
    return ClassificationManagementService(session).bulk_review(project_id, payload)


@router.get(
    "/projects/{project_id}/classification-model-comparison",
    response_model=ClassificationComparisonResponse,
)
def compare_classification_models(
    project_id: str,
    session: DbSession,
    label_set: str | None = None,
    target_kind: str | None = None,
    image_id: str | None = None,
    review_status: str | None = None,
    minimum_models: Annotated[int, Query(ge=1, le=50)] = 2,
) -> ClassificationComparisonResponse:
    return ClassificationManagementService(session).compare_models(
        project_id,
        label_set=label_set,
        target_kind=target_kind,
        image_id=image_id,
        review_status=review_status,
        minimum_models=minimum_models,
    )


@router.get(
    "/projects/{project_id}/classification-assignments/scientific-export.csv",
)
def download_scientific_classification_csv(
    project_id: str,
    request: Request,
    session: DbSession,
    assignment_status: str = "accepted",
) -> StreamingResponse:
    payload = ScientificClassificationFileService(
        session,
        request.app.state.settings,
    ).csv_bytes(project_id, assignment_status=assignment_status)
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="reefvision-{project_id}-classifications.csv"'
            )
        },
    )


@router.get(
    "/projects/{project_id}/classification-assignments/scientific-export.npz",
)
def download_scientific_classification_npz(
    project_id: str,
    request: Request,
    session: DbSession,
    assignment_status: str = "accepted",
) -> StreamingResponse:
    payload = ScientificClassificationFileService(
        session,
        request.app.state.settings,
    ).npz_bytes(project_id, assignment_status=assignment_status)
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="reefvision-{project_id}-classifications.npz"'
            )
        },
    )

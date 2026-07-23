"""Portable scientific classification assignment export endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.classification_data_exports import (
    ClassificationDataExportRequest,
    ClassificationDataExportResponse,
)
from reefvision.services.classification_data_exports import (
    ClassificationDataExportService,
)

router = APIRouter(tags=["classification-exports"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/classification-assignments/scientific-data-exports",
    response_model=ClassificationDataExportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_scientific_classification_data_export(
    project_id: str,
    payload: ClassificationDataExportRequest,
    request: Request,
    session: DbSession,
) -> ClassificationDataExportResponse:
    return ClassificationDataExportService(
        session,
        request.app.state.settings,
    ).export(project_id, payload)

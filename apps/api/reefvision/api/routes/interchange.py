"""External annotation interchange endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.interchange import (
    InterchangeApplyRequest,
    InterchangeApplyResponse,
    InterchangeExportRequest,
    InterchangeExportResponse,
    InterchangePreviewRequest,
    InterchangePreviewResponse,
)
from reefvision.services.coco_rle import expand_compact_rle_document
from reefvision.services.interchange import InterchangeService

router = APIRouter(tags=["interchange"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> InterchangeService:
    settings: Settings = request.app.state.settings
    return InterchangeService(session, settings)


def _normalized_preview(payload: InterchangePreviewRequest) -> InterchangePreviewRequest:
    if payload.format not in {
        "coco_detection",
        "coco_instance",
        "coco_panoptic",
        "roboflow_coco",
    }:
        return payload
    return payload.model_copy(
        update={"document": expand_compact_rle_document(payload.document)},
        deep=True,
    )


def _normalized_apply(payload: InterchangeApplyRequest) -> InterchangeApplyRequest:
    if payload.format not in {
        "coco_detection",
        "coco_instance",
        "coco_panoptic",
        "roboflow_coco",
    }:
        return payload
    return payload.model_copy(
        update={"document": expand_compact_rle_document(payload.document)},
        deep=True,
    )


@router.post(
    "/projects/{project_id}/interchange/preview",
    response_model=InterchangePreviewResponse,
)
def preview_interchange(
    project_id: str,
    payload: InterchangePreviewRequest,
    request: Request,
    session: DbSession,
) -> InterchangePreviewResponse:
    return service(request, session).preview(project_id, _normalized_preview(payload))


@router.post(
    "/projects/{project_id}/interchange/apply",
    response_model=InterchangeApplyResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply_interchange(
    project_id: str,
    payload: InterchangeApplyRequest,
    request: Request,
    session: DbSession,
) -> InterchangeApplyResponse:
    return service(request, session).apply(project_id, _normalized_apply(payload))


@router.post(
    "/projects/{project_id}/interchange/export",
    response_model=InterchangeExportResponse,
    status_code=status.HTTP_201_CREATED,
)
def export_interchange(
    project_id: str,
    payload: InterchangeExportRequest,
    request: Request,
    session: DbSession,
) -> InterchangeExportResponse:
    return service(request, session).export(project_id, payload)

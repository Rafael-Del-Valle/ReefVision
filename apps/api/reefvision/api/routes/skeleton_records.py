"""Persisted skeleton analysis endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.connected_branch_editing import (
    ConnectedBranchPreviewRequest,
    ConnectedBranchPreviewResponse,
)
from reefvision.schemas.skeletonization import (
    SkeletonAnalysisCorrectionRequest,
    SkeletonAnalysisCreateRequest,
    SkeletonAnalysisExportResponse,
    SkeletonAnalysisReviewRequest,
    SkeletonAnalysisRevisionResponse,
)
from reefvision.services.connected_branch_preview import preview_saved_branch_addition
from reefvision.services.skeletonization import SkeletonizationService

router = APIRouter(tags=["skeletonization"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> SkeletonizationService:
    settings: Settings = request.app.state.settings
    return SkeletonizationService(session, settings)


@router.get(
    "/skeleton-analyses/{analysis_id}",
    response_model=SkeletonAnalysisRevisionResponse,
)
def get_skeleton_analysis(
    analysis_id: str,
    request: Request,
    session: DbSession,
) -> SkeletonAnalysisRevisionResponse:
    return service(request, session).get_persisted_analysis(analysis_id)


@router.post(
    "/mask-annotations/{mask_annotation_id}/skeleton-analyses",
    response_model=SkeletonAnalysisRevisionResponse,
)
def create_skeleton_analysis(
    mask_annotation_id: str,
    payload: SkeletonAnalysisCreateRequest,
    request: Request,
    session: DbSession,
) -> SkeletonAnalysisRevisionResponse:
    return service(request, session).persist_analysis(
        mask_annotation_id,
        payload,
    )


@router.get(
    "/mask-annotations/{mask_annotation_id}/skeleton-analyses",
    response_model=list[SkeletonAnalysisRevisionResponse],
)
def list_skeleton_analyses(
    mask_annotation_id: str,
    request: Request,
    session: DbSession,
) -> list[SkeletonAnalysisRevisionResponse]:
    return service(request, session).list_persisted_analyses(mask_annotation_id)


@router.post(
    "/skeleton-analyses/{analysis_id}/review",
    response_model=SkeletonAnalysisRevisionResponse,
)
def review_skeleton_analysis(
    analysis_id: str,
    payload: SkeletonAnalysisReviewRequest,
    request: Request,
    session: DbSession,
) -> SkeletonAnalysisRevisionResponse:
    return service(request, session).review_persisted_analysis(
        analysis_id,
        payload,
    )


@router.post(
    "/skeleton-analyses/{analysis_id}/corrections",
    response_model=SkeletonAnalysisRevisionResponse,
)
def correct_skeleton_analysis(
    analysis_id: str,
    payload: SkeletonAnalysisCorrectionRequest,
    request: Request,
    session: DbSession,
) -> SkeletonAnalysisRevisionResponse:
    return service(request, session).correct_persisted_analysis(
        analysis_id,
        payload,
    )


@router.post(
    "/skeleton-analyses/{analysis_id}/branch-edits/preview",
    response_model=ConnectedBranchPreviewResponse,
)
def preview_connected_branch_edit(
    analysis_id: str,
    payload: ConnectedBranchPreviewRequest,
    request: Request,
    session: DbSession,
) -> ConnectedBranchPreviewResponse:
    return preview_saved_branch_addition(
        session,
        request.app.state.settings,
        analysis_id,
        payload,
    )


@router.post(
    "/skeleton-analyses/{analysis_id}/export",
    response_model=SkeletonAnalysisExportResponse,
)
def export_skeleton_analysis(
    analysis_id: str,
    request: Request,
    session: DbSession,
) -> SkeletonAnalysisExportResponse:
    return service(request, session).export_persisted_analysis(analysis_id)


@router.get("/skeleton-analyses/{analysis_id}/export/download")
def download_skeleton_analysis_export(
    analysis_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    archive = service(request, session).persisted_analysis_archive_path(analysis_id)
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=archive.name,
    )

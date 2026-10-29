"""Standalone read-only mesh measurement preview endpoint (1.4)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.db.models import Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.spatial_mesh_preview_v14 import (
    MeshLongitudinalComparisonRequest,
    MeshPreviewRequest,
)
from reefvision.schemas.spatial_point_cloud_v14 import PointCloudPreviewRequest
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.spatial_point_cloud_v14 import preview_point_cloud_from_request
from reefvision.services.spatial_source_assets_v14 import preview_project_mesh

router = APIRouter(tags=["spatial-mesh-preview"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("/projects/{project_id}/spatial/mesh-preview")
def preview_mesh_surface(
    project_id: str, payload: MeshPreviewRequest, request: Request, session: DbSession
) -> dict[str, Any]:
    if session.get(Project, project_id) is None:
        raise NotFoundError("Project not found")
    settings: Settings = request.app.state.settings
    try:
        result = preview_project_mesh(session, settings, project_id, payload)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    result["project_id"] = project_id
    return result


@router.post("/projects/{project_id}/spatial/point-cloud-preview")
def preview_point_cloud(
    project_id: str, payload: PointCloudPreviewRequest, session: DbSession
) -> dict[str, Any]:
    if session.get(Project, project_id) is None:
        raise NotFoundError("Project not found")
    try:
        result = preview_point_cloud_from_request(payload)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    result["project_id"] = project_id
    return result


@router.post("/projects/{project_id}/spatial/mesh-longitudinal-comparison")
def preview_mesh_longitudinal_comparison(
    project_id: str,
    payload: MeshLongitudinalComparisonRequest,
    request: Request,
    session: DbSession,
) -> dict[str, Any]:
    if session.get(Project, project_id) is None:
        raise NotFoundError("Project not found")
    settings: Settings = request.app.state.settings
    try:
        before = preview_project_mesh(session, settings, project_id, payload.before)
        after = preview_project_mesh(session, settings, project_id, payload.after)
        before["project_id"] = project_id
        after["project_id"] = project_id
        return compare_mesh_observations(
            before,
            after,
            payload.registration_evidence,
            payload.reidentification_evidence,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

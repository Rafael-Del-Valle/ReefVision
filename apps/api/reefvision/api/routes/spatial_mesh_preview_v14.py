"""Standalone read-only mesh measurement preview endpoint (1.4)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request

router = APIRouter(tags=["spatial-mesh-preview"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("/projects/{project_id}/spatial/mesh-preview")
def preview_mesh_surface(
    project_id: str, payload: MeshPreviewRequest, session: DbSession
) -> dict[str, Any]:
    if session.get(Project, project_id) is None:
        raise NotFoundError("Project not found")
    try:
        result = preview_from_request(payload)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    result["project_id"] = project_id
    return result

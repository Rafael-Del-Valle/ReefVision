"""Scientific pixel-grid heatmaps for independent evidence sources."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.scientific_heatmaps import ScientificHeatmapResponse
from reefvision.services.scientific_heatmaps import ScientificHeatmapService

router = APIRouter(tags=["scientific-heatmaps"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/projects/{project_id}/images/{image_id}/scientific-heatmaps",
    response_model=ScientificHeatmapResponse,
)
def get_scientific_heatmaps(
    project_id: UUID,
    image_id: UUID,
    session: DbSession,
    columns: int = Query(default=16, ge=2, le=64),
    rows: int = Query(default=16, ge=2, le=64),
    label_class_id: UUID | None = None,
) -> ScientificHeatmapResponse:
    service = ScientificHeatmapService(session)
    return service.image_heatmaps(
        str(project_id),
        str(image_id),
        columns=columns,
        rows=rows,
        label_class_id=(str(label_class_id) if label_class_id is not None else None),
    )

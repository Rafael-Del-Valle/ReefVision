"""Read-only scientific annotation aggregate endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.annotation_aggregates import (
    AnnotationImageAggregate,
)
from reefvision.services.annotation_aggregates import (
    AnnotationAggregateService,
)

router = APIRouter(tags=["scientific-annotation-aggregates"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/projects/{project_id}/images/{image_id}/annotation-aggregates",
    response_model=AnnotationImageAggregate,
)
def image_annotation_aggregates(
    project_id: UUID,
    image_id: UUID,
    session: DbSession,
) -> AnnotationImageAggregate:
    return AnnotationAggregateService(session).summarize_image(
        str(project_id),
        str(image_id),
    )

"""Paired reviewed survey analysis and immutable report history."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.api.routes.reviewer_lab_v15 import Access, require_actor, service
from reefvision.db.models.multimodal import MultimodalStudy
from reefvision.schemas.multimodal import (
    Digest,
    MultimodalOption,
    MultimodalRead,
    MultimodalRequest,
    MultimodalSummary,
)
from reefvision.services.multimodal import find_study, freeze, options, read, replay, summary

router = APIRouter(prefix="/projects/{project_id}/multimodal", tags=["multimodal"])
Db = Annotated[Session, Depends(get_db_session)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/sources")
def sources(
    project_id: UUID,
    kind: Literal["audio", "index", "box"],
    db: Db,
    limit: Limit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MultimodalOption]:
    return options(db, str(project_id), kind, limit, offset)


@router.post("/studies", status_code=201)
def create(
    project_id: UUID, payload: MultimodalRequest, request: Request, db: Db, access: Access
) -> MultimodalRead:
    actor = require_actor(service(project_id, db), access, write=True)
    return freeze(db, request.app.state.settings, str(project_id), payload, actor)


@router.get("/studies")
def list_studies(
    project_id: UUID, db: Db, limit: Limit = 50, offset: Annotated[int, Query(ge=0)] = 0
) -> list[MultimodalSummary]:
    rows = db.scalars(
        select(MultimodalStudy)
        .where(MultimodalStudy.project_id == str(project_id))
        .order_by(MultimodalStudy.created_at.desc(), MultimodalStudy.id)
        .limit(limit)
        .offset(offset)
    )
    return [summary(row) for row in rows]


@router.get("/studies/{study_id}")
def get(project_id: UUID, study_id: UUID, db: Db) -> MultimodalRead:
    return read(find_study(db, str(project_id), str(study_id)))


@router.get("/studies/{study_id}/export")
def export(project_id: UUID, study_id: UUID, response: Response, db: Db) -> MultimodalRead:
    response.headers["Content-Disposition"] = f'attachment; filename="multimodal-{study_id}.json"'
    return read(find_study(db, str(project_id), str(study_id)))


class Pin(BaseModel):
    study_sha256: Digest


@router.post("/studies/{study_id}/replay")
def recompute(
    project_id: UUID, study_id: UUID, pin: Pin, request: Request, db: Db
) -> MultimodalRead:
    row = find_study(db, str(project_id), str(study_id))
    replay(db, request.app.state.settings, str(project_id), row, pin.study_sha256)
    return read(row)

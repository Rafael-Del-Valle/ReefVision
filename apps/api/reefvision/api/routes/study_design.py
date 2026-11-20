"""Researcher-reviewed experimental design history."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.study_design import (
    StudyDesignBind,
    StudyDesignCreate,
    StudyDesignPage,
    StudyDesignRead,
    StudyDesignSnapshot,
)
from reefvision.services.study_design import StudyDesignService

router = APIRouter(prefix="/projects/{project_id}/ecology/study-designs", tags=["study design"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post("", status_code=201)
def freeze_study_design(
    project_id: UUID, payload: StudyDesignCreate, session: DbSession
) -> StudyDesignRead:
    return StudyDesignService(session).save(str(project_id), payload)


@router.get("")
def list_study_designs(
    project_id: UUID,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> StudyDesignPage:
    return StudyDesignService(session).list(str(project_id), page, page_size)


@router.get("/{revision_id}")
def get_study_design(project_id: UUID, revision_id: UUID, session: DbSession) -> StudyDesignRead:
    return StudyDesignService(session).get(str(project_id), str(revision_id))


@router.post("/{revision_id}/bind", status_code=201)
def bind_study_design(
    project_id: UUID, revision_id: UUID, payload: StudyDesignBind, session: DbSession
) -> StudyDesignRead:
    return StudyDesignService(session).bind(str(project_id), str(revision_id), payload)


@router.get("/{revision_id}/design.json")
def download_study_design(
    project_id: UUID, revision_id: UUID, session: DbSession, response: Response
) -> StudyDesignSnapshot:
    result = get_study_design(project_id, revision_id, session)
    response.headers["Content-Disposition"] = (
        f'attachment; filename="study-design-{revision_id}.json"'
    )
    response.headers["X-ReefVision-Content-SHA256"] = result.content_sha256
    return result.snapshot

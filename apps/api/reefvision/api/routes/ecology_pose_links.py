"""Project-scoped reviewed ecological pose link endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.ecology_pose_links import (
    PoseLinkCorrection,
    PoseLinkCreate,
    PoseLinkList,
    PoseLinkResponse,
    PoseLinkUnlink,
)
from reefvision.services.ecology_pose_links import EcologyPoseLinkService

router = APIRouter(
    prefix="/projects/{project_id}/ecology/pose-links", tags=["ecological monitoring"]
)
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get("", response_model=PoseLinkList)
def list_links(
    project_id: UUID,
    session: DbSession,
    organism_key: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PoseLinkList:
    return EcologyPoseLinkService(session).list(
        str(project_id), organism_key=organism_key, limit=limit, offset=offset
    )


@router.post("", response_model=PoseLinkResponse, status_code=status.HTTP_201_CREATED)
def create_link(project_id: UUID, payload: PoseLinkCreate, session: DbSession) -> PoseLinkResponse:
    return EcologyPoseLinkService(session).link(str(project_id), payload)


@router.get("/{link_id}", response_model=list[PoseLinkResponse])
def link_history(project_id: UUID, link_id: UUID, session: DbSession) -> list[PoseLinkResponse]:
    return EcologyPoseLinkService(session).history(str(project_id), str(link_id))


@router.post(
    "/{link_id}/corrections", response_model=PoseLinkResponse, status_code=status.HTTP_201_CREATED
)
def correct_link(
    project_id: UUID, link_id: UUID, payload: PoseLinkCorrection, session: DbSession
) -> PoseLinkResponse:
    return EcologyPoseLinkService(session).correct(str(project_id), str(link_id), payload)


@router.post(
    "/{link_id}/unlink", response_model=PoseLinkResponse, status_code=status.HTTP_201_CREATED
)
def unlink(
    project_id: UUID, link_id: UUID, payload: PoseLinkUnlink, session: DbSession
) -> PoseLinkResponse:
    return EcologyPoseLinkService(session).unlink(str(project_id), str(link_id), payload)

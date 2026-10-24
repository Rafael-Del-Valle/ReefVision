"""Local-first project ecological identity registry endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.ecology_identity import (
    EcologyIdentityCreate,
    EcologyIdentityRegistryResponse,
    EcologyIdentityRevisionCreate,
    EcologyIdentityRow,
)
from reefvision.services.ecology_identity import EcologyIdentityService

router = APIRouter(tags=["ecological monitoring"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.get(
    "/projects/{project_id}/ecology/identity-registry",
    response_model=EcologyIdentityRegistryResponse,
)
def list_identity_registry(project_id: str, session: DbSession) -> EcologyIdentityRegistryResponse:
    return EcologyIdentityService(session).registry(project_id)


@router.post(
    "/projects/{project_id}/ecology/organisms",
    response_model=EcologyIdentityRow,
    status_code=status.HTTP_201_CREATED,
)
def register_organism(
    project_id: str, payload: EcologyIdentityCreate, session: DbSession
) -> EcologyIdentityRow:
    return EcologyIdentityService(session).register(project_id, payload)


@router.post(
    "/projects/{project_id}/ecology/organisms/{organism_key}/revisions",
    response_model=EcologyIdentityRow,
    status_code=status.HTTP_201_CREATED,
)
def revise_organism(
    project_id: str,
    organism_key: str,
    payload: EcologyIdentityRevisionCreate,
    session: DbSession,
) -> EcologyIdentityRow:
    return EcologyIdentityService(session).revise(project_id, organism_key, payload)

"""Local-first project ecological identity registry endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.ecology_identity import (
    EcologyAnnotationEvidenceCreate,
    EcologyAnnotationEvidenceRow,
    EcologyCalibrationEvidenceCreate,
    EcologyCalibrationEvidenceRow,
    EcologyIdentityCreate,
    EcologyIdentityRegistryResponse,
    EcologyIdentityRevisionCreate,
    EcologyIdentityRow,
    EcologyImageEvidenceCreate,
    EcologyImageEvidenceRow,
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
    "/projects/{project_id}/ecology/organisms/{organism_key}/image-evidence",
    response_model=EcologyImageEvidenceRow,
    status_code=status.HTTP_201_CREATED,
)
def link_organism_image(
    project_id: str,
    organism_key: str,
    payload: EcologyImageEvidenceCreate,
    session: DbSession,
) -> EcologyImageEvidenceRow:
    return EcologyIdentityService(session).link_image(project_id, organism_key, payload)


@router.post(
    "/projects/{project_id}/ecology/organisms/{organism_key}/annotation-evidence",
    response_model=EcologyAnnotationEvidenceRow,
    status_code=status.HTTP_201_CREATED,
)
def link_organism_annotation(
    project_id: str,
    organism_key: str,
    payload: EcologyAnnotationEvidenceCreate,
    session: DbSession,
) -> EcologyAnnotationEvidenceRow:
    return EcologyIdentityService(session).link_annotation(project_id, organism_key, payload)


@router.post(
    "/projects/{project_id}/ecology/organisms/{organism_key}/calibration-evidence",
    response_model=EcologyCalibrationEvidenceRow,
    status_code=status.HTTP_201_CREATED,
)
def link_organism_calibration(
    project_id: str,
    organism_key: str,
    payload: EcologyCalibrationEvidenceCreate,
    session: DbSession,
) -> EcologyCalibrationEvidenceRow:
    return EcologyIdentityService(session).link_calibration(project_id, organism_key, payload)


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

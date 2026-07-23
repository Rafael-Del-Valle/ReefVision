"""Immutable whole-image, mask, and fragment classification dataset routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.classification_datasets import (
    ClassificationDatasetCreateRequest,
    ClassificationDatasetDetailResponse,
    ClassificationDatasetSnapshotResponse,
)
from reefvision.services.classification_datasets import ClassificationDatasetService

router = APIRouter(tags=["classification-datasets"])
DbSession = Annotated[Session, Depends(get_db_session)]


@router.post(
    "/projects/{project_id}/classification-dataset-snapshots",
    response_model=ClassificationDatasetDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_classification_dataset_snapshot(
    project_id: str,
    payload: ClassificationDatasetCreateRequest,
    session: DbSession,
) -> ClassificationDatasetDetailResponse:
    return ClassificationDatasetService(session).create(project_id, payload)


@router.get(
    "/projects/{project_id}/classification-dataset-snapshots",
    response_model=list[ClassificationDatasetSnapshotResponse],
)
def list_classification_dataset_snapshots(
    project_id: str,
    session: DbSession,
) -> list[ClassificationDatasetSnapshotResponse]:
    return ClassificationDatasetService(session).list(project_id)


@router.get(
    "/classification-dataset-snapshots/{snapshot_id}",
    response_model=ClassificationDatasetDetailResponse,
)
def get_classification_dataset_snapshot(
    snapshot_id: str,
    session: DbSession,
) -> ClassificationDatasetDetailResponse:
    return ClassificationDatasetService(session).get(snapshot_id)

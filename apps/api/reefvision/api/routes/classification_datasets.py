"""Immutable whole-image, mask, and fragment classification dataset routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import get_settings
from reefvision.schemas.classification_datasets import (
    ClassificationDatasetCreateRequest,
    ClassificationDatasetDetailResponse,
    ClassificationDatasetSnapshotResponse,
    ClassificationSnapshotEvaluationQueueResponse,
    ClassificationSnapshotEvaluationRequest,
    ClassificationSnapshotTrainingRequest,
    ClassificationSnapshotTrainingResponse,
)
from reefvision.services.classification_datasets import ClassificationDatasetService
from reefvision.services.classification_snapshot_evaluations import (
    ClassificationSnapshotEvaluationService,
)
from reefvision.services.classification_snapshot_training import (
    ClassificationSnapshotTrainingService,
)
from reefvision.services.training_resource_requirements import (
    apply_training_scheduler_requirements,
)

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


@router.post(
    "/projects/{project_id}/classification-dataset-snapshots/{snapshot_id}/training-runs",
    response_model=ClassificationSnapshotTrainingResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def train_classification_dataset_snapshot(
    project_id: str,
    snapshot_id: str,
    payload: ClassificationSnapshotTrainingRequest,
    session: DbSession,
) -> ClassificationSnapshotTrainingResponse:
    response = ClassificationSnapshotTrainingService(session).queue(
        project_id,
        snapshot_id,
        payload,
    )
    apply_training_scheduler_requirements(session, response.training_run_id)
    return response


@router.post(
    "/projects/{project_id}/classification-dataset-snapshots/{snapshot_id}/evaluations",
    response_model=ClassificationSnapshotEvaluationQueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def evaluate_classification_dataset_snapshot(
    project_id: str,
    snapshot_id: str,
    payload: ClassificationSnapshotEvaluationRequest,
    session: DbSession,
) -> ClassificationSnapshotEvaluationQueueResponse:
    return ClassificationSnapshotEvaluationService(session, get_settings()).queue(
        project_id,
        snapshot_id,
        payload,
    )

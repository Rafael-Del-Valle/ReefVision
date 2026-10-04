"""Immutable pose-training dataset endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.pose_training_datasets import (
    PoseTrainingDatasetCreateRequest,
    PoseTrainingDatasetItemResponse,
    PoseTrainingDatasetManifestResponse,
    PoseTrainingDatasetResponse,
)
from reefvision.services.pose_training_datasets import (
    PoseTrainingDatasetService,
)

router = APIRouter(tags=["pose-training-datasets"])
DbSession = Annotated[
    Session,
    Depends(get_db_session),
]


@router.post(
    "/pose-active-learning-rounds/{round_id}/training-dataset",
    response_model=PoseTrainingDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_pose_training_dataset(
    round_id: str,
    payload: PoseTrainingDatasetCreateRequest,
    session: DbSession,
) -> PoseTrainingDatasetResponse:
    return PoseTrainingDatasetService(session).create_from_round(
        round_id,
        payload,
    )


@router.get(
    "/projects/{project_id}/pose-training-datasets",
    response_model=list[PoseTrainingDatasetResponse],
)
def list_pose_training_datasets(
    project_id: str,
    session: DbSession,
) -> list[PoseTrainingDatasetResponse]:
    return PoseTrainingDatasetService(session).list_datasets(project_id)


@router.get(
    "/pose-training-datasets/{dataset_id}",
    response_model=PoseTrainingDatasetResponse,
)
def get_pose_training_dataset(
    dataset_id: str,
    session: DbSession,
) -> PoseTrainingDatasetResponse:
    return PoseTrainingDatasetService(session).get_dataset(dataset_id)


@router.get(
    "/pose-training-datasets/{dataset_id}/items",
    response_model=list[PoseTrainingDatasetItemResponse],
)
def get_pose_training_dataset_items(
    dataset_id: str,
    session: DbSession,
) -> list[PoseTrainingDatasetItemResponse]:
    return PoseTrainingDatasetService(session).items(dataset_id)


@router.get(
    "/pose-training-datasets/{dataset_id}/manifest",
    response_model=PoseTrainingDatasetManifestResponse,
)
def get_pose_training_dataset_manifest(
    dataset_id: str,
    session: DbSession,
) -> PoseTrainingDatasetManifestResponse:
    return PoseTrainingDatasetService(session).manifest(dataset_id)


@router.get(
    "/pose-training-datasets/{dataset_id}/native-package",
)
def download_pose_training_dataset_native_package(
    dataset_id: str,
    session: DbSession,
) -> Response:
    filename, content, package_sha256 = PoseTrainingDatasetService(session).native_package(
        dataset_id
    )

    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": (f'attachment; filename="{filename}"'),
            "X-ReefVision-Pose-Dataset-Package-SHA256": (package_sha256),
        },
    )

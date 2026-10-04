"""Immutable pose-training dataset endpoints."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.schemas.pose_training_datasets import (
    PoseTrainingDatasetCreateRequest,
    PoseTrainingDatasetItemResponse,
    PoseTrainingDatasetManifestResponse,
    PoseTrainingDatasetResponse,
    PoseTrainingExportFormat,
)
from reefvision.services.pose_training_datasets import (
    PoseTrainingDatasetService,
)
from reefvision.services.pose_training_exports import (
    PoseTrainingExportService,
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


@router.get(
    "/pose-training-datasets/{dataset_id}/export",
)
def download_pose_training_dataset_export(
    dataset_id: str,
    request: Request,
    session: DbSession,
    export_format: Annotated[
        PoseTrainingExportFormat,
        Query(alias="format"),
    ] = "coco",
) -> Response:
    settings: Settings = request.app.state.settings

    artifact = PoseTrainingExportService(
        session,
        settings,
    ).export(
        dataset_id,
        export_format,
    )

    encoded_filename = quote(
        artifact.filename,
        safe="",
    )

    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": (f"attachment; filename*=UTF-8''{encoded_filename}"),
            "X-ReefVision-Pose-Training-Format": (artifact.export_format),
            "X-ReefVision-Pose-Training-Lossy": ("true" if artifact.lossy else "false"),
            "X-ReefVision-Pose-Training-Bundle-SHA256": (artifact.bundle_sha256),
        },
    )

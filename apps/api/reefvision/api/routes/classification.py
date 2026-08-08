"""Image-label, classification dataset, training, inference, and review endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.config import Settings
from reefvision.db.models import ClassificationDataset, Job
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.classification import (
    ClassificationDatasetCreateRequest,
    ClassificationDatasetResponse,
    ClassificationInferenceCreateRequest,
    ClassificationPredictionResponse,
    ClassificationPredictionReviewRequest,
    ClassificationTrainingCreateRequest,
    ImageLabelResponse,
    ImageLabelSetRequest,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.services.classification_datasets import ClassificationDatasetService
from reefvision.services.classification_labels import ClassificationLabelService
from reefvision.services.classification_predictions import ClassificationPredictionService

router = APIRouter(tags=["classification"])
DbSession = Annotated[Session, Depends(get_db_session)]


def dataset_service(
    request: Request,
    session: Session,
) -> ClassificationDatasetService:
    settings: Settings = request.app.state.settings
    return ClassificationDatasetService(session, settings)


@router.get(
    "/images/{image_id}/classification-labels",
    response_model=list[ImageLabelResponse],
)
def list_image_labels(
    image_id: str,
    session: DbSession,
    label_set: Annotated[str, Query(min_length=1, max_length=100)] = "default",
) -> list[ImageLabelResponse]:
    return ClassificationLabelService(session).list_labels(image_id, label_set)


@router.put(
    "/images/{image_id}/classification-labels",
    response_model=list[ImageLabelResponse],
)
def replace_image_labels(
    image_id: str,
    payload: ImageLabelSetRequest,
    session: DbSession,
) -> list[ImageLabelResponse]:
    return ClassificationLabelService(session).replace_labels(image_id, payload)


@router.get(
    "/projects/{project_id}/classification-datasets",
    response_model=list[ClassificationDatasetResponse],
)
def list_classification_datasets(
    project_id: str,
    request: Request,
    session: DbSession,
) -> list[ClassificationDatasetResponse]:
    return dataset_service(request, session).list_datasets(project_id)


@router.post(
    "/projects/{project_id}/classification-datasets",
    response_model=ClassificationDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_classification_dataset(
    project_id: str,
    payload: ClassificationDatasetCreateRequest,
    request: Request,
    session: DbSession,
) -> ClassificationDatasetResponse:
    return dataset_service(request, session).create_dataset(project_id, payload)


@router.get(
    "/classification-datasets/{dataset_id}",
    response_model=ClassificationDatasetResponse,
)
def get_classification_dataset(
    dataset_id: str,
    request: Request,
    session: DbSession,
) -> ClassificationDatasetResponse:
    return dataset_service(request, session).get_dataset(dataset_id)


@router.get("/classification-datasets/{dataset_id}/download", response_class=FileResponse)
def download_classification_dataset(
    dataset_id: str,
    request: Request,
    session: DbSession,
) -> FileResponse:
    path = dataset_service(request, session).archive_path(dataset_id)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"reefvision-classification-{dataset_id}.zip",
    )


@router.post(
    "/projects/{project_id}/classification-training-jobs",
    response_model=JobResponse,
)
def create_classification_training_job(
    project_id: str,
    payload: ClassificationTrainingCreateRequest,
    session: DbSession,
) -> JobResponse:
    dataset = session.get(ClassificationDataset, payload.classification_dataset_id)
    if dataset is None or dataset.project_id != project_id:
        raise NotFoundError("Classification dataset not found in this project")
    job = Job(
        project_id=project_id,
        job_type="classification_training",
        status="queued",
        progress_total=payload.epochs,
        request_json=payload.model_dump(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return JobResponse.model_validate(job)


@router.post(
    "/projects/{project_id}/classification-inference-jobs",
    response_model=JobResponse,
)
def create_classification_inference_job(
    project_id: str,
    payload: ClassificationInferenceCreateRequest,
    session: DbSession,
) -> JobResponse:
    return ClassificationPredictionService(session).create_job(project_id, payload)


@router.get(
    "/projects/{project_id}/classification-predictions",
    response_model=list[ClassificationPredictionResponse],
)
def list_classification_predictions(
    project_id: str,
    session: DbSession,
    image_id: str | None = None,
    review_status: Annotated[str | None, Query(alias="status")] = None,
) -> list[ClassificationPredictionResponse]:
    return ClassificationPredictionService(session).list_predictions(
        project_id,
        image_id=image_id,
        status=review_status,
    )


@router.put(
    "/classification-predictions/{prediction_id}/review",
    response_model=ClassificationPredictionResponse,
)
def review_classification_prediction(
    prediction_id: str,
    payload: ClassificationPredictionReviewRequest,
    session: DbSession,
) -> ClassificationPredictionResponse:
    return ClassificationPredictionService(session).review(prediction_id, payload)

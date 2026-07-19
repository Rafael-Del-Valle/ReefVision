"""Classification dataset, training, inference, label, and review endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.schemas.classification import (
    ClassificationDatasetPreviewResponse,
    ClassificationDatasetRequest,
    ClassificationInferenceRequest,
    ClassificationPredictionPage,
    ClassificationPredictionResponse,
    ClassificationReviewRequest,
    ClassificationTrainingRequest,
    ImageLabelResponse,
    ImageLabelWriteRequest,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.training import TrainingRunResponse
from reefvision.services.classification import ClassificationService

router = APIRouter(tags=["classification"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ClassificationService:
    return ClassificationService(session, request.app.state.settings)


@router.post(
    "/projects/{project_id}/classification-preview",
    response_model=ClassificationDatasetPreviewResponse,
)
def preview_classification_dataset(
    project_id: str,
    payload: ClassificationDatasetRequest,
    request: Request,
    session: DbSession,
) -> ClassificationDatasetPreviewResponse:
    return service(request, session).preview(project_id, payload)


@router.post(
    "/projects/{project_id}/classification-training-runs",
    response_model=TrainingRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_classification_training_run(
    project_id: str,
    payload: ClassificationTrainingRequest,
    request: Request,
    session: DbSession,
) -> TrainingRunResponse:
    return service(request, session).create_training_run(project_id, payload)


@router.post(
    "/projects/{project_id}/classification-inference-jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_classification_inference_job(
    project_id: str,
    payload: ClassificationInferenceRequest,
    request: Request,
    session: DbSession,
) -> JobResponse:
    return service(request, session).create_inference_job(project_id, payload)


@router.get(
    "/projects/{project_id}/classification-predictions",
    response_model=ClassificationPredictionPage,
)
def list_classification_predictions(
    project_id: str,
    request: Request,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    image_id: str | None = None,
    model_id: str | None = None,
    review_status: str | None = None,
) -> ClassificationPredictionPage:
    return service(request, session).list_predictions(
        project_id,
        page=page,
        page_size=page_size,
        image_id=image_id,
        model_id=model_id,
        review_status=review_status,
    )


@router.post(
    "/classification-predictions/{prediction_id}/review",
    response_model=ClassificationPredictionResponse,
)
def review_classification_prediction(
    prediction_id: str,
    payload: ClassificationReviewRequest,
    request: Request,
    session: DbSession,
) -> ClassificationPredictionResponse:
    return service(request, session).review_prediction(prediction_id, payload)


@router.get("/images/{image_id}/labels", response_model=list[ImageLabelResponse])
def list_image_labels(
    image_id: str,
    request: Request,
    session: DbSession,
) -> list[ImageLabelResponse]:
    return service(request, session).list_image_labels(image_id)


@router.post(
    "/images/{image_id}/labels",
    response_model=ImageLabelResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_image_label(
    image_id: str,
    payload: ImageLabelWriteRequest,
    request: Request,
    session: DbSession,
) -> ImageLabelResponse:
    return service(request, session).add_image_label(image_id, payload)


@router.delete("/image-labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image_label(
    label_id: str,
    request: Request,
    session: DbSession,
) -> None:
    service(request, session).delete_image_label(label_id)

"""Classification dataset, training, inference, label, assignment, and review endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from reefvision.api.dependencies import get_db_session
from reefvision.db.models import ClassificationPrediction, ModelRegistration
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.classification import (
    ClassificationAssignmentAcceptRequest,
    ClassificationAssignmentExportResponse,
    ClassificationAssignmentPage,
    ClassificationAssignmentResponse,
    ClassificationDatasetPreviewResponse,
    ClassificationDatasetRequest,
    ClassificationInferenceRequest,
    ClassificationLabelSetCreateRequest,
    ClassificationLabelSetResponse,
    ClassificationLabelSetUpdateRequest,
    ClassificationPredictionPage,
    ClassificationPredictionResponse,
    ClassificationReviewRequest,
    ClassificationTrainingRequest,
    ImageLabelResponse,
    ImageLabelWriteRequest,
)
from reefvision.schemas.classification_assignment_exports import (
    ScientificClassificationExportResponse,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.models import ModelRegistrationResponse, RegisterModelFromRunRequest
from reefvision.schemas.training import TrainingRunResponse
from reefvision.services.classification import ClassificationService
from reefvision.services.classification_assignment_exports import (
    ScientificClassificationExportService,
)
from reefvision.services.classification_assignments import ClassificationAssignmentService
from reefvision.services.classification_models import ClassificationModelService
from reefvision.services.generalized_classification_assignments import (
    GeneralizedClassificationAssignmentService,
)
from reefvision.services.generalized_classification_jobs import (
    GeneralizedClassificationJobService,
)

router = APIRouter(tags=["classification"])
DbSession = Annotated[Session, Depends(get_db_session)]


def service(request: Request, session: Session) -> ClassificationService:
    return ClassificationService(session, request.app.state.settings)


def assignment_service(session: Session) -> ClassificationAssignmentService:
    return GeneralizedClassificationAssignmentService(session)


def model_service(request: Request, session: Session) -> ClassificationModelService:
    return ClassificationModelService(session, request.app.state.settings)


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
    "/projects/{project_id}/classifiers",
    response_model=ModelRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_classifier(
    project_id: str,
    request: Request,
    session: DbSession,
    model_file: Annotated[UploadFile, File()],
    classification_mode: Annotated[
        Literal["multiclass", "binary_state"],
        Form(),
    ] = "multiclass",
    display_name: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
) -> ModelRegistrationResponse:
    models = model_service(request, session)
    registered = models.register_model_upload(
        project_id,
        purpose="classifier",
        provider_name="ultralytics",
        upload_filename=model_file.filename,
        upload_stream=model_file.file,
        display_name=display_name,
        notes=notes,
    )
    model = session.get(ModelRegistration, registered.id)
    if model is None:
        raise NotFoundError("Imported classifier could not be reloaded")
    model.class_map_json = {
        **dict(model.class_map_json or {}),
        "classification_mode": classification_mode,
        "state_labels": ["open", "closed"] if classification_mode == "binary_state" else [],
    }
    model.metadata_json = {
        **dict(model.metadata_json or {}),
        "classification_mode": classification_mode,
        "classification_scope": "annotation_crop",
        "registered_from": "trusted_upload",
    }
    session.commit()
    session.refresh(model)
    return ModelRegistrationResponse.model_validate(model)


@router.post(
    "/projects/{project_id}/classifiers/register-from-run",
    response_model=ModelRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_classifier_from_run(
    project_id: str,
    payload: RegisterModelFromRunRequest,
    request: Request,
    session: DbSession,
) -> ModelRegistrationResponse:
    return model_service(request, session).register_model_from_run(project_id, payload)


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
    return GeneralizedClassificationJobService(
        session,
        request.app.state.settings,
    ).create(project_id, payload)


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
    prediction = session.get(ClassificationPrediction, prediction_id)
    if (
        prediction is not None
        and payload.action == "accept"
        and (
            prediction.label_set.strip().casefold() != "default"
            or prediction.target_kind != "annotation"
        )
    ):
        assignment_service(session).accept_prediction_assignment(
            prediction_id,
            ClassificationAssignmentAcceptRequest(
                label_class_id=payload.label_class_id,
            ),
        )
        session.refresh(prediction)
        return ClassificationPredictionResponse.model_validate(prediction)
    return service(request, session).review_prediction(prediction_id, payload)


@router.post(
    "/projects/{project_id}/classification-label-sets",
    response_model=ClassificationLabelSetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_classification_label_set(
    project_id: str,
    payload: ClassificationLabelSetCreateRequest,
    session: DbSession,
) -> ClassificationLabelSetResponse:
    return assignment_service(session).create_label_set(project_id, payload)


@router.get(
    "/projects/{project_id}/classification-label-sets",
    response_model=list[ClassificationLabelSetResponse],
)
def list_classification_label_sets(
    project_id: str,
    session: DbSession,
    target_kind: str | None = None,
    active_only: bool = True,
) -> list[ClassificationLabelSetResponse]:
    return assignment_service(session).list_label_sets(
        project_id,
        target_kind=target_kind,
        active_only=active_only,
    )


@router.patch(
    "/classification-label-sets/{label_set_id}",
    response_model=ClassificationLabelSetResponse,
)
def update_classification_label_set(
    label_set_id: str,
    payload: ClassificationLabelSetUpdateRequest,
    session: DbSession,
) -> ClassificationLabelSetResponse:
    return assignment_service(session).update_label_set(label_set_id, payload)


@router.post(
    "/classification-predictions/{prediction_id}/accept-assignment",
    response_model=ClassificationAssignmentResponse,
)
def accept_classification_prediction_as_assignment(
    prediction_id: str,
    payload: ClassificationAssignmentAcceptRequest,
    session: DbSession,
) -> ClassificationAssignmentResponse:
    return assignment_service(session).accept_prediction_assignment(prediction_id, payload)


@router.get(
    "/projects/{project_id}/classification-assignments",
    response_model=ClassificationAssignmentPage,
)
def list_classification_assignments(
    project_id: str,
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    image_id: str | None = None,
    annotation_id: str | None = None,
    label_set_id: str | None = None,
    model_id: str | None = None,
    assignment_status: str | None = "accepted",
) -> ClassificationAssignmentPage:
    return assignment_service(session).list_assignments(
        project_id,
        page=page,
        page_size=page_size,
        image_id=image_id,
        annotation_id=annotation_id,
        label_set_id=label_set_id,
        model_id=model_id,
        status=assignment_status,
    )


@router.get(
    "/projects/{project_id}/classification-assignments/export",
    response_model=ClassificationAssignmentExportResponse,
)
def export_classification_assignments(
    project_id: str,
    session: DbSession,
    assignment_status: str | None = "accepted",
) -> ClassificationAssignmentExportResponse:
    return assignment_service(session).export_assignments(
        project_id,
        status=assignment_status,
    )


@router.get(
    "/projects/{project_id}/classification-assignments/scientific-export",
    response_model=ScientificClassificationExportResponse,
)
def export_scientific_classification_assignments(
    project_id: str,
    request: Request,
    session: DbSession,
    assignment_status: str = "accepted",
) -> ScientificClassificationExportResponse:
    return ScientificClassificationExportService(
        session,
        request.app.state.settings,
    ).export(project_id, assignment_status=assignment_status)


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

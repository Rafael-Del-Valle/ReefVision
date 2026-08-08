"""Queue, list, and review image classification predictions."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    ClassificationPrediction,
    ImageAsset,
    ImageLabel,
    Job,
    LabelClass,
    ModelRegistration,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.classification import (
    ClassificationInferenceCreateRequest,
    ClassificationPredictionResponse,
    ClassificationPredictionReviewRequest,
)
from reefvision.schemas.jobs import JobResponse


class ClassificationPredictionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_job(
        self,
        project_id: str,
        payload: ClassificationInferenceCreateRequest,
    ) -> JobResponse:
        model = self.session.get(ModelRegistration, payload.model_id)
        if model is None or model.project_id != project_id:
            raise NotFoundError("Classifier model not found in this project")
        if model.purpose != "classifier" or model.task != "classify":
            raise ValidationError("Selected model is not a classifier")
        found_ids = set(
            self.session.scalars(
                select(ImageAsset.id).where(
                    ImageAsset.project_id == project_id,
                    ImageAsset.id.in_(payload.image_ids),
                )
            )
        )
        if found_ids != set(payload.image_ids):
            raise ValidationError("Classification images must belong to the selected project")
        job = Job(
            project_id=project_id,
            job_type="classification_inference",
            status="queued",
            progress_total=len(payload.image_ids),
            request_json=payload.model_dump(),
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)

    def list_predictions(
        self,
        project_id: str,
        *,
        image_id: str | None = None,
        status: str | None = None,
    ) -> list[ClassificationPredictionResponse]:
        statement = select(ClassificationPrediction).where(
            ClassificationPrediction.project_id == project_id
        )
        if image_id is not None:
            statement = statement.where(ClassificationPrediction.image_id == image_id)
        if status is not None:
            statement = statement.where(ClassificationPrediction.status == status)
        statement = statement.order_by(
            ClassificationPrediction.image_id,
            ClassificationPrediction.rank,
            ClassificationPrediction.created_at,
        )
        return [
            ClassificationPredictionResponse.model_validate(item)
            for item in self.session.scalars(statement)
        ]

    def review(
        self,
        prediction_id: str,
        payload: ClassificationPredictionReviewRequest,
    ) -> ClassificationPredictionResponse:
        prediction = self.session.get(ClassificationPrediction, prediction_id)
        if prediction is None:
            raise NotFoundError("Classification prediction not found")
        if prediction.status != "pending":
            raise ValidationError("Classification prediction has already been reviewed")
        if payload.action == "reject":
            prediction.status = "rejected"
            prediction.reviewed_at = utc_now()
            prediction.reviewed_by = "local_user"
            self.session.commit()
            self.session.refresh(prediction)
            return ClassificationPredictionResponse.model_validate(prediction)

        label_class_id = payload.label_class_id or prediction.label_class_id
        label_class = self.session.get(LabelClass, label_class_id)
        image = self.session.get(ImageAsset, prediction.image_id)
        if image is None or label_class is None or label_class.project_id != image.project_id:
            raise ValidationError("Accepted classification class must belong to the image project")
        existing = self.session.scalar(
            select(ImageLabel).where(
                ImageLabel.image_id == prediction.image_id,
                ImageLabel.label_class_id == label_class_id,
                ImageLabel.label_set == prediction.label_set,
            )
        )
        if existing is None:
            existing = ImageLabel(
                image_id=prediction.image_id,
                label_class_id=label_class_id,
                label_set=prediction.label_set,
                confidence=prediction.confidence,
                source_type="accepted_prediction",
                source_model_id=prediction.model_id,
                source_prediction_id=prediction.id,
                provenance_json={"rank": prediction.rank, "scores": prediction.scores_json},
                status="verified",
                created_by="local_user",
            )
            self.session.add(existing)
            self.session.flush()
        else:
            existing.deleted_at = None
            existing.confidence = prediction.confidence
            existing.source_type = "accepted_prediction"
            existing.source_model_id = prediction.model_id
            existing.source_prediction_id = prediction.id
            existing.provenance_json = {"rank": prediction.rank, "scores": prediction.scores_json}
            existing.status = "verified"
            existing.revision += 1
        image.annotation_revision += 1
        prediction.status = "accepted"
        prediction.accepted_image_label_id = existing.id
        prediction.reviewed_at = utc_now()
        prediction.reviewed_by = "local_user"
        self.session.commit()
        self.session.refresh(prediction)
        return ClassificationPredictionResponse.model_validate(prediction)

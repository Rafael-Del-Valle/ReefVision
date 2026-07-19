"""Evaluate classification predictions against verified annotation classes."""

from __future__ import annotations

from collections import Counter
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Annotation,
    ClassificationPrediction,
    ImageAsset,
    ModelRegistration,
    Project,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.classification_evaluation import (
    ClassificationCalibrationBin,
    ClassificationClassEvaluation,
    ClassificationConfusionCell,
    ClassificationEvaluationRequest,
    ClassificationEvaluationResponse,
)


class ClassificationEvaluationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _model(self, project_id: str, model_id: str) -> ModelRegistration:
        model = self.session.get(ModelRegistration, model_id)
        if model is None:
            raise NotFoundError("Classifier not found")
        if model.project_id != project_id:
            raise ValidationError("The evaluation classifier must belong to the project")
        if model.purpose != "classifier" or model.task != "classify":
            raise ValidationError("Classification evaluation requires a classifier")
        return model

    def _validate_images(self, project_id: str, image_ids: list[str]) -> None:
        if not image_ids:
            return
        images = list(
            self.session.scalars(
                select(ImageAsset).where(
                    ImageAsset.project_id == project_id,
                    ImageAsset.id.in_(image_ids),
                )
            )
        )
        if len(images) != len(set(image_ids)):
            raise ValidationError(
                "All requested evaluation images must exist in the selected project"
            )

    def evaluate(
        self,
        project_id: str,
        request: ClassificationEvaluationRequest,
    ) -> ClassificationEvaluationResponse:
        self._project(project_id)
        self._model(project_id, request.model_id)
        self._validate_images(project_id, request.image_ids)
        statuses = list(dict.fromkeys(request.review_statuses))
        if not statuses:
            raise ValidationError("Choose at least one prediction review status")

        query = select(ClassificationPrediction).where(
            ClassificationPrediction.project_id == project_id,
            ClassificationPrediction.model_id == request.model_id,
            ClassificationPrediction.review_status.in_(statuses),
            ClassificationPrediction.confidence >= request.confidence_threshold,
        )
        if request.image_ids:
            query = query.where(
                ClassificationPrediction.image_id.in_(request.image_ids)
            )
        if request.label_set:
            query = query.where(
                ClassificationPrediction.label_set == request.label_set
            )
        predictions = list(
            self.session.scalars(
                query.order_by(
                    ClassificationPrediction.created_at,
                    ClassificationPrediction.id,
                )
            )
        )

        observations: list[tuple[str, str, float, bool]] = []
        warnings: list[str] = []
        missing_annotation_count = 0
        unresolved_prediction_count = 0
        post_review_ground_truth_count = 0
        for prediction in predictions:
            annotation = (
                self.session.get(Annotation, prediction.annotation_id)
                if prediction.annotation_id
                else None
            )
            if annotation is None or annotation.deleted_at is not None:
                missing_annotation_count += 1
                continue
            if prediction.label_class_id is None:
                unresolved_prediction_count += 1
                continue
            if annotation.source_type == "accepted_prediction":
                post_review_ground_truth_count += 1
            actual = annotation.label_class_id
            predicted = prediction.label_class_id
            observations.append(
                (
                    actual,
                    predicted,
                    float(prediction.confidence),
                    actual == predicted,
                )
            )
        if missing_annotation_count:
            warnings.append(
                f"{missing_annotation_count} predictions were skipped because their source "
                "annotation is unavailable."
            )
        if unresolved_prediction_count:
            warnings.append(
                f"{unresolved_prediction_count} predictions were skipped because they do not "
                "resolve to a project class."
            )
        if post_review_ground_truth_count:
            warnings.append(
                f"{post_review_ground_truth_count} evaluated annotations were previously "
                "changed by accepted predictions. Include pending predictions only or use an "
                "immutable dataset version for an unbiased final evaluation."
            )

        confusion = Counter((actual, predicted) for actual, predicted, _, _ in observations)
        classes = sorted(
            {actual for actual, _, _, _ in observations}
            | {predicted for _, predicted, _, _ in observations}
        )
        class_results: list[ClassificationClassEvaluation] = []
        for label_class_id in classes:
            support = sum(
                count
                for (actual, _predicted), count in confusion.items()
                if actual == label_class_id
            )
            predicted_count = sum(
                count
                for (_actual, predicted), count in confusion.items()
                if predicted == label_class_id
            )
            true_positive_count = confusion[(label_class_id, label_class_id)]
            false_positive_count = predicted_count - true_positive_count
            false_negative_count = support - true_positive_count
            precision = (
                true_positive_count / predicted_count if predicted_count else 0.0
            )
            recall = true_positive_count / support if support else 0.0
            f1 = (
                2 * precision * recall / (precision + recall)
                if precision + recall
                else 0.0
            )
            class_results.append(
                ClassificationClassEvaluation(
                    label_class_id=label_class_id,
                    support=support,
                    predicted_count=predicted_count,
                    true_positive_count=true_positive_count,
                    false_positive_count=false_positive_count,
                    false_negative_count=false_negative_count,
                    precision=precision,
                    recall=recall,
                    f1=f1,
                )
            )

        sample_count = len(observations)
        correct_count = sum(1 for *_prefix, correct in observations if correct)
        accuracy = correct_count / sample_count if sample_count else 0.0
        macro_precision = (
            mean(item.precision for item in class_results) if class_results else 0.0
        )
        macro_recall = (
            mean(item.recall for item in class_results) if class_results else 0.0
        )
        macro_f1 = mean(item.f1 for item in class_results) if class_results else 0.0
        weighted_f1 = (
            sum(item.f1 * item.support for item in class_results) / sample_count
            if sample_count
            else 0.0
        )

        calibration_bins: list[ClassificationCalibrationBin] = []
        expected_calibration_error = 0.0
        bin_count = request.calibration_bin_count
        for index in range(bin_count):
            lower = index / bin_count
            upper = (index + 1) / bin_count
            values = [
                (confidence, correct)
                for _actual, _predicted, confidence, correct in observations
                if confidence >= lower
                and (confidence < upper or (index == bin_count - 1 and confidence <= upper))
            ]
            if values:
                average_confidence = mean(value[0] for value in values)
                bin_accuracy = mean(float(value[1]) for value in values)
                absolute_gap = abs(bin_accuracy - average_confidence)
                expected_calibration_error += (
                    len(values) / sample_count * absolute_gap
                    if sample_count
                    else 0.0
                )
            else:
                average_confidence = None
                bin_accuracy = None
                absolute_gap = None
            calibration_bins.append(
                ClassificationCalibrationBin(
                    lower_bound=lower,
                    upper_bound=upper,
                    sample_count=len(values),
                    mean_confidence=average_confidence,
                    accuracy=bin_accuracy,
                    absolute_gap=absolute_gap,
                )
            )

        confidence_values = [confidence for *_prefix, confidence, _correct in observations]
        top_label_brier_score = (
            mean(
                (confidence - float(correct)) ** 2
                for _actual, _predicted, confidence, correct in observations
            )
            if observations
            else None
        )
        return ClassificationEvaluationResponse(
            project_id=project_id,
            model_id=request.model_id,
            sample_count=sample_count,
            correct_count=correct_count,
            accuracy=accuracy,
            macro_precision=macro_precision,
            macro_recall=macro_recall,
            macro_f1=macro_f1,
            weighted_f1=weighted_f1,
            mean_confidence=(mean(confidence_values) if confidence_values else None),
            expected_calibration_error=(
                expected_calibration_error if observations else None
            ),
            top_label_brier_score=top_label_brier_score,
            confidence_threshold=request.confidence_threshold,
            review_statuses=statuses,
            per_class=class_results,
            confusion_matrix=[
                ClassificationConfusionCell(
                    actual_label_class_id=actual,
                    predicted_label_class_id=predicted,
                    count=count,
                )
                for (actual, predicted), count in sorted(confusion.items())
            ],
            calibration_bins=calibration_bins,
            warnings=warnings,
        )

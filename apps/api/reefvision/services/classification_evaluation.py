"""Evaluate classification predictions against reviewed task-specific ground truth."""

from __future__ import annotations

from collections import Counter
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Annotation,
    ClassificationAssignment,
    ClassificationLabelSet,
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
    ClassificationReviewFilter,
)


def _prediction_target_kind(prediction: ClassificationPrediction) -> str:
    if prediction.target_kind:
        return prediction.target_kind.strip().casefold()
    return "annotation" if prediction.annotation_id else "image"


def _prediction_target_key(
    prediction: ClassificationPrediction,
    target_kind: str,
) -> str | None:
    if prediction.target_key:
        return prediction.target_key
    if target_kind == "annotation" and prediction.annotation_id:
        return f"annotation:{prediction.annotation_id}"
    if target_kind == "image":
        return f"image:{prediction.image_id}"
    if target_kind == "mask" and prediction.mask_annotation_id:
        return f"mask:{prediction.mask_annotation_id}"
    if target_kind == "fragment":
        fragment_key = prediction.fragment_key or prediction.mask_annotation_id
        return f"fragment:{fragment_key}" if fragment_key else None
    return None


def _label_set_candidates(prediction: ClassificationPrediction, target_kind: str) -> tuple[str, ...]:
    key = prediction.label_set.strip().casefold()
    if key == "default" and target_kind != "annotation":
        return (key, f"default-{target_kind}")
    return (key,)


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
        statuses: list[ClassificationReviewFilter] = list(dict.fromkeys(request.review_statuses))
        if not statuses:
            raise ValidationError("Choose at least one prediction review status")

        query = select(ClassificationPrediction).where(
            ClassificationPrediction.project_id == project_id,
            ClassificationPrediction.model_id == request.model_id,
            ClassificationPrediction.review_status.in_(statuses),
            ClassificationPrediction.confidence >= request.confidence_threshold,
        )
        if request.image_ids:
            query = query.where(ClassificationPrediction.image_id.in_(request.image_ids))
        if request.label_set:
            query = query.where(ClassificationPrediction.label_set == request.label_set)
        predictions = list(
            self.session.scalars(
                query.order_by(
                    ClassificationPrediction.created_at,
                    ClassificationPrediction.id,
                )
            )
        )

        label_sets = list(
            self.session.scalars(
                select(ClassificationLabelSet).where(
                    ClassificationLabelSet.project_id == project_id,
                    ClassificationLabelSet.is_active.is_(True),
                )
            )
        )
        label_set_by_key = {item.key.strip().casefold(): item for item in label_sets}
        accepted_assignments = list(
            self.session.scalars(
                select(ClassificationAssignment)
                .where(
                    ClassificationAssignment.project_id == project_id,
                    ClassificationAssignment.status == "accepted",
                )
                .order_by(
                    ClassificationAssignment.updated_at,
                    ClassificationAssignment.created_at,
                    ClassificationAssignment.id,
                )
            )
        )
        assignment_by_target: dict[tuple[str, str, str], ClassificationAssignment] = {}
        for assignment in accepted_assignments:
            assignment_by_target[
                (assignment.label_set_id, assignment.target_kind, assignment.target_key)
            ] = assignment

        observations: list[tuple[str, str, float, bool]] = []
        warnings: list[str] = []
        missing_truth_count = 0
        unresolved_prediction_count = 0
        self_referential_truth_count = 0
        model_derived_truth_count = 0
        multi_label_truth_count = 0
        annotation_fallback_count = 0
        missing_label_set_count = 0

        for prediction in predictions:
            if prediction.label_class_id is None:
                unresolved_prediction_count += 1
                continue
            target_kind = _prediction_target_kind(prediction)
            target_key = _prediction_target_key(prediction, target_kind)
            label_set = next(
                (
                    label_set_by_key[key]
                    for key in _label_set_candidates(prediction, target_kind)
                    if key in label_set_by_key
                    and label_set_by_key[key].target_kind == target_kind
                ),
                None,
            )

            truth_class_id: str | None = None
            truth_assignment: ClassificationAssignment | None = None
            if label_set is not None:
                if label_set.cardinality != "single":
                    multi_label_truth_count += 1
                    continue
                if target_key is not None:
                    truth_assignment = assignment_by_target.get(
                        (label_set.id, target_kind, target_key)
                    )
                if truth_assignment is not None:
                    if truth_assignment.source_prediction_id == prediction.id:
                        self_referential_truth_count += 1
                        continue
                    truth_class_id = truth_assignment.label_class_id
                    if (
                        truth_assignment.source_prediction_id is not None
                        or truth_assignment.source_model_id is not None
                    ):
                        model_derived_truth_count += 1
            elif target_kind != "annotation":
                missing_label_set_count += 1

            if truth_class_id is None and target_kind == "annotation":
                annotation = (
                    self.session.get(Annotation, prediction.annotation_id)
                    if prediction.annotation_id
                    else None
                )
                if annotation is not None and annotation.deleted_at is None:
                    truth_class_id = annotation.label_class_id
                    annotation_fallback_count += 1

            if truth_class_id is None:
                missing_truth_count += 1
                continue

            predicted = prediction.label_class_id
            observations.append(
                (
                    truth_class_id,
                    predicted,
                    float(prediction.confidence),
                    truth_class_id == predicted,
                )
            )

        if missing_truth_count:
            warnings.append(
                f"{missing_truth_count} predictions were skipped because no accepted "
                "classification assignment or legacy annotation truth was available."
            )
        if missing_label_set_count:
            warnings.append(
                f"{missing_label_set_count} generalized predictions could not resolve an active "
                "classification label set for their target kind."
            )
        if unresolved_prediction_count:
            warnings.append(
                f"{unresolved_prediction_count} predictions were skipped because they do not "
                "resolve to a project class."
            )
        if self_referential_truth_count:
            warnings.append(
                f"{self_referential_truth_count} predictions were excluded because the accepted "
                "ground-truth assignment was created from that same prediction."
            )
        if model_derived_truth_count:
            warnings.append(
                f"{model_derived_truth_count} observations use human-accepted assignments that "
                "originated from model predictions. Use a frozen immutable test snapshot for an "
                "independent final performance claim."
            )
        if multi_label_truth_count:
            warnings.append(
                f"{multi_label_truth_count} predictions were skipped because this confusion-matrix "
                "evaluator currently requires single-label classification truth."
            )
        if annotation_fallback_count:
            warnings.append(
                f"{annotation_fallback_count} annotation-target observations used the annotation's "
                "primary class as backward-compatible ground truth because no reviewed assignment "
                "was available."
            )

        confusion = Counter(
            (actual, predicted) for actual, predicted, _confidence, _correct in observations
        )
        classes = sorted(
            {actual for actual, _predicted, _confidence, _correct in observations}
            | {predicted for _actual, predicted, _confidence, _correct in observations}
        )
        class_results: list[ClassificationClassEvaluation] = []
        sample_count = len(observations)
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
            true_negative_count = sample_count - (
                true_positive_count + false_positive_count + false_negative_count
            )
            precision = true_positive_count / predicted_count if predicted_count else 0.0
            recall = true_positive_count / support if support else 0.0
            specificity_denominator = true_negative_count + false_positive_count
            specificity = (
                true_negative_count / specificity_denominator
                if specificity_denominator
                else 0.0
            )
            negative_predictive_denominator = true_negative_count + false_negative_count
            negative_predictive_value = (
                true_negative_count / negative_predictive_denominator
                if negative_predictive_denominator
                else 0.0
            )
            balanced_class_accuracy = (recall + specificity) / 2.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            class_results.append(
                ClassificationClassEvaluation(
                    label_class_id=label_class_id,
                    support=support,
                    predicted_count=predicted_count,
                    true_positive_count=true_positive_count,
                    true_negative_count=true_negative_count,
                    false_positive_count=false_positive_count,
                    false_negative_count=false_negative_count,
                    precision=precision,
                    recall=recall,
                    sensitivity=recall,
                    specificity=specificity,
                    negative_predictive_value=negative_predictive_value,
                    balanced_accuracy=balanced_class_accuracy,
                    f1=f1,
                )
            )

        correct_count = sum(1 for observation in observations if observation[3])
        accuracy = correct_count / sample_count if sample_count else 0.0
        macro_precision = mean(item.precision for item in class_results) if class_results else 0.0
        macro_recall = mean(item.recall for item in class_results) if class_results else 0.0
        macro_f1 = mean(item.f1 for item in class_results) if class_results else 0.0
        balanced_accuracy = (
            mean(item.balanced_accuracy for item in class_results) if class_results else 0.0
        )
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
                    len(values) / sample_count * absolute_gap if sample_count else 0.0
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

        confidence_values = [observation[2] for observation in observations]
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
            balanced_accuracy=balanced_accuracy,
            macro_precision=macro_precision,
            macro_recall=macro_recall,
            macro_f1=macro_f1,
            weighted_f1=weighted_f1,
            mean_confidence=(mean(confidence_values) if confidence_values else None),
            expected_calibration_error=(expected_calibration_error if observations else None),
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

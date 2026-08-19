from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError as PydanticValidationError

from reefvision.domain.errors import ValidationError
from reefvision.jobs.classification_snapshot_evaluation import (
    _verified_probability_mapping,
)
from reefvision.jobs.classification_snapshot_integrity_runtime import (
    _current_verified_source_path,
)
from reefvision.jobs.classification_snapshot_training import _sample_payload
from reefvision.schemas.active_learning_cycles import (
    ActiveLearningClassificationEvaluationJobsRequest,
    ActiveLearningDatasetRecordRequest,
)
from reefvision.schemas.classification import (
    ClassificationInferenceRequest,
    ClassificationTrainingRequest,
)
from reefvision.schemas.classification_datasets import (
    ClassificationSnapshotEvaluationRequest,
    ClassificationSnapshotTrainingRequest,
)
from reefvision.schemas.classification_evaluation import (
    ClassificationCalibrationBin,
    ClassificationClassEvaluation,
    ClassificationConfusionCell,
    ClassificationEvaluationResponse,
)
from reefvision.services.active_learning_cycle_api import _sample_universe
from reefvision.services.classification_evaluation import (
    _label_set_candidates,
    _prediction_target_key,
    _prediction_target_kind,
)
from reefvision.services.classification_evaluation_metrics_runtime import (
    _cohen_kappa,
    _matthews_correlation_coefficient,
)
from reefvision.services.classification_metrics import (
    ClassificationObservation,
    build_classification_evaluation,
)
from reefvision.services.generalized_classification_jobs import (
    _normalized_scope,
    _require_snapshot_preprocessing_match,
)
from reefvision.storage.datasets import canonical_json_sha256


def _snapshot_sample() -> SimpleNamespace:
    sample = SimpleNamespace(
        target_kind="image",
        target_key="image:image-1",
        image_id="image-1",
        source_image_sha256="a" * 64,
        source_image_width_px=100,
        source_image_height_px=80,
        source_image_managed_path="projects/old/images/image-1.jpg",
        mask_annotation_id=None,
        fragment_key=None,
        label_class_ids_json=["class-1"],
        assignment_ids_json=["assignment-1"],
        assignment_revisions_json={"assignment-1": 1},
        target_revision=None,
        target_checksum="a" * 64,
        geometry_json={},
        sample_sha256="",
    )
    sample.sample_sha256 = canonical_json_sha256(_sample_payload(cast(Any, sample)))
    return sample


def test_snapshot_training_request_defaults_to_installed_ultralytics_yaml() -> None:
    request = ClassificationSnapshotTrainingRequest(run_name="reef-state")

    assert request.architecture == "yolo11-cls.yaml"
    assert request.epochs == 100
    assert request.precision == "amp"
    assert request.mask_background == "black"


def test_legacy_classification_training_uses_real_installed_v8_yaml() -> None:
    request = ClassificationTrainingRequest(dataset_version_id="dataset-1")

    assert request.architecture == "yolov8-cls.yaml"


def test_snapshot_evaluation_defaults_to_held_out_test_split() -> None:
    request = ClassificationSnapshotEvaluationRequest(model_id="model-1")

    assert request.split == "test"
    assert request.top_k_values == [1, 3, 5]
    assert request.include_curves is True


def test_snapshot_source_path_can_relocate_when_identity_is_unchanged() -> None:
    sample = _snapshot_sample()
    image = SimpleNamespace(
        id="image-1",
        sha256="a" * 64,
        width_px=100,
        height_px=80,
        managed_path="projects/new/images/image-1.jpg",
    )

    path = _current_verified_source_path(cast(Any, sample), cast(Any, image))

    assert path.as_posix() == "projects/new/images/image-1.jpg"


def test_snapshot_source_identity_rejects_changed_checksum() -> None:
    sample = _snapshot_sample()
    image = SimpleNamespace(
        id="image-1",
        sha256="b" * 64,
        width_px=100,
        height_px=80,
        managed_path="projects/new/images/image-1.jpg",
    )

    with pytest.raises(RuntimeError, match="changed after classification snapshot creation"):
        _current_verified_source_path(cast(Any, sample), cast(Any, image))


def test_generalized_prediction_target_helpers_preserve_target_semantics() -> None:
    mask_prediction = SimpleNamespace(
        target_kind="mask",
        target_key="mask:mask-1",
        annotation_id=None,
        image_id="image-1",
        mask_annotation_id="mask-1",
        fragment_key=None,
        label_set="default",
    )
    legacy_annotation = SimpleNamespace(
        target_kind="",
        target_key="",
        annotation_id="annotation-1",
        image_id="image-1",
        mask_annotation_id=None,
        fragment_key=None,
        label_set="state",
    )

    assert _prediction_target_kind(cast(Any, mask_prediction)) == "mask"
    assert _prediction_target_key(cast(Any, mask_prediction), "mask") == "mask:mask-1"
    assert _label_set_candidates(cast(Any, mask_prediction), "mask") == (
        "default",
        "default-mask",
    )
    assert _prediction_target_kind(cast(Any, legacy_annotation)) == "annotation"
    assert _prediction_target_key(
        cast(Any, legacy_annotation),
        "annotation",
    ) == "annotation:annotation-1"


def test_scope_normalization_keeps_legacy_annotation_models_compatible() -> None:
    assert _normalized_scope("annotation_crop") == "annotation"
    assert _normalized_scope("fragment") == "fragment"


def test_snapshot_mask_classifier_requires_training_preprocessing_at_inference() -> None:
    metadata: dict[str, object] = {
        "minimum_crop_size_px": 20,
        "padding_fraction": 0.1,
        "mask_background": "black",
    }
    matching = ClassificationInferenceRequest(
        model_id="model-1",
        target_kind="mask",
        mask_annotation_ids=["mask-1"],
        minimum_crop_size_px=20,
        padding_fraction=0.1,
        mask_background="black",
    )
    changed = matching.model_copy(update={"padding_fraction": 0.2})

    _require_snapshot_preprocessing_match(metadata, matching)
    with pytest.raises(ValidationError, match="same crop padding"):
        _require_snapshot_preprocessing_match(metadata, changed)


def test_probability_mapping_normalizes_every_registered_output_class() -> None:
    mapped = _verified_probability_mapping(
        {"open": "class-open", "closed": "class-closed"},
        {"open": 2.0, "closed": 1.0},
    )

    assert mapped == pytest.approx(
        {"class-open": 2.0 / 3.0, "class-closed": 1.0 / 3.0}
    )
    with pytest.raises(RuntimeError, match="not mapped"):
        _verified_probability_mapping(
            {"open": "class-open"},
            {"open": 0.5, "unknown": 0.5},
        )


def test_active_learning_dataset_record_requires_exactly_one_immutable_dataset() -> None:
    detection = ActiveLearningDatasetRecordRequest(dataset_version_id="dataset-1")
    classification = ActiveLearningDatasetRecordRequest(
        classification_dataset_snapshot_id="snapshot-1"
    )

    assert detection.dataset_version_id == "dataset-1"
    assert classification.classification_dataset_snapshot_id == "snapshot-1"
    with pytest.raises(PydanticValidationError):
        ActiveLearningDatasetRecordRequest()
    with pytest.raises(PydanticValidationError):
        ActiveLearningDatasetRecordRequest(
            dataset_version_id="dataset-1",
            classification_dataset_snapshot_id="snapshot-1",
        )


def test_active_learning_classifier_promotion_requires_distinct_evaluation_jobs() -> None:
    request = ActiveLearningClassificationEvaluationJobsRequest(
        baseline_evaluation_job_id="baseline-job",
        candidate_evaluation_job_id="candidate-job",
    )

    assert request.baseline_evaluation_job_id == "baseline-job"
    with pytest.raises(PydanticValidationError):
        ActiveLearningClassificationEvaluationJobsRequest(
            baseline_evaluation_job_id="same-job",
            candidate_evaluation_job_id="same-job",
        )


def test_active_learning_sample_universe_is_sorted_and_complete() -> None:
    manifest = {
        "evaluated_samples": [
            {"sample_id": "b", "sample_sha256": "2" * 64},
            {"sample_id": "a", "sample_sha256": "1" * 64},
        ],
        "excluded_samples": [
            {"sample_id": "c", "sample_sha256": "3" * 64, "reason": "minimum"}
        ],
    }

    universe = _sample_universe(manifest)

    assert universe["evaluated"][0][0] == "a"
    assert universe["excluded"] == [["c", "3" * 64, "minimum"]]


def _evaluation_response() -> ClassificationEvaluationResponse:
    return ClassificationEvaluationResponse(
        project_id="project-1",
        model_id="model-1",
        sample_count=10,
        correct_count=8,
        accuracy=0.8,
        balanced_accuracy=0.8,
        macro_precision=0.8,
        macro_recall=0.8,
        macro_f1=0.8,
        weighted_f1=0.8,
        confidence_threshold=0,
        review_statuses=["pending"],
        per_class=[
            ClassificationClassEvaluation(
                label_class_id="a",
                support=5,
                predicted_count=5,
                true_positive_count=4,
                true_negative_count=4,
                false_positive_count=1,
                false_negative_count=1,
                precision=0.8,
                recall=0.8,
                sensitivity=0.8,
                specificity=0.8,
                negative_predictive_value=0.8,
                balanced_accuracy=0.8,
                f1=0.8,
            ),
            ClassificationClassEvaluation(
                label_class_id="b",
                support=5,
                predicted_count=5,
                true_positive_count=4,
                true_negative_count=4,
                false_positive_count=1,
                false_negative_count=1,
                precision=0.8,
                recall=0.8,
                sensitivity=0.8,
                specificity=0.8,
                negative_predictive_value=0.8,
                balanced_accuracy=0.8,
                f1=0.8,
            ),
        ],
        confusion_matrix=[
            ClassificationConfusionCell(
                actual_label_class_id="a",
                predicted_label_class_id="a",
                count=4,
            ),
            ClassificationConfusionCell(
                actual_label_class_id="a",
                predicted_label_class_id="b",
                count=1,
            ),
            ClassificationConfusionCell(
                actual_label_class_id="b",
                predicted_label_class_id="a",
                count=1,
            ),
            ClassificationConfusionCell(
                actual_label_class_id="b",
                predicted_label_class_id="b",
                count=4,
            ),
        ],
        calibration_bins=[
            ClassificationCalibrationBin(
                lower_bound=0,
                upper_bound=1,
                sample_count=10,
                mean_confidence=0.8,
                accuracy=0.8,
                absolute_gap=0,
            )
        ],
        warnings=[],
    )


def test_multiclass_agreement_metrics_match_symmetric_binary_confusion() -> None:
    response = _evaluation_response()

    assert _matthews_correlation_coefficient(response) == pytest.approx(0.6)
    assert _cohen_kappa(response) == pytest.approx(0.6)


def test_held_out_metric_engine_reports_top_k_curves_and_calibration() -> None:
    observations = [
        ClassificationObservation(
            actual_label_class_id="a",
            predicted_label_class_id="a",
            confidence=0.9,
            probabilities_by_class_id={"a": 0.9, "b": 0.1},
        ),
        ClassificationObservation(
            actual_label_class_id="a",
            predicted_label_class_id="b",
            confidence=0.6,
            probabilities_by_class_id={"a": 0.4, "b": 0.6},
        ),
        ClassificationObservation(
            actual_label_class_id="b",
            predicted_label_class_id="b",
            confidence=0.8,
            probabilities_by_class_id={"a": 0.2, "b": 0.8},
        ),
        ClassificationObservation(
            actual_label_class_id="b",
            predicted_label_class_id="b",
            confidence=0.7,
            probabilities_by_class_id={"a": 0.3, "b": 0.7},
        ),
    ]

    result = build_classification_evaluation(
        project_id="project-1",
        model_id="model-1",
        observations=observations,
        calibration_bin_count=5,
        top_k_values=[1, 2],
        include_curves=True,
    )

    assert result.accuracy == pytest.approx(0.75)
    assert result.top_k_accuracy[0].accuracy == pytest.approx(0.75)
    assert result.top_k_accuracy[1].accuracy == pytest.approx(1.0)
    assert result.expected_calibration_error is not None
    assert result.temperature_scale is not None
    assert result.temperature_scaled_negative_log_likelihood is not None
    assert result.isotonic_calibration
    assert all(item.curve for item in result.per_class)
    assert all(item.roc_auc is not None for item in result.per_class)
    assert all(item.precision_recall_auc is not None for item in result.per_class)

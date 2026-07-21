from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import (
    ActiveLearningCycle,
    ModelRegistration,
    Project,
    TrainingRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.active_learning_cycles import (
    ActiveLearningCycleCreateRequest,
    ActiveLearningEvaluationRequest,
    ActiveLearningReviewProgressRequest,
    ActiveLearningSelectionRecordRequest,
    ActiveLearningTrainingRecordRequest,
    PromotionGate,
)
from reefvision.services.active_learning_cycle_api import (
    PublicActiveLearningCycleService,
)


def test_active_learning_cycle_records_selection_review_and_promotion_gates(
    client: TestClient,
) -> None:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        project = Project(
            name="Active learning project",
            slug="active-learning-project",
            storage_root="projects/active-learning-project",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        service = PublicActiveLearningCycleService(session)
        cycle = service.create(
            project.id,
            ActiveLearningCycleCreateRequest(
                name="Cycle one",
                selection_strategy="k_center",
                annotation_budget=3,
                promotion_gates=[
                    PromotionGate(
                        metric="map50_95",
                        operator=">=",
                        threshold=0.02,
                        relative_to_baseline=True,
                    )
                ],
                stop_after_cycles=3,
            ),
        )
        assert cycle.cycle_index == 1
        assert cycle.status == "selection"

        cycle = service.record_selection(
            cycle.id,
            ActiveLearningSelectionRecordRequest(
                selected_candidate_ids=["image-a", "image-b", "image-c"],
                selection_result={"strategy": "k_center"},
            ),
        )
        assert cycle.status == "review"
        assert cycle.selected_count == 3
        cycle = service.record_review_progress(
            cycle.id,
            ActiveLearningReviewProgressRequest(reviewed_count=3),
        )
        assert cycle.reviewed_count == 3

        row = session.get(ActiveLearningCycle, cycle.id)
        assert row is not None
        row.status = "evaluation"
        session.commit()
        result = service.evaluate_and_promote(
            cycle.id,
            ActiveLearningEvaluationRequest(
                baseline_metrics={"map50_95": 0.60},
                candidate_metrics={"map50_95": 0.64},
            ),
        )
        assert result.all_required_gates_passed
        assert not result.promoted
        assert result.cycle.status == "retained_baseline"
        assert result.cycle.promotion_results[0].passed


def test_active_learning_comparison_blocks_explicitly_incompatible_datasets(
    client: TestClient,
) -> None:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        project = Project(
            name="Incompatible comparison project",
            slug="incompatible-comparison-project",
            storage_root="projects/incompatible-comparison-project",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        service = PublicActiveLearningCycleService(session)
        cycle = service.create(
            project.id,
            ActiveLearningCycleCreateRequest(
                name="Compatibility check",
                selection_strategy="blended",
                annotation_budget=1,
            ),
        )
        row = session.get(ActiveLearningCycle, cycle.id)
        assert row is not None
        row.status = "evaluation"
        session.commit()

        result = service.evaluate_and_promote(
            cycle.id,
            ActiveLearningEvaluationRequest(
                baseline_metrics={"map50_95": 0.60},
                candidate_metrics={"map50_95": 0.70},
                baseline_dataset_version_id="dataset-baseline",
                candidate_dataset_version_id="dataset-candidate",
                baseline_metric_schema_id="ultralytics-detect-v1",
                candidate_metric_schema_id="ultralytics-detect-v1",
            ),
        )

        assert not result.comparison_compatible
        assert not result.all_required_gates_passed
        assert not result.promoted
        assert any(
            "different immutable dataset" in warning for warning in result.compatibility_warnings
        )
        assert result.compatibility_warnings == result.cycle.warnings


def test_cycle_training_requires_a_distinct_model_registered_from_that_run(
    client: TestClient,
) -> None:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        project = Project(
            name="Training lineage project",
            slug="training-lineage-project",
            storage_root="projects/training-lineage-project",
        )
        session.add(project)
        session.flush()
        source = ModelRegistration(
            project_id=project.id,
            purpose="detector",
            display_name="Source model",
            source_filename="source.pt",
            managed_path=f"projects/{project.id}/models/source.pt",
            sha256="a" * 64,
            file_size_bytes=10,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            metadata_json={},
        )
        run = TrainingRun(
            project_id=project.id,
            dataset_manifest_sha256="b" * 64,
            split_manifest_sha256="c" * 64,
            task="detect",
            provider_id="ultralytics",
            architecture="YOLO11n",
            initial_checkpoint_source="catalog",
            device="cpu",
            precision="fp32",
            run_name="Cycle retraining",
            status="completed",
            stage="completed",
        )
        session.add_all([source, run])
        session.flush()
        unrelated = ModelRegistration(
            project_id=project.id,
            purpose="detector",
            display_name="Unrelated model",
            source_filename="unrelated.pt",
            managed_path=f"projects/{project.id}/models/unrelated.pt",
            sha256="d" * 64,
            file_size_bytes=11,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            metadata_json={"source_training_run_id": "different-run"},
        )
        candidate = ModelRegistration(
            project_id=project.id,
            purpose="detector",
            display_name="Cycle candidate",
            source_filename="candidate.pt",
            managed_path=f"projects/{project.id}/models/candidate.pt",
            sha256="e" * 64,
            file_size_bytes=12,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            metadata_json={"source_training_run_id": run.id},
        )
        session.add_all([unrelated, candidate])
        session.commit()

        service = PublicActiveLearningCycleService(session)
        cycle = service.create(
            project.id,
            ActiveLearningCycleCreateRequest(
                name="Training cycle",
                selection_strategy="blended",
                annotation_budget=1,
                source_model_id=source.id,
            ),
        )
        row = session.get(ActiveLearningCycle, cycle.id)
        assert row is not None
        row.status = "dataset_frozen"
        session.commit()

        with pytest.raises(ValidationError, match="registered from the attached training run"):
            service.record_training(
                cycle.id,
                ActiveLearningTrainingRecordRequest(
                    training_run_id=run.id,
                    candidate_model_id=unrelated.id,
                ),
            )

        recorded = service.record_training(
            cycle.id,
            ActiveLearningTrainingRecordRequest(
                training_run_id=run.id,
                candidate_model_id=candidate.id,
            ),
        )
        assert recorded.status == "evaluation"
        assert recorded.source_model_id == source.id
        assert recorded.candidate_model_id == candidate.id
        assert recorded.source_model_id != recorded.candidate_model_id

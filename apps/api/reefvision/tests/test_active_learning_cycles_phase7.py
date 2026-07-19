from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.db.models import ActiveLearningCycle, Project
from reefvision.schemas.active_learning_cycles import (
    ActiveLearningCycleCreateRequest,
    ActiveLearningEvaluationRequest,
    ActiveLearningReviewProgressRequest,
    ActiveLearningSelectionRecordRequest,
    PromotionGate,
)
from reefvision.services.active_learning_cycle_api import (
    PublicActiveLearningCycleService,
)


def test_active_learning_cycle_records_selection_review_and_promotion_gates(
    client: TestClient,
) -> None:
    with client.app.state.session_factory() as session:
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

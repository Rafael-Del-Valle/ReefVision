"""Scientific deployment safeguards; no detector model may be touched."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.segmentation_deployment import SegmentationPromoteRequest
from reefvision.services.segmentation_deployment import SegmentationDeploymentService


def fixture(
    monkeypatch,
) -> tuple[SegmentationDeploymentService, Mock, SimpleNamespace, SimpleNamespace, Job]:
    from reefvision.services import segmentation_deployment as module

    session = Mock()
    candidate = SimpleNamespace(
        id="segment-candidate",
        sha256="b" * 64,
        managed_path="project/segment-candidate.pt",
        metadata_json={},
        purpose="segmenter",
        task="segment",
    )
    detector = SimpleNamespace(
        id="detector-1",
        metadata_json={"active_for_predictions": True},
        purpose="detector",
        task="detect",
    )
    evaluation = Job(
        id="evaluation-1",
        project_id="p",
        status="completed",
        job_type="segmentation_learning_evaluation",
        request_json={
            "task": "segment",
            "candidate_model_id": candidate.id,
            "candidate_checksum": candidate.sha256,
            "incumbent_model_id": None,
            "manifest_sha256": "a" * 64,
            "dataset_version_id": "version-1",
        },
        result_json={
            "promotion_eligible": True,
            "blockers": [],
            "candidate_metrics": {
                "mask_map50": 1,
                "mean_absolute_count_error": 0,
            },
        },
    )
    service = SegmentationDeploymentService(session, cast(Settings, Mock()))
    monkeypatch.setattr(service, "_lock_project", lambda _project: None)
    monkeypatch.setattr(service, "_evaluation", lambda _p, _e: evaluation)
    monkeypatch.setattr(service, "_models", lambda _p: [candidate])
    monkeypatch.setattr(module, "verify_learning_content", lambda *_: None)
    session.scalars.return_value = []

    def flush() -> None:
        for call in session.add.call_args_list:
            record = call.args[0]
            if record.id is None:
                record.id = "deployment-1"

    session.flush.side_effect = flush
    return service, session, candidate, detector, evaluation


def test_manual_promotion_is_audited_and_detector_metadata_unchanged(monkeypatch) -> None:
    service, session, candidate, detector, _evaluation = fixture(monkeypatch)
    result = service.promote(
        "p",
        "evaluation-1",
        expected_active_model_id=None,
        approved_by="lab_reviewer",
        reason="Candidate passed held-out mask AP50 tests",
    )
    assert result.job_type == "segmentation_learning_deployment"
    assert result.request_json["approved_by"] == "lab_reviewer"
    assert result.result_json["evaluation_metrics_sha256"]
    assert candidate.metadata_json["active_for_predictions"] is True
    assert candidate.metadata_json["active_segmentation_deployment_id"] == result.id
    assert detector.metadata_json == {"active_for_predictions": True}
    session.commit.assert_called_once()


def test_promotion_refuses_stale_expected_active_model(monkeypatch) -> None:
    service, session, candidate, _detector, _evaluation = fixture(monkeypatch)
    candidate.metadata_json = {"active_for_predictions": True}
    with pytest.raises(ConflictError, match="changed"):
        service.promote(
            "p",
            "evaluation-1",
            expected_active_model_id=None,
            approved_by="lab_reviewer",
            reason="Holdout metrics reviewed and approved",
        )
    session.commit.assert_not_called()


def test_promotion_refuses_repeat_evaluation(monkeypatch) -> None:
    service, session, _candidate, _detector, _evaluation = fixture(monkeypatch)
    session.scalars.return_value = [
        Job(
            project_id="p",
            job_type="segmentation_learning_deployment",
            request_json={"evaluation_id": "evaluation-1"},
        )
    ]
    with pytest.raises(ConflictError, match="already been deployed"):
        service.promote(
            "p",
            "evaluation-1",
            expected_active_model_id=None,
            approved_by="lab_reviewer",
            reason="Holdout metrics reviewed and approved",
        )
    session.commit.assert_not_called()


def test_rollback_cannot_override_newer_deployment(monkeypatch) -> None:
    service, session, candidate, _detector, _evaluation = fixture(monkeypatch)
    deployment = service.promote(
        "p",
        "evaluation-1",
        expected_active_model_id=None,
        approved_by="lab_reviewer",
        reason="Holdout metrics reviewed and approved",
    )
    session.get.return_value = deployment
    candidate.metadata_json["active_segmentation_deployment_id"] = "newer-deployment"
    with pytest.raises(ConflictError, match="no longer current"):
        service.rollback(
            "p",
            deployment.id,
            expected_active_model_id=candidate.id,
            approved_by="lab_reviewer",
            reason="Restore preceding model after observed drift",
        )


def test_rollback_restores_no_active_model_with_audit(monkeypatch) -> None:
    service, session, candidate, _detector, _evaluation = fixture(monkeypatch)
    deployment = service.promote(
        "p",
        "evaluation-1",
        expected_active_model_id=None,
        approved_by="lab_reviewer",
        reason="Holdout metrics reviewed and approved",
    )
    session.get.return_value = deployment
    session.add.reset_mock()
    result = service.rollback(
        "p",
        deployment.id,
        expected_active_model_id=candidate.id,
        approved_by="lab_reviewer",
        reason="Rollback after deployment inspection",
    )
    assert result.job_type == "segmentation_learning_deployment_rollback"
    assert result.request_json["deployment_id"] == deployment.id
    assert candidate.metadata_json["active_for_predictions"] is False
    assert "active_segmentation_deployment_id" not in candidate.metadata_json


def test_explicit_expected_active_field_required() -> None:
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        SegmentationPromoteRequest(
            approved_by="lab_reviewer",
            reason="Holdout metrics reviewed and approved",
        )


def test_approval_reason_cannot_be_empty(monkeypatch) -> None:
    service, _session, _candidate, _detector, _evaluation = fixture(monkeypatch)
    with pytest.raises(ValidationError):
        service.promote(
            "p",
            "evaluation-1",
            expected_active_model_id=None,
            approved_by="",
            reason="short",
        )

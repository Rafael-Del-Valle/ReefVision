from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.jobs.workflow_consensus as workflow_consensus
from reefvision.db.models import Job, MaskAnnotation, PredictionProposal
from reefvision.domain.errors import ValidationError
from reefvision.services.multi_model_auto_labeling import (
    MaskVote,
    apply_multi_model_mask_consensus,
)
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_segmentation_prediction_review_safety import (
    _seed_review_proposals,
)


@dataclass(frozen=True)
class _FakeVoter:
    voter_name: str
    model_name: str
    accepted: bool
    confidence: float

    def vote(
        self,
        *,
        prompt: str,
        candidate_label: str,
        source_crop_png: bytes,
        overlay_crop_png: bytes,
    ) -> MaskVote:
        assert prompt
        assert candidate_label == "soft coral"
        assert source_crop_png.startswith(b"\x89PNG")
        assert overlay_crop_png.startswith(b"\x89PNG")
        return MaskVote(
            voter=self.voter_name,
            model=self.model_name,
            accepted=self.accepted,
            confidence=self.confidence,
            reason="deterministic test vote",
        )


def _settings_and_factory(client: TestClient):
    app = cast(FastAPI, client.app)
    settings = app.state.settings.model_copy(update={"allow_remote_vision": True})
    return settings, app.state.session_factory


def _configuration() -> dict[str, object]:
    return {
        "prompt": "soft coral colony",
        "required_votes": 2,
        "sam_vote_threshold": 0.5,
        "minimum_reviewer_confidence": 0.5,
        "allow_remote_review": True,
        "auto_accept": True,
        "fail_closed": True,
    }


def test_two_of_three_votes_promote_verified_raster_mask(client: TestClient) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="polygon_mask")
    proposal_id = fixture.proposal_ids[0]
    settings, factory = _settings_and_factory(client)

    result = apply_multi_model_mask_consensus(
        settings,
        factory,
        prediction_ids=[proposal_id],
        consensus_configuration=_configuration(),
        workflow_run_id="workflow-run-1",
        workflow_node_id="segment-and-vote",
        voters=[
            _FakeVoter("gemini", "gemini-test", True, 0.91),
            _FakeVoter("openai", "gpt-test", False, 0.88),
        ],
    )

    assert result.evaluated_count == 1
    assert result.consensus_count == 1
    assert result.promoted_count == 1
    candidate = result.candidates[0]
    assert candidate.accepted_vote_count == 2
    assert candidate.mask_annotation_id is not None

    with factory() as session:
        proposal = session.get(PredictionProposal, proposal_id)
        annotation = session.get(MaskAnnotation, candidate.mask_annotation_id)
        assert proposal is not None
        assert annotation is not None
        assert proposal.review_status == "accepted"
        assert proposal.accepted_mask_annotation_id == annotation.id
        assert annotation.geometry_kind == "raster_mask"
        assert annotation.status == "verified"
        assert annotation.source_type == "workflow_consensus"
        provenance = dict(annotation.provenance_json or {})
        assert provenance["workflow_run_id"] == "workflow-run-1"
        assert provenance["required_votes"] == 2
        assert provenance["accepted_vote_count"] == 2
        assert len(provenance["votes"]) == 3
        assert annotation.mask_path is not None
        path = resolve_managed_project_path(settings, annotation.mask_path)
        assert path.is_file()


def test_one_of_three_votes_leave_proposal_pending(client: TestClient) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="raster_mask")
    proposal_id = fixture.proposal_ids[1]
    settings, factory = _settings_and_factory(client)

    result = apply_multi_model_mask_consensus(
        settings,
        factory,
        prediction_ids=[proposal_id],
        consensus_configuration=_configuration(),
        workflow_run_id="workflow-run-2",
        workflow_node_id="segment-and-vote",
        voters=[
            _FakeVoter("gemini", "gemini-test", False, 0.94),
            _FakeVoter("openai", "gpt-test", False, 0.93),
        ],
    )

    assert result.consensus_count == 0
    assert result.promoted_count == 0
    assert result.pending_count == 1
    with factory() as session:
        proposal = session.get(PredictionProposal, proposal_id)
        assert proposal is not None
        assert proposal.review_status == "pending"
        consensus = dict(proposal.provenance_json or {})["workflow_consensus"]
        assert consensus["accepted_vote_count"] == 1
        assert consensus["consensus_reached"] is False


def test_remote_consensus_requires_double_opt_in(client: TestClient) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="polygon_mask")
    app = cast(FastAPI, client.app)
    disabled = app.state.settings.model_copy(update={"allow_remote_vision": False})

    with pytest.raises(ValidationError, match="REEFVISION_ALLOW_REMOTE_VISION"):
        apply_multi_model_mask_consensus(
            disabled,
            app.state.session_factory,
            prediction_ids=[fixture.proposal_ids[0]],
            consensus_configuration=_configuration(),
            workflow_run_id="workflow-run-3",
            workflow_node_id="segment-and-vote",
            voters=[
                _FakeVoter("gemini", "gemini-test", True, 0.9),
                _FakeVoter("openai", "gpt-test", True, 0.9),
            ],
        )


def test_named_consensus_workflow_rejects_non_sam3_primary_model(
    client: TestClient,
) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="polygon_mask")
    app = cast(FastAPI, client.app)

    with pytest.raises(RuntimeError, match="sam3_sidecar"):
        workflow_consensus._require_primary_provider(
            app.state.session_factory,
            model_id=fixture.model_id,
            required_provider="sam3_sidecar",
        )


def test_workflow_inference_compatibility_normalizes_confidence_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="polygon_mask")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        job = Job(
            project_id=fixture.project_id,
            job_type="inference",
            status="queued",
            progress_total=1,
            request_json={"confidence": 0.37},
        )
        session.add(job)
        session.commit()
        job_id = job.id

    observed: dict[str, object] = {}

    def fake_original(settings, factory, target_job_id: str) -> bool:
        with factory() as session:
            target = session.get(Job, target_job_id)
            assert target is not None
            observed.update(dict(target.request_json))
        return True

    monkeypatch.setattr(
        workflow_consensus,
        "_ORIGINAL_PROCESS_INFERENCE",
        fake_original,
    )
    assert workflow_consensus._workflow_inference_request_compatibility(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )
    assert observed["confidence_threshold"] == 0.37
    assert observed["iou_threshold"] == app.state.settings.inference_default_iou


def test_workflow_templates_expose_multi_model_auto_labeling(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/workflow-templates")
    assert response.status_code == 200, response.text
    templates = {item["template_id"]: item for item in response.json()}
    template = templates["multi-model-segmentation-auto-labeling"]
    node = next(
        item
        for item in template["workflow"]["nodes"]
        if item["id"] == "segment-and-vote"
    )
    consensus = node["configuration"]["multi_model_consensus"]
    assert consensus["required_votes"] == 2
    assert consensus["required_primary_provider"] == "sam3_sidecar"
    assert consensus["auto_accept"] is True
    assert consensus["allow_remote_review"] is False

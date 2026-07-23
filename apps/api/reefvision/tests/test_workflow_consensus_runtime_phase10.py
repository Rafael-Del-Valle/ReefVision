from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.jobs.workflow_consensus as workflow_consensus
from reefvision.db.models import ModelRegistration, WorkflowRun
from reefvision.tests.test_annotations import create_project


def test_consensus_wrapper_enriches_masks_artifact(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Consensus runtime")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=project["id"],
            purpose="segmenter",
            display_name="SAM 3 runtime test",
            source_filename="sam3.sam3.json",
            managed_path=f"{project['storage_root']}/models/sam3-runtime-test.json",
            sha256="a" * 64,
            file_size_bytes=1,
            framework="sam3-sidecar",
            task="segment",
            provider_name="sam3_sidecar",
            provider_version="test",
            class_map_json={},
            input_size_json=None,
            metadata_json={},
        )
        session.add(model)
        session.commit()
        model_id = model.id

    run = WorkflowRun(
        id="workflow-runtime-test",
        workflow_id="workflow-test",
        workflow_revision_id="revision-test",
        project_id=project["id"],
        status="running",
        stage="running",
        current_node_id="segment-and-vote",
        input_json={},
        result_json={},
        node_state_json={},
    )

    def fake_original(
        _settings,
        _factory,
        _current_run,
        node_type: str,
        _configuration: dict[str, Any],
        _inputs,
    ):
        assert node_type == "segmenter"
        return {
            "masks": (
                "masks",
                {
                    "image_ids": ["image-1"],
                    "prediction_ids": ["proposal-1"],
                    "model_id": model_id,
                    "child_job_id": "child-1",
                },
            )
        }

    class _Result:
        def as_payload(self) -> dict[str, Any]:
            return {
                "requested_count": 1,
                "evaluated_count": 1,
                "consensus_count": 1,
                "promoted_count": 1,
                "pending_count": 0,
                "failed_count": 0,
                "candidates": [
                    {
                        "proposal_id": "proposal-1",
                        "image_id": "image-1",
                        "accepted_vote_count": 2,
                        "required_votes": 2,
                        "consensus_reached": True,
                        "auto_promoted": True,
                        "mask_annotation_id": "mask-1",
                        "votes": [],
                    }
                ],
            }

    def fake_consensus(*_args, **_kwargs) -> _Result:
        return _Result()

    monkeypatch.setattr(workflow_consensus, "_ORIGINAL_MODEL_INFERENCE", fake_original)
    monkeypatch.setattr(
        workflow_consensus,
        "apply_multi_model_mask_consensus",
        fake_consensus,
    )
    outputs = workflow_consensus._consensus_aware_model_inference(
        app.state.settings,
        app.state.session_factory,
        run,
        "segmenter",
        {
            "model_id": model_id,
            "multi_model_consensus": {
                "enabled": True,
                "mode": "semantic_voters",
                "required_primary_provider": "sam3_sidecar",
            },
        },
        [],
    )

    payload = outputs["masks"][1]
    assert payload["mask_annotation_ids"] == ["mask-1"]
    assert payload["auto_labeling_mode"] == "semantic_review_two_of_three"
    assert payload["consensus"]["promoted_count"] == 1

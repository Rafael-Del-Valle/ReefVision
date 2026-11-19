"""Tampered frozen coral rows must fail standalone and saved QC without rewriting review."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import DatasetVersionItem, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.schemas.review_queues import ReviewQueueCreateRequest
from reefvision.services.frozen_dataset_integrity_16 import _item_payload
from reefvision.services.review_queues import ReviewQueueService
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_review_queue_annotation_evidence_16 import _queue_item
from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
    _frozen_graph,
    _run_frozen_graph,
    _study,
)


@pytest.mark.parametrize(
    "tamper",
    [
        "geometry",
        "resigned_geometry",
        "split",
        "per_class_counts",
        "original_filename",
        "snapshot_digest",
    ],
)
def test_frozen_item_evidence_cannot_change_under_standalone_or_saved_qc(
    client: TestClient, tamper: str
) -> None:
    project_id, _, version_id, _ = _study(client)
    standalone = client.post(f"/api/v1/dataset-versions/{version_id}/review-queues", json={})
    assert standalone.status_code == 201, standalone.text
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": _frozen_graph(version_id)},
    )
    assert saved.status_code == 201, saved.text
    run_id, payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    workflow_url = f"/api/v1/review-queues/{payload['queue_id']}/items"
    before = client.get(workflow_url)
    assert before.status_code == 200, before.text
    assert payload["review_status"] == "requires_researcher_review"
    assert payload["priority_score_unit"] == "dimensionless"

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        frozen = session.scalar(
            select(DatasetVersionItem).where(DatasetVersionItem.dataset_version_id == version_id)
        )
        assert frozen is not None
        if tamper in {"geometry", "resigned_geometry"}:
            annotations = [dict(annotation) for annotation in frozen.annotation_snapshot_json]
            assert len(annotations) == 1
            annotations[0]["x_min"] = float(annotations[0]["x_min"]) + 3.0
            frozen.annotation_snapshot_json = annotations
            if tamper == "resigned_geometry":
                frozen.snapshot_sha256 = canonical_json_sha256(_item_payload(frozen))
        elif tamper == "split":
            frozen.split = "train" if frozen.split != "train" else "test"
        elif tamper == "per_class_counts":
            frozen.per_class_counts_json = {"forged_taxon": 1}
        elif tamper == "original_filename":
            frozen.original_filename = "other-coral.png"
        else:
            frozen.snapshot_sha256 = "f" * 64
        session.flush()

        # Standalone and the persisted typed Workflow Builder adapter share
        # the same immutable source check. Neither can silently create a
        # replacement review queue or infer verification from altered media.
        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            ReviewQueueService(session, app.state.settings).create_queue_for_dataset_version(
                version_id, ReviewQueueCreateRequest()
            )

        node_runs = session.scalars(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        ).all()
        nodes = {node.node_type: node for node in node_runs}
        project_source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == nodes["project_source"].id,
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        dataset_source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == nodes["dataset_version_source"].id,
                WorkflowArtifact.producer_port_id == "dataset",
            )
        )
        assert project_source is not None and dataset_source is not None
        qc_node = nodes["qc_review_queue"]
        params = {
            **dict(qc_node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": qc_node.id,
        }
        inputs = {"project": [project_source], "dataset": [dataset_source]}
        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, params, inputs
            )
        session.rollback()
        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, params, inputs
        )
        assert replay[0]["payload"] == payload
        session.rollback()

    after = client.get(workflow_url)
    assert after.status_code == 200, after.text
    assert after.json() == before.json()
    assert _queue_item(client, standalone.json()["id"])["review_state"] == "pending"

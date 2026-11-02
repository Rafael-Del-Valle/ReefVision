"""Frozen QC workflows reject re-signed dataset substitutions and broken upstream lineage."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import DatasetVersion, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_dataset_versions import create_version
from reefvision.tests.test_review_queue_annotation_evidence_16 import _queue_item
from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
    _frozen_graph,
    _run_frozen_graph,
    _study,
)


@pytest.mark.parametrize(
    "tamper",
    [
        "resigned_other_version",
        "producer_other_version",
        "producer_filtered_split",
        "producer_project_binding",
    ],
)
def test_saved_frozen_qc_rejects_dataset_producer_mismatch(
    client: TestClient, tamper: str
) -> None:
    project_id, _, version_id, _ = _study(client)
    graph = _frozen_graph(version_id)
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run_id, payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    other_id = None
    if tamper in {"resigned_other_version", "producer_other_version"}:
        other = create_version(client, project_id, name="Independent frozen coral study")
        other_id = other["id"]
        assert other_id != version_id

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        node_runs = session.scalars(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        ).all()
        by_type = {node.node_type: node for node in node_runs}
        project_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == by_type["project_source"].id,
                WorkflowArtifact.producer_port_id == "project",
            )
        )
        dataset_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == by_type["dataset_version_source"].id,
                WorkflowArtifact.producer_port_id == "dataset",
            )
        )
        assert project_artifact is not None and dataset_artifact is not None
        producer = by_type["dataset_version_source"]
        assert producer.input_artifact_ids_json == [project_artifact.id]

        if tamper == "resigned_other_version":
            assert other_id is not None
            other_version = session.get(DatasetVersion, other_id)
            assert other_version is not None
            dataset_artifact.payload_json = {
                **dataset_artifact.payload_json,
                "dataset_version_id": other_id,
                "manifest_sha256": other_version.manifest_sha256,
            }
            dataset_artifact.payload_sha256 = canonical_json_sha256(dataset_artifact.payload_json)
        elif tamper == "producer_other_version":
            assert other_id is not None
            producer.parameters_json = {**producer.parameters_json, "dataset_version_id": other_id}
        elif tamper == "producer_filtered_split":
            producer.parameters_json = {**producer.parameters_json, "split": "train"}
        else:
            producer.input_artifact_ids_json = []

        session.flush()
        qc_node = by_type["qc_review_queue"]
        with pytest.raises(ValidationError, match="dataset producer provenance"):
            create_review_queue_workflow_artifact(
                session,
                app.state.settings,
                project_id,
                {
                    **dict(qc_node.parameters_json or {}),
                    "__workflow_run_id": run_id,
                    "__workflow_node_run_id": qc_node.id,
                },
                {"project": [project_artifact], "dataset": [dataset_artifact]},
            )
        session.rollback()

    # Failed replay cannot mutate historical human-review state or scientific evidence.
    assert _queue_item(client, payload["queue_id"])["review_state"] == "pending"

"""Rehashed frozen mask IDs must not create new standalone or saved review evidence."""

from __future__ import annotations

from copy import deepcopy
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    WorkflowArtifact,
    WorkflowNodeRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.review_queues import ReviewQueueCreateRequest
from reefvision.services.frozen_dataset_integrity_16 import (
    _item_payload,
    validate_frozen_dataset_manifest,
)
from reefvision.services.review_queues import ReviewQueueService
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_dataset_versions import create_version
from reefvision.tests.test_mask_dataset_exports import _save_polygon
from reefvision.tests.test_review_queue_annotation_evidence_16 import _queue_item
from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
    _frozen_graph,
    _run_frozen_graph,
)


@pytest.mark.parametrize("tamper", ["duplicate", "missing"])
def test_resigned_mask_ids_fail_standalone_and_saved_frozen_qc(
    client: TestClient, tamper: str
) -> None:
    project = create_project(client, "Frozen coral mask identity study")
    project_id = project["id"]
    imported = import_one(client, project_id, filename="mask-identity.png")
    image_id = imported["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    _save_polygon(
        client,
        image_id=image_id,
        class_id=class_id,
        mask_id=str(uuid4()),
        points=[(5, 5), (30, 5), (30, 30), (5, 30)],
        base_revision=0,
    )
    version_id = create_version(client, project_id, name="Frozen mask identity")["id"]
    standalone = client.post(
        f"/api/v1/dataset-versions/{version_id}/review-queues", json={}
    )
    assert standalone.status_code == 201, standalone.text
    graph = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": _frozen_graph(version_id)},
    )
    assert graph.status_code == 201, graph.text
    run_id, output = _run_frozen_graph(client, project_id, graph.json()["id"])
    assert output["priority_score_unit"] == "dimensionless"
    assert output["review_status"] == "requires_researcher_review"
    review_url = f"/api/v1/review-queues/{output['queue_id']}/items"
    original_response = client.get(review_url)
    assert original_response.status_code == 200

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        version = session.get(DatasetVersion, version_id)
        item = session.scalar(
            select(DatasetVersionItem).where(
                DatasetVersionItem.dataset_version_id == version_id
            )
        )
        assert version is not None and item is not None
        assert version.schema_version == "0007"
        assert item.mask_annotation_count == 1
        validate_frozen_dataset_manifest(version, [item])

        masks = deepcopy(item.mask_annotation_snapshot_json)
        if tamper == "duplicate":
            masks.append(deepcopy(masks[0]))
            item.mask_annotation_count = 2
            item.per_mask_class_counts_json = {class_id: 2}
            version.mask_annotation_count = 2
        else:
            masks[0].pop("id")
        item.mask_annotation_snapshot_json = masks
        payload = _item_payload(item, schema_version="0007")
        item.snapshot_sha256 = canonical_json_sha256(payload)
        manifest = deepcopy(version.manifest_json)
        manifest["summary"]["mask_annotation_count"] = version.mask_annotation_count
        manifest["items"] = [{**payload, "snapshot_sha256": item.snapshot_sha256}]
        version.manifest_json = manifest
        version.manifest_sha256 = canonical_json_sha256(manifest)
        session.flush()

        # Even fully recomputed checksums must not authorize duplicate or
        # unidentified masks in a completed biological study.
        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            validate_frozen_dataset_manifest(version, [item])
        with pytest.raises(ValidationError, match="Frozen dataset item snapshot"):
            ReviewQueueService(session, app.state.settings).create_queue_for_dataset_version(
                version_id, ReviewQueueCreateRequest()
            )

        nodes = {
            node.node_type: node
            for node in session.scalars(
                select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
            )
        }
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
        parameters = {
            **dict(qc_node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": qc_node.id,
        }
        inputs = {"project": [project_source], "dataset": [dataset_source]}
        # Saved typed dataset artifacts retain the original manifest digest;
        # producer provenance rejects a completely rehashed replacement first.
        with pytest.raises(
            ValidationError, match="QC Review Queue dataset version or manifest does not match"
        ):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, parameters, inputs
            )
        session.rollback()

        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, parameters, inputs
        )
        assert replay[0]["payload"] == output
        session.rollback()

    current_response = client.get(review_url)
    assert current_response.status_code == 200
    assert current_response.json() == original_response.json()
    assert _queue_item(client, standalone.json()["id"])["review_state"] == "pending"

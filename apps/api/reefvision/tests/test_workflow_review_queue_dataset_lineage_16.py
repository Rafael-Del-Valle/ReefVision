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
from reefvision.tests.test_dataset_versions import create_version, import_image, update_image
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
        "producer_extra_output",
        "producer_missing_images_output",
        "producer_wrong_images_binding",
        "producer_resigned_images_artifact",
        "producer_resigned_image_ids",
        "producer_reordered_images",
        "metadata_version_number",
        "metadata_split_method",
        "metadata_split_counts",
        "metadata_image_count",
        "metadata_annotation_count",
        "metadata_mask_annotation_count",
        "metadata_missing_split_counts",
        "metadata_boolean_image_count",
        "metadata_boolean_split_count",
        "metadata_float_split_count",
    ],
)
def test_saved_frozen_qc_rejects_dataset_producer_mismatch(client: TestClient, tamper: str) -> None:
    project_id, _, version_id, _ = _study(client)
    if tamper == "producer_reordered_images":
        imported = import_image(
            client,
            project_id,
            filename="second-coral.png",
            relative_path="frozen/second-coral.png",
            color=(80, 20, 190),
        )
        second_id = imported["successful"][0]["image_id"]
        update_image(client, second_id, group_key=None, annotation_status="reviewed")
        version_id = create_version(client, project_id, name="Two-image frozen study")["id"]
    graph = _frozen_graph(version_id)
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run_id, payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    queue_url = f"/api/v1/review-queues/{payload['queue_id']}/items"
    original_response = client.get(queue_url)
    assert original_response.status_code == 200, original_response.text
    original_items = original_response.json()["items"]
    expected_count = 2 if tamper == "producer_reordered_images" else 1
    assert original_response.json()["total"] == expected_count
    assert len(original_items) == expected_count
    assert all(item["review_state"] == "pending" for item in original_items)

    if tamper == "producer_reordered_images":
        # The two-image frozen study must produce identical standalone and
        # executable saved-workflow scientific QC evidence before corruption.
        standalone = client.post(f"/api/v1/dataset-versions/{version_id}/review-queues", json={})
        assert standalone.status_code == 201, standalone.text
        standalone_response = client.get(f"/api/v1/review-queues/{standalone.json()['id']}/items")
        assert standalone_response.status_code == 200, standalone_response.text
        assert standalone_response.json()["total"] == expected_count
        assert sorted(
            (item["image_id"], item["input_checksum"], item["score"])
            for item in standalone_response.json()["items"]
        ) == sorted(
            (item["image_id"], item["input_checksum"], item["score"]) for item in original_items
        )
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
        images_artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.producer_node_run_id == by_type["dataset_version_source"].id,
                WorkflowArtifact.producer_port_id == "images",
            )
        )
        assert project_artifact is not None and dataset_artifact is not None
        assert images_artifact is not None
        producer = by_type["dataset_version_source"]
        assert producer.input_artifact_ids_json == [project_artifact.id]
        assert producer.output_artifact_ids_json == [
            dataset_artifact.id,
            images_artifact.id,
        ]

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
        elif tamper == "producer_project_binding":
            producer.input_artifact_ids_json = []
        elif tamper == "producer_extra_output":
            producer.output_artifact_ids_json = [
                dataset_artifact.id,
                images_artifact.id,
                project_artifact.id,
            ]
        elif tamper == "producer_missing_images_output":
            producer.output_artifact_ids_json = [dataset_artifact.id]
        elif tamper == "producer_wrong_images_binding":
            producer.output_artifact_ids_json = [images_artifact.id, dataset_artifact.id]
        elif tamper == "producer_reordered_images":
            original_ids = images_artifact.payload_json["image_ids"]
            assert len(original_ids) == 2 and original_ids[0] != original_ids[1]
            images_artifact.payload_json = {
                **images_artifact.payload_json,
                "image_ids": list(reversed(original_ids)),
            }
            images_artifact.payload_sha256 = canonical_json_sha256(images_artifact.payload_json)
        elif tamper.startswith("metadata_"):
            field, replacement = {
                "metadata_version_number": ("version_number", -1),
                "metadata_split_method": ("split_method", "forged-split-method"),
                "metadata_split_counts": ("split_counts", {"train": 999}),
                "metadata_image_count": ("image_count", -1),
                "metadata_annotation_count": ("annotation_count", -1),
                "metadata_mask_annotation_count": ("mask_annotation_count", -1),
                "metadata_boolean_image_count": ("image_count", True),
            }.get(tamper, ("split_counts", None))
            metadata = dict(dataset_artifact.payload_json)
            if tamper in {"metadata_boolean_split_count", "metadata_float_split_count"}:
                counts = dict(metadata["split_counts"])
                first_split = next(iter(counts))
                assert counts[first_split] == 1
                if tamper == "metadata_boolean_split_count":
                    counts[first_split] = True
                else:
                    counts[first_split] = 1.0
                metadata["split_counts"] = counts
            elif tamper == "metadata_missing_split_counts":
                metadata.pop(field)
            else:
                metadata[field] = replacement
            dataset_artifact.payload_json = metadata
            dataset_artifact.payload_sha256 = canonical_json_sha256(metadata)
        elif tamper == "producer_resigned_images_artifact":
            images_artifact.payload_json = {
                **images_artifact.payload_json,
                "dataset_manifest_sha256": "0" * 64,
            }
            images_artifact.payload_sha256 = canonical_json_sha256(images_artifact.payload_json)
        else:
            images_artifact.payload_json = {
                **images_artifact.payload_json,
                "image_ids": ["forged-image-id"],
            }
            images_artifact.payload_sha256 = canonical_json_sha256(images_artifact.payload_json)

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

        # Restoring the exact saved producer binding must replay the original
        # immutable queue, not regenerate evidence or alter reviewer state.
        replay = create_review_queue_workflow_artifact(
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
        assert replay[0]["payload"] == payload
        session.rollback()

    # Failed replay cannot mutate any historical human-review state or
    # scientific evidence, including multi-image frozen studies.
    final_response = client.get(queue_url)
    assert final_response.status_code == 200, final_response.text
    assert final_response.json()["total"] == expected_count
    assert final_response.json()["items"] == original_items



def test_completed_frozen_qc_replay_rejects_erased_output_binding(client: TestClient) -> None:
    """A finished node cannot replay a queue after its saved output is erased."""
    project_id, _, version_id, _ = _study(client)
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": _frozen_graph(version_id)},
    )
    assert saved.status_code == 201, saved.text
    run_id, payload = _run_frozen_graph(client, project_id, saved.json()["id"])
    queue_url = f"/api/v1/review-queues/{payload['queue_id']}/items"
    before = client.get(queue_url)
    assert before.status_code == 200, before.text
    assert all(item["review_state"] == "pending" for item in before.json()["items"])
    assert payload["review_status"] == "requires_researcher_review"
    assert payload["priority_score_unit"] == "dimensionless"

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        node_runs = session.scalars(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        ).all()
        by_type = {node.node_type: node for node in node_runs}
        qc_node = by_type["qc_review_queue"]
        assert qc_node.status == "succeeded"
        assert len(qc_node.output_artifact_ids_json) == 1
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
        params = {
            **dict(qc_node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": qc_node.id,
        }
        inputs = {"project": [project_artifact], "dataset": [dataset_artifact]}

        # Re-signed payloads are irrelevant when a completed node has no
        # persisted output binding; reject before any evidence regeneration.
        qc_node.output_artifact_ids_json = []
        session.flush()
        with pytest.raises(ValidationError, match="missing saved output binding"):
            create_review_queue_workflow_artifact(
                session, app.state.settings, project_id, params, inputs
            )
        session.rollback()

        # Rollback restores the original binding, and the exact original
        # scientific queue can still be replayed without researcher approval.
        replay = create_review_queue_workflow_artifact(
            session, app.state.settings, project_id, params, inputs
        )
        assert replay[0]["payload"] == payload
        session.rollback()

    after = client.get(queue_url)
    assert after.status_code == 200, after.text
    assert after.json() == before.json()

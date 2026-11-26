"""Public QC creators cannot impersonate saved workflows or poison their retries."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ReviewQueue, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project, import_one


@pytest.mark.parametrize("creator", ["workflow:forged:node", "  WORKFLOW:forged:node"])
def test_public_qc_creation_cannot_claim_internal_workflow_owner(
    client: TestClient, creator: str
) -> None:
    project = create_project(client, "Reserved QC workflow owner")
    project_id = project["id"]
    imported = import_one(
        client,
        project_id,
        filename="reserved-workflow-owner.png",
        relative_path="qc/reserved-workflow-owner.png",
    )
    assert len(imported["successful"]) == 1

    # Both public creation routes must reject forged internal ownership.
    rejected = client.post(
        f"/api/v1/projects/{project_id}/review-queues",
        json={"created_by": creator},
    )
    assert rejected.status_code == 422, rejected.text
    assert "reserved" in rejected.json()["detail"]
    rejected_dataset = client.post(
        "/api/v1/dataset-versions/not-a-version/review-queues",
        json={"created_by": creator},
    )
    assert rejected_dataset.status_code == 422, rejected_dataset.text
    assert client.get(f"/api/v1/projects/{project_id}/review-queues").json() == []

    # Human-supplied local labels remain available for standalone queues.
    allowed = client.post(
        f"/api/v1/projects/{project_id}/review-queues",
        json={"created_by": "marine researcher"},
    )
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["created_by"] == "marine researcher"


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_weights",
        "missing_version",
        "missing_checksums",
        "null_scoring_digest",
        "null_item_digest",
    ],
)
def test_regenerated_workflow_queue_keeps_lineage_without_stealing_retry_owner(
    client: TestClient, corruption: str
) -> None:
    project = create_project(client, "Workflow QC regeneration provenance")
    project_id = project["id"]
    imported = import_one(
        client,
        project_id,
        filename="swiftia-workflow-regeneration.png",
        relative_path="qc/swiftia-workflow-regeneration.png",
    )
    assert len(imported["successful"]) == 1
    graph = {
        "graph_id": "qc-regeneration-owner-16",
        "name": "Workflow QC regeneration ownership",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "qc", "node_type": "qc_review_queue"},
        ],
        "edges": [
            {
                "edge_id": "project-qc",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "qc",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["id"]
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    references = [
        item for item in detail.json()["artifacts"] if item["data_type"] == "review_queue_reference"
    ]
    assert len(references) == 1
    original_id = references[0]["payload_json"]["queue_id"]
    original = client.get(f"/api/v1/review-queues/{original_id}")
    assert original.status_code == 200, original.text
    owner = original.json()["created_by"]
    assert owner.startswith("workflow:")
    items = client.get(f"/api/v1/review-queues/{original_id}/items")
    assert items.status_code == 200, items.text
    item_id = items.json()["items"][0]["id"]
    events_url = f"/api/v1/review-queues/{original_id}/items/{item_id}/events"
    comment = client.post(
        events_url,
        json={
            "client_request_id": str(uuid4()),
            "event_type": "comment",
            "actor": "marine researcher",
            "comment": "Keep original polyp review evidence",
        },
    )
    assert comment.status_code == 201, comment.text

    # A manual regeneration must not bless corrupted workflow provenance.
    with app.state.session_factory() as session:
        saved_queue = session.get(ReviewQueue, original_id)
        assert saved_queue is not None
        original_config = dict(saved_queue.configuration_json)
        original_checksums = dict(saved_queue.input_checksums_json)
        altered_checksums = dict(original_checksums)
        if corruption == "missing_weights":
            saved_queue.configuration_json = {
                key: value for key, value in original_config.items() if key != "weights"
            }
        elif corruption == "missing_version":
            saved_queue.input_checksums_json = {
                key: value
                for key, value in original_checksums.items()
                if key != "integrity_schema_version"
            }
        elif corruption == "missing_checksums":
            saved_queue.input_checksums_json = {}
        else:
            # Removing the marker and nulling an optional digest must not
            # masquerade as a genuinely older unsigned queue.
            altered_checksums.pop("integrity_schema_version")
            altered_checksums.pop("scoring_provenance_sha256")
            altered_checksums.pop("item_evidence_sha256")
            digest_field = (
                "scoring_provenance_sha256"
                if corruption == "null_scoring_digest"
                else "item_evidence_sha256"
            )
            altered_checksums[digest_field] = None
            saved_queue.input_checksums_json = altered_checksums
        session.commit()

    refused = client.post(f"/api/v1/review-queues/{original_id}/regenerate")
    assert refused.status_code == 422, refused.text
    queues = client.get(f"/api/v1/projects/{project_id}/review-queues")
    assert queues.status_code == 200, queues.text
    assert [queue["id"] for queue in queues.json()] == [original_id]
    with app.state.session_factory() as session:
        saved_queue = session.get(ReviewQueue, original_id)
        assert saved_queue is not None
        saved_queue.configuration_json = original_config
        saved_queue.input_checksums_json = original_checksums
        session.commit()

    regenerated = client.post(f"/api/v1/review-queues/{original_id}/regenerate")
    assert regenerated.status_code == 200, regenerated.text
    new_queue = regenerated.json()
    assert new_queue["id"] != original_id
    assert new_queue["created_by"] == "local_user"
    assert new_queue["regenerated_from_queue_id"] == original_id
    assert new_queue["input_checksums_json"]["integrity_schema_version"] == ("qc-review-queue-v3")
    assert (
        new_queue["source_quality_control_run_id"]
        == (original.json()["source_quality_control_run_id"])
    )

    # Regeneration must not create ambiguous ownership for the saved run.
    with app.state.session_factory() as session:
        owned = session.scalars(
            select(ReviewQueue).where(
                ReviewQueue.project_id == project_id,
                ReviewQueue.created_by == owner,
            )
        ).all()
        assert [queue.id for queue in owned] == [original_id]
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run_id,
                WorkflowArtifact.data_type == "project_reference",
            )
        )
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_type == "qc_review_queue",
            )
        )
        assert source is not None and node is not None
        if corruption in {"null_scoring_digest", "null_item_digest"}:
            saved_queue = session.get(ReviewQueue, original_id)
            assert saved_queue is not None
            saved_queue.input_checksums_json = altered_checksums
            session.commit()
            with pytest.raises(ValidationError, match="snapshot failed integrity validation"):
                create_review_queue_workflow_artifact(
                    session=session,
                    settings=app.state.settings,
                    project_id=project_id,
                    parameters={
                        **dict(node.parameters_json or {}),
                        "__workflow_run_id": run_id,
                        "__workflow_node_run_id": node.id,
                    },
                    inputs={"project": [source]},
                )
            session.rollback()
            saved_queue.input_checksums_json = original_checksums
            session.commit()
        replay = create_review_queue_workflow_artifact(
            session=session,
            settings=app.state.settings,
            project_id=project_id,
            parameters={
                **dict(node.parameters_json or {}),
                "__workflow_run_id": run_id,
                "__workflow_node_run_id": node.id,
            },
            inputs={"project": [source]},
        )
        assert replay[0]["data_type"] == "review_queue_reference"
        assert replay[0]["payload"]["queue_id"] == original_id
        assert replay[0]["payload"]["review_status"] == "requires_researcher_review"
        assert replay[0]["payload"]["priority_score_unit"] == "dimensionless"

        # A completed node cannot silently create a replacement queue when
        # its original review evidence loses the internal ownership marker.
        saved_queue = session.get(ReviewQueue, original_id)
        assert saved_queue is not None
        saved_queue.created_by = "local_user"
        session.commit()
        with pytest.raises(ValidationError, match="saved output"):
            create_review_queue_workflow_artifact(
                session=session,
                settings=app.state.settings,
                project_id=project_id,
                parameters={
                    **dict(node.parameters_json or {}),
                    "__workflow_run_id": run_id,
                    "__workflow_node_run_id": node.id,
                },
                inputs={"project": [source]},
            )
        saved_queue.created_by = owner
        session.commit()

        # Re-signing an altered output digest is insufficient to redirect a
        # completed node to another queue or invent new scientific evidence.
        assert len(node.output_artifact_ids_json) == 1
        output = session.get(WorkflowArtifact, node.output_artifact_ids_json[0])
        assert output is not None
        original_payload = dict(output.payload_json)
        for field, forged_value in (
            ("queue_id", "forged-queue"),
            ("priority_score_unit", "polyps"),
            ("review_status", "verified"),
        ):
            output.payload_json = {**original_payload, field: forged_value}
            output.payload_sha256 = canonical_json_sha256(output.payload_json)
            session.commit()
            with pytest.raises(ValidationError, match="saved output no longer matches"):
                create_review_queue_workflow_artifact(
                    session=session,
                    settings=app.state.settings,
                    project_id=project_id,
                    parameters={
                        **dict(node.parameters_json or {}),
                        "__workflow_run_id": run_id,
                        "__workflow_node_run_id": node.id,
                    },
                    inputs={"project": [source]},
                )
        output.payload_json = original_payload
        output.payload_sha256 = canonical_json_sha256(original_payload)
        session.commit()
        restored = create_review_queue_workflow_artifact(
            session=session,
            settings=app.state.settings,
            project_id=project_id,
            parameters={
                **dict(node.parameters_json or {}),
                "__workflow_run_id": run_id,
                "__workflow_node_run_id": node.id,
            },
            inputs={"project": [source]},
        )
        assert restored[0]["payload"]["queue_id"] == original_id
        owned = session.scalars(
            select(ReviewQueue).where(
                ReviewQueue.project_id == project_id,
                ReviewQueue.created_by == owner,
            )
        ).all()
        assert [queue.id for queue in owned] == [original_id]

    history = client.get(events_url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["id"] == comment.json()["id"]
    assert history.json()["requires_researcher_review"] is True
    annotations = client.get(f"/api/v1/images/{imported['successful'][0]['image_id']}/annotations")
    assert annotations.status_code == 200, annotations.text
    assert annotations.json()["annotations"] == []


@pytest.mark.parametrize(
    "corruption",
    [
        "array",
        "missing_weights",
        "string_weight",
        "missing_threshold",
        "source_mismatch",
        "missing_version",
        "missing_version_and_weights",
        "unversioned_bad_item_digest",
        "unversioned_null_scoring_digest",
        "unversioned_null_item_digest",
        "unversioned_null_both_digests",
    ],
)
def test_manual_qc_regeneration_refuses_invalid_saved_science(
    client: TestClient, corruption: str
) -> None:
    project_id = create_project(client, "Manual QC regeneration integrity")["id"]
    assert len(import_one(client, project_id, filename="regen-coral.png")["successful"]) == 1
    original = client.post(
        f"/api/v1/projects/{project_id}/review-queues",
        json={"signal_weights": {"recent_import": 2.0}},
    )
    assert original.status_code == 201, original.text
    queue_id = original.json()["id"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        queue = session.get(ReviewQueue, queue_id)
        assert queue is not None
        configuration = dict(queue.configuration_json)
        checksums = dict(queue.input_checksums_json)
        altered_checksums = dict(checksums)
        altered: Any = dict(configuration)
        if corruption == "array":
            altered = []
        elif corruption == "missing_weights":
            altered.pop("weights")
        elif corruption == "string_weight":
            altered["weights"] = {**configuration["weights"], "recent_import": "2.0"}
        elif corruption == "missing_threshold":
            altered.pop("review_below_confidence")
        elif corruption == "source_mismatch":
            altered["source_quality_control_run_id"] = "different-source"
        else:
            altered_checksums.pop("integrity_schema_version")
            if corruption == "missing_version_and_weights":
                altered.pop("weights")
            elif corruption == "unversioned_bad_item_digest":
                altered_checksums.pop("scoring_provenance_sha256")
                altered_checksums["item_evidence_sha256"] = "0" * 64
            elif corruption.startswith("unversioned_null_"):
                altered_checksums.pop("scoring_provenance_sha256")
                altered_checksums.pop("item_evidence_sha256")
                if corruption != "unversioned_null_item_digest":
                    altered_checksums["scoring_provenance_sha256"] = None
                if corruption != "unversioned_null_scoring_digest":
                    altered_checksums["item_evidence_sha256"] = None
        queue.configuration_json = altered
        queue.input_checksums_json = altered_checksums
        session.commit()

    refused = client.post(f"/api/v1/review-queues/{queue_id}/regenerate")
    assert refused.status_code == 422, refused.text
    with app.state.session_factory() as session:
        queues = session.scalars(
            select(ReviewQueue).where(ReviewQueue.project_id == project_id)
        ).all()
        assert [queue.id for queue in queues] == [queue_id]
        assert queues[0].configuration_json == altered
        assert queues[0].input_checksums_json == altered_checksums
        assert [item.review_state for item in queues[0].items] == ["pending"]
        queues[0].configuration_json = configuration
        queues[0].input_checksums_json = checksums
        session.commit()

    regenerated = client.post(f"/api/v1/review-queues/{queue_id}/regenerate")
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["regenerated_from_queue_id"] == queue_id
    assert regenerated.json()["configuration_json"]["weights"] == configuration["weights"]
    for current_id in (queue_id, regenerated.json()["id"]):
        items = client.get(f"/api/v1/review-queues/{current_id}/items")
        assert items.status_code == 200, items.text
        assert [item["review_state"] for item in items.json()["items"]] == ["pending"]


@pytest.mark.parametrize("signed", [False, True])
def test_manual_qc_regeneration_retains_unversioned_compatibility(
    client: TestClient, signed: bool
) -> None:
    project_id = create_project(client, "Historical QC regeneration")["id"]
    assert len(import_one(client, project_id)["successful"]) == 1
    original = client.post(
        f"/api/v1/projects/{project_id}/review-queues",
        json={"signal_weights": {"recent_import": 2.0}},
    )
    assert original.status_code == 201, original.text
    queue_id = original.json()["id"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        queue = session.get(ReviewQueue, queue_id)
        assert queue is not None
        checksums = dict(queue.input_checksums_json)
        checksums.pop("integrity_schema_version")
        if signed:
            checksums["scoring_provenance_sha256"] = canonical_json_sha256(
                {
                    "formula_id": queue.formula_id,
                    "formula_version": queue.formula_version,
                    "configuration": queue.configuration_json,
                }
            )
        else:
            checksums.pop("scoring_provenance_sha256")
            checksums.pop("item_evidence_sha256")
        queue.input_checksums_json = checksums
        session.commit()

    regenerated = client.post(f"/api/v1/review-queues/{queue_id}/regenerate")
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["regenerated_from_queue_id"] == queue_id
    assert regenerated.json()["configuration_json"]["weights"]["recent_import"] == 2.0
    for current_id in (queue_id, regenerated.json()["id"]):
        items = client.get(f"/api/v1/review-queues/{current_id}/items")
        assert items.status_code == 200, items.text
        assert [item["review_state"] for item in items.json()["items"]] == ["pending"]

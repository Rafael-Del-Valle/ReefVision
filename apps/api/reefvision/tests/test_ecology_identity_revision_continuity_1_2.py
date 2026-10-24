"""Fail-closed ecological identity history acceptance for APIs and saved workflows."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project


@pytest.mark.parametrize("imported_revision", [0, 3])
def test_imported_revision_gap_blocks_api_writes_and_saved_workflow(
    client: TestClient, imported_revision: int
) -> None:
    project_id = str(create_project(client, f"Revision gap {imported_revision}")["id"])
    base = f"/api/v1/projects/{project_id}/ecology"
    initial = client.post(
        f"{base}/organisms",
        json={
            "organism_key": "colony-20",
            "kind": "colony",
            "reason": "Initial registered biological identity",
        },
    )
    assert initial.status_code == 201, initial.text

    # An imported or manually edited SQLite record bypasses API revision checks.
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            EcologyIdentityRevision(
                project_id=project_id,
                organism_key="colony-20",
                revision=imported_revision,
                kind="colony",
                reason="Malformed imported scientific revision history",
            )
        )
        session.commit()

    registry = client.get(f"{base}/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "revision history is not contiguous" in registry.json()["detail"]

    create = client.post(
        f"{base}/organisms",
        json={
            "organism_key": "fragment-20a",
            "kind": "fragment",
            "parent_colony_key": "colony-20",
            "reason": "Must not write into a corrupted identity registry",
        },
    )
    assert create.status_code == 400, create.text
    revise = client.post(
        f"{base}/organisms/colony-20/revisions",
        json={
            "expected_revision": 1,
            "kind": "colony",
            "reason": "Must not append to an incomplete revision chain",
        },
    )
    assert revise.status_code == 400, revise.text

    graph = {
        "graph_id": f"ecology-revision-gap-{imported_revision}",
        "name": "Fail closed on missing biological identity history",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "identity", "node_type": "ecology_identity_registry_source"},
        ],
        "edges": [
            {
                "edge_id": "project-identity",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "identity",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert "revision history is not contiguous" in detail.json()["run"]["error_message"]
    assert not any(
        row["data_type"] == "ecology_identity_registry" for row in detail.json()["artifacts"]
    )


def test_valid_revision_chain_preserves_project_isolation(client: TestClient) -> None:
    first = str(create_project(client, "Valid ecological revisions")["id"])
    second = str(create_project(client, "Unrelated ecological revisions")["id"])
    base = f"/api/v1/projects/{first}/ecology"
    created = client.post(
        f"{base}/organisms",
        json={
            "organism_key": "colony-68",
            "kind": "colony",
            "reason": "Initial parent colony registration",
        },
    )
    assert created.status_code == 201, created.text
    revised = client.post(
        f"{base}/organisms/colony-68/revisions",
        json={
            "expected_revision": 1,
            "kind": "colony",
            "reason": "Corrected scientific registry description",
        },
    )
    assert revised.status_code == 201, revised.text
    registry = client.get(f"{base}/identity-registry")
    assert registry.status_code == 200, registry.text
    assert registry.json()["identities"][0]["revision"] == 2
    assert registry.json()["evidence_level"] == "registered_unverified"
    other = client.get(f"/api/v1/projects/{second}/ecology/identity-registry")
    assert other.status_code == 200, other.text
    assert other.json()["identities"] == []


def test_historical_identity_revisions_are_fingerprinted_in_saved_workflows(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Historical identity provenance")["id"])
    base = f"/api/v1/projects/{project_id}/ecology"
    created = client.post(
        f"{base}/organisms",
        json={
            "organism_key": "colony-16",
            "kind": "colony",
            "reason": "Original registered identity",
        },
    )
    assert created.status_code == 201, created.text
    revised = client.post(
        f"{base}/organisms/colony-16/revisions",
        json={
            "expected_revision": 1,
            "kind": "colony",
            "reason": "Second revision with unchanged biological identity",
        },
    )
    assert revised.status_code == 201, revised.text
    before = client.get(f"{base}/identity-registry")
    assert before.status_code == 200, before.text
    assert before.json()["history_revision_count"] == 2
    assert len(before.json()["history_sha256"]) == 64

    # Simulate an imported retroactive edit to the original audit record.
    # The latest-only snapshot cannot detect this; full-history provenance must.
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        original = session.scalar(
            select(EcologyIdentityRevision).where(
                EcologyIdentityRevision.project_id == project_id,
                EcologyIdentityRevision.organism_key == "colony-16",
                EcologyIdentityRevision.revision == 1,
            )
        )
        assert original is not None
        original.reason = "Simulated retroactive modification of original record"
        session.commit()

    after = client.get(f"{base}/identity-registry")
    assert after.status_code == 200, after.text
    assert after.json()["identities"] == before.json()["identities"]
    assert after.json()["snapshot_sha256"] == before.json()["snapshot_sha256"]
    assert after.json()["history_sha256"] != before.json()["history_sha256"]
    assert after.json()["evidence_level"] == "registered_unverified"

    graph = {
        "graph_id": "ecology-identity-history-fingerprint-1-2",
        "name": "Persist full identity revision provenance",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "identity", "node_type": "ecology_identity_registry_source"},
        ],
        "edges": [
            {
                "edge_id": "project-identity",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "identity",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = [
        row for row in detail.json()["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == after.json()
    assert artifacts[0]["payload_json"]["review_gate"] == "scientist_review_required"

"""Project-scoped biological identity revisions and saved workflow provenance."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project


def _register(
    client: TestClient,
    project_id: str,
    key: str,
    kind: str = "colony",
    **extra: Any,
) -> Any:
    return client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms",
        json={
            "organism_key": key,
            "kind": kind,
            "reason": "Initial biological identity registration",
            **extra,
        },
    )


def test_identity_registry_is_project_owned_and_deterministic(
    client: TestClient,
) -> None:
    first = str(create_project(client, "Ecology identity A")["id"])
    second = str(create_project(client, "Ecology identity B")["id"])
    colony = _register(client, first, "colony-16")
    assert colony.status_code == 201, colony.text
    fragment = _register(
        client,
        first,
        "fragment-16a",
        "fragment",
        parent_colony_key="colony-16",
        experimental_unit_type="tank",
        experimental_unit_id="tank-1",
    )
    assert fragment.status_code == 201, fragment.text
    registry_url = f"/api/v1/projects/{first}/ecology/identity-registry"
    one = client.get(registry_url)
    two = client.get(registry_url)
    assert one.status_code == 200, one.text
    assert one.json() == two.json()
    assert [row["organism_key"] for row in one.json()["identities"]] == [
        "colony-16",
        "fragment-16a",
    ]
    assert one.json()["evidence_level"] == "registered_unverified"
    assert one.json()["review_gate"] == "scientist_review_required"
    assert len(one.json()["snapshot_sha256"]) == 64
    other = client.get(f"/api/v1/projects/{second}/ecology/identity-registry")
    assert other.status_code == 200, other.text
    assert other.json()["identities"] == []
    assert other.json()["snapshot_sha256"] != one.json()["snapshot_sha256"]


def test_identity_rejects_cross_project_parents_and_technical_units(
    client: TestClient,
) -> None:
    first = str(create_project(client, "Parent project A")["id"])
    second = str(create_project(client, "Parent project B")["id"])
    assert _register(client, first, "colony-1").status_code == 201
    cross_project = _register(
        client, second, "fragment-1", "fragment", parent_colony_key="colony-1"
    )
    assert cross_project.status_code == 400, cross_project.text
    assert _register(client, first, "colony-1").status_code == 409
    invalid = _register(
        client,
        first,
        "fragment-2",
        "fragment",
        experimental_unit_type="video_frame",
        experimental_unit_id="frame-9",
    )
    assert invalid.status_code == 422, invalid.text
    incomplete = _register(client, first, "fragment-3", "fragment", experimental_unit_id="tank-1")
    assert incomplete.status_code == 422, incomplete.text
    self_parent = _register(client, first, "fragment-4", "fragment", parent_colony_key="fragment-4")
    assert self_parent.status_code == 400, self_parent.text


def test_identity_revision_is_append_only_and_stale_writes_fail(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Identity history")["id"])
    created = _register(
        client,
        project_id,
        "coral-1",
        "individual",
        experimental_unit_type="tank",
        experimental_unit_id="tank-A",
    )
    assert created.status_code == 201, created.text
    before = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry").json()
    payload = {
        "expected_revision": 1,
        "kind": "individual",
        "experimental_unit_type": "tank",
        "experimental_unit_id": "tank-B",
        "reason": "Scientist corrected the recorded tank assignment",
    }
    url = f"/api/v1/projects/{project_id}/ecology/organisms/coral-1/revisions"
    changed = client.post(url, json=payload)
    assert changed.status_code == 201, changed.text
    assert changed.json()["revision"] == 2
    assert client.post(url, json=payload).status_code == 409
    after = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry").json()
    assert before["snapshot_sha256"] != after["snapshot_sha256"]
    assert after["identities"][0]["experimental_unit_id"] == "tank-B"
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        history = list(
            session.scalars(
                select(EcologyIdentityRevision)
                .where(EcologyIdentityRevision.project_id == project_id)
                .order_by(EcologyIdentityRevision.revision)
            )
        )
    assert [(row.revision, row.experimental_unit_id) for row in history] == [
        (1, "tank-A"),
        (2, "tank-B"),
    ]


def test_saved_workflow_snapshots_registry_without_verification_promotion(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Identity workflow")["id"])
    assert _register(client, project_id, "colony-68").status_code == 201
    registry_response = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry_response.status_code == 200, registry_response.text
    nodes = {row["node_type"]: row for row in registry_response.json()}
    definition = nodes["ecology_identity_registry_source"]
    assert definition["executable"] is True
    assert definition["input_ports"][0]["accepted_types"] == ["project_reference"]
    assert definition["output_ports"][0]["accepted_types"] == ["ecology_identity_registry"]
    graph: dict[str, Any] = {
        "graph_id": "ecology-identity-registry-1-2",
        "name": "Versioned organism identities",
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
    app = cast(FastAPI, client.app)
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
    standalone = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert standalone.status_code == 200, standalone.text
    assert artifacts[0]["payload_json"] == standalone.json()
    graph["nodes"].append({"node_id": "dataset", "node_type": "dataset_version_create"})
    graph["edges"].append(
        {
            "edge_id": "identity-to-reviewed",
            "source_node_id": "identity",
            "source_port_id": "registry",
            "target_node_id": "dataset",
            "target_port_id": "reviewed",
        }
    )
    invalid = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/validate", json=graph)
    assert invalid.status_code == 200, invalid.text
    assert invalid.json()["valid"] is False
    assert any(issue["code"] == "incompatible_port_types" for issue in invalid.json()["issues"])


def test_saved_identity_source_rejects_scientist_supplied_parameters(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Reject forged identity source parameters")["id"])
    assert _register(client, project_id, "parent-verified-claim").status_code == 201
    graph: dict[str, Any] = {
        "graph_id": "ecology-identity-parameters-rejected-1-2",
        "name": "Reject caller verification claims",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "identity",
                "node_type": "ecology_identity_registry_source",
                "parameters": {"verified": True},
            },
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
    app = cast(FastAPI, client.app)
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
    assert "accepts no parameters" in detail.json()["run"]["error_message"]
    assert not any(
        row["data_type"] == "ecology_identity_registry" for row in detail.json()["artifacts"]
    )


def test_imported_technical_unit_cannot_enter_registry_or_saved_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Imported technical unit integrity")["id"])
    created = _register(
        client,
        project_id,
        "fragment-technical",
        "fragment",
        experimental_unit_type="tank",
        experimental_unit_id="tank-1",
    )
    assert created.status_code == 201, created.text
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            EcologyIdentityRevision(
                project_id=project_id,
                organism_key="fragment-technical",
                revision=2,
                kind="fragment",
                experimental_unit_type="video_frame",
                experimental_unit_id="frame-1",
                reason="Simulated imported technical pseudoreplicate",
            )
        )
        session.commit()

    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    response = client.get(registry_url)
    assert response.status_code == 400, response.text
    assert "invalid experimental unit type" in response.json()["detail"]

    graph: dict[str, Any] = {
        "graph_id": "ecology-imported-technical-unit-1-2",
        "name": "Reject imported technical pseudoreplicates",
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
    assert "invalid experimental unit type" in detail.json()["run"]["error_message"]
    assert not any(
        row["data_type"] == "ecology_identity_registry" for row in detail.json()["artifacts"]
    )


def test_parent_colony_reclassification_requires_reassigning_fragments(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Parent colony lineage integrity")["id"])
    assert _register(client, project_id, "parent-20").status_code == 201
    assert (
        _register(
            client,
            project_id,
            "fragment-20a",
            "fragment",
            parent_colony_key="parent-20",
        ).status_code
        == 201
    )
    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    before = client.get(registry_url).json()
    parent_url = f"/api/v1/projects/{project_id}/ecology/organisms/parent-20/revisions"
    change = {
        "expected_revision": 1,
        "kind": "individual",
        "reason": "Correct the parent colony taxonomic designation",
    }
    blocked = client.post(parent_url, json=change)
    assert blocked.status_code == 400, blocked.text
    assert "reclassify a parent colony" in blocked.json()["detail"]
    assert client.get(registry_url).json() == before

    # A reviewed correction may first unlink the child in a new revision.
    fragment_url = f"/api/v1/projects/{project_id}/ecology/organisms/fragment-20a/revisions"
    unlinked = client.post(
        fragment_url,
        json={
            "expected_revision": 1,
            "kind": "fragment",
            "reason": "Scientist corrected the fragment's parent assignment",
        },
    )
    assert unlinked.status_code == 201, unlinked.text
    allowed = client.post(parent_url, json=change)
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["revision"] == 2
    latest = client.get(registry_url).json()
    assert latest["evidence_level"] == "registered_unverified"
    assert latest["snapshot_sha256"] != before["snapshot_sha256"]


def test_corrupt_latest_lineage_fails_closed_in_api_and_saved_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Imported lineage integrity")["id"])
    assert _register(client, project_id, "parent-39").status_code == 201
    assert (
        _register(
            client,
            project_id,
            "fragment-39a",
            "fragment",
            parent_colony_key="parent-39",
        ).status_code
        == 201
    )

    # Simulate an invalid external import bypassing service-level revisions.
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            EcologyIdentityRevision(
                project_id=project_id,
                organism_key="parent-39",
                revision=2,
                kind="individual",
                reason="Simulated malformed external identity import",
            )
        )
        session.commit()

    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    standalone = client.get(registry_url)
    assert standalone.status_code == 400, standalone.text
    assert "invalid parent-colony link" in standalone.json()["detail"]

    graph: dict[str, Any] = {
        "graph_id": "ecology-invalid-lineage-1-2",
        "name": "Reject corrupt ecological lineage",
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
    assert "invalid parent-colony link" in detail.json()["run"]["error_message"]
    assert not any(
        row["data_type"] == "ecology_identity_registry" for row in detail.json()["artifacts"]
    )

def test_superseded_ecological_identity_history_in_saved_workflow(client: TestClient) -> None:
    """Reviewers can inspect every earlier tank assignment, not only its digest."""
    project_id = str(create_project(client, "Superseded ecological identity audit")["id"])
    assert _register(client, project_id, "parent-16").status_code == 201
    created = _register(
        client,
        project_id,
        "fragment-16a",
        "fragment",
        parent_colony_key="parent-16",
        experimental_unit_type="tank",
        experimental_unit_id="tank-A",
    )
    assert created.status_code == 201, created.text
    url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    before = client.get(url)
    assert before.status_code == 200, before.text
    assert before.json()["history_revision_count"] == len(before.json()["identity_history"]) == 2

    corrected = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/fragment-16a/revisions",
        json={
            "expected_revision": 1,
            "kind": "fragment",
            "parent_colony_key": "parent-16",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-B",
            "reason": "Correct tank assignment after inspecting laboratory records",
        },
    )
    assert corrected.status_code == 201, corrected.text
    response = client.get(url)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["history_revision_count"] == len(body["identity_history"]) == 3
    prior_and_current = [
        row for row in body["identity_history"] if row["organism_key"] == "fragment-16a"
    ]
    assert [row["revision"] for row in prior_and_current] == [1, 2]
    assert [row["experimental_unit_id"] for row in prior_and_current] == ["tank-A", "tank-B"]
    assert all(row["reason"] and row["created_at"] for row in prior_and_current)
    fragment = next(row for row in body["identities"] if row["organism_key"] == "fragment-16a")
    assert fragment["experimental_unit_id"] == "tank-B"
    assert body["history_sha256"] != before.json()["history_sha256"]
    assert body["evidence_level"] == "registered_unverified"
    assert body["review_gate"] == "scientist_review_required"

    graph: dict[str, Any] = {
        "graph_id": "ecology-superseded-identity-audit",
        "name": "Audit full organism revision history",
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
    nodes = client.get("/api/v1/workflow-graphs/node-registry")
    assert nodes.status_code == 200, nodes.text
    source = next(
        row for row in nodes.json() if row["node_type"] == "ecology_identity_registry_source"
    )
    assert source["output_ports"][0]["accepted_types"] == ["ecology_identity_registry"]
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
    app = cast(FastAPI, client.app)
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
    assert artifacts[0]["payload_json"] == body


def test_legacy_ecological_registry_artifact_defaults_to_empty_history() -> None:
    from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse

    old = EcologyIdentityRegistryResponse.model_validate(
        {"project_id": "legacy", "identities": [], "snapshot_sha256": "legacy-hash"}
    )
    assert old.identity_history == []
    assert old.history_revision_count == 0
    assert old.evidence_level == "registered_unverified"
    assert old.review_gate == "scientist_review_required"

"""Scientific unit-identity integrity across API revisions and saved workflows."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project


def _register(
    client: TestClient,
    project_id: str,
    key: str,
    kind: str = "colony",
    **fields: Any,
) -> Any:
    return client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms",
        json={
            "organism_key": key,
            "kind": kind,
            "reason": "Scientist registered an ecological identity",
            **fields,
        },
    )


def test_registered_colony_and_organism_units_do_not_inflate_replicates(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Ecological independent-unit guard")["id"])
    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    for parent in ("parent-A", "parent-B"):
        response = _register(client, project_id, parent)
        assert response.status_code == 201, response.text

    first = _register(
        client,
        project_id,
        "fragment-A1",
        "fragment",
        parent_colony_key="parent-A",
        experimental_unit_type="colony",
        experimental_unit_id="colony-unit-1",
    )
    assert first.status_code == 201, first.text
    same_parent = _register(
        client,
        project_id,
        "fragment-A2",
        "fragment",
        parent_colony_key="parent-A",
        experimental_unit_type="colony",
        experimental_unit_id="colony-unit-1",
    )
    assert same_parent.status_code == 201, same_parent.text
    before = client.get(registry_url).json()

    mixed_parent = _register(
        client,
        project_id,
        "fragment-B1",
        "fragment",
        parent_colony_key="parent-B",
        experimental_unit_type="colony",
        experimental_unit_id="colony-unit-1",
    )
    assert mixed_parent.status_code == 400, mixed_parent.text
    assert "mix parent colonies" in mixed_parent.json()["detail"]
    missing_parent = _register(
        client,
        project_id,
        "fragment-orphan",
        "fragment",
        experimental_unit_type="colony",
        experimental_unit_id="colony-unit-2",
    )
    assert missing_parent.status_code == 400, missing_parent.text
    assert client.get(registry_url).json() == before

    # Tank assignment can legitimately contain fragments of different parents.
    tank = _register(
        client,
        project_id,
        "fragment-B1",
        "fragment",
        parent_colony_key="parent-B",
        experimental_unit_type="tank",
        experimental_unit_id="tank-1",
    )
    assert tank.status_code == 201, tank.text
    other_tank_fragment = _register(
        client,
        project_id,
        "fragment-A3",
        "fragment",
        parent_colony_key="parent-A",
        experimental_unit_type="tank",
        experimental_unit_id="tank-1",
    )
    assert other_tank_fragment.status_code == 201, other_tank_fragment.text

    first_individual = _register(
        client,
        project_id,
        "individual-1",
        "individual",
        experimental_unit_type="organism",
        experimental_unit_id="individual-unit-1",
    )
    assert first_individual.status_code == 201, first_individual.text
    duplicate_individual = _register(
        client,
        project_id,
        "individual-2",
        "individual",
        experimental_unit_type="Organism",
        experimental_unit_id="individual-unit-1",
    )
    assert duplicate_individual.status_code == 400, duplicate_individual.text
    assert "multiple organisms" in duplicate_individual.json()["detail"]

    # Revisions must enforce the same guard without appending invalid history.
    revise_url = f"/api/v1/projects/{project_id}/ecology/organisms/fragment-B1/revisions"
    revision = client.post(
        revise_url,
        json={
            "expected_revision": 1,
            "kind": "fragment",
            "parent_colony_key": "parent-B",
            "experimental_unit_type": "colony",
            "experimental_unit_id": "colony-unit-1",
            "reason": "Correct a previously assigned independent unit",
        },
    )
    assert revision.status_code == 400, revision.text
    assert "mix parent colonies" in revision.json()["detail"]
    after = client.get(registry_url).json()
    assert after["evidence_level"] == "registered_unverified"
    assert (
        next(row for row in after["identities"] if row["organism_key"] == "fragment-B1")["revision"]
        == 1
    )


def test_imported_unit_collision_blocks_registry_and_saved_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Corrupt colony unit import")["id"])
    for parent in ("parent-1", "parent-2"):
        assert _register(client, project_id, parent).status_code == 201
    assert (
        _register(
            client,
            project_id,
            "fragment-1",
            "fragment",
            parent_colony_key="parent-1",
            experimental_unit_type="colony",
            experimental_unit_id="colony-unit-1",
        ).status_code
        == 201
    )
    assert (
        _register(
            client,
            project_id,
            "fragment-2",
            "fragment",
            parent_colony_key="parent-2",
            experimental_unit_type="colony",
            experimental_unit_id="colony-unit-2",
        ).status_code
        == 201
    )

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            EcologyIdentityRevision(
                project_id=project_id,
                organism_key="fragment-2",
                revision=2,
                kind="fragment",
                parent_colony_key="parent-2",
                experimental_unit_type="colony",
                experimental_unit_id="colony-unit-1",
                reason="Simulated malformed imported experimental design",
            )
        )
        session.commit()

    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "mix parent colonies" in registry.json()["detail"]

    graph: dict[str, Any] = {
        "graph_id": "ecology-invalid-unit-1-2",
        "name": "Fail closed on mixed parent-colony units",
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
    assert "mix parent colonies" in detail.json()["run"]["error_message"]
    assert not any(
        artifact["data_type"] == "ecology_identity_registry"
        for artifact in detail.json()["artifacts"]
    )


def test_colony_unit_split_rejected_in_api_and_workflow(client: TestClient) -> None:
    project_id = str(create_project(client, "No split colony replicates")["id"])
    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    assert _register(client, project_id, "parent-16").status_code == 201
    for fragment in ("fragment-16a", "fragment-16b"):
        created = _register(
            client,
            project_id,
            fragment,
            "fragment",
            parent_colony_key="parent-16",
            experimental_unit_type="colony",
            experimental_unit_id="colony-unit-1",
        )
        assert created.status_code == 201, created.text
    before = client.get(registry_url).json()
    split = _register(
        client,
        project_id,
        "fragment-16c",
        "fragment",
        parent_colony_key="parent-16",
        experimental_unit_type="colony",
        experimental_unit_id="colony-unit-2",
    )
    assert split.status_code == 400, split.text
    assert "split across colony-level units" in split.json()["detail"]
    revision = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/fragment-16b/revisions",
        json={
            "expected_revision": 1,
            "kind": "fragment",
            "parent_colony_key": "parent-16",
            "experimental_unit_type": "colony",
            "experimental_unit_id": "colony-unit-2",
            "reason": "Proposed independent unit correction",
        },
    )
    assert revision.status_code == 400, revision.text
    assert client.get(registry_url).json() == before

    # An imported revision can bypass the API; registry snapshots must fail.
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            EcologyIdentityRevision(
                project_id=project_id,
                organism_key="fragment-16b",
                revision=2,
                kind="fragment",
                parent_colony_key="parent-16",
                experimental_unit_type="colony",
                experimental_unit_id="colony-unit-2",
                reason="Simulated invalid independent-unit import",
            )
        )
        session.commit()
    invalid = client.get(registry_url)
    assert invalid.status_code == 400, invalid.text
    assert "split across colony-level units" in invalid.json()["detail"]

    graph: dict[str, Any] = {
        "graph_id": "ecology-split-colony-1-2",
        "name": "Reject duplicated colony replicates",
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
    assert "split across colony-level units" in detail.json()["run"]["error_message"]
    assert not any(
        artifact["data_type"] == "ecology_identity_registry"
        for artifact in detail.json()["artifacts"]
    )

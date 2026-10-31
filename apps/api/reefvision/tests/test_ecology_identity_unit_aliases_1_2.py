"""Alias-safe biological sampling units across registration, revisions, and workflows."""

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
            "reason": "Scientist recorded the biological sampling identity",
            **fields,
        },
    )


def test_aliases_cannot_inflate_independent_units(client: TestClient) -> None:
    project_id = str(create_project(client, "Canonical experimental-unit aliases")["id"])
    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    assert _register(client, project_id, "parent-A").status_code == 201
    assert _register(client, project_id, "parent-B").status_code == 201

    assert (
        _register(
            client,
            project_id,
            "fragment-A1",
            "fragment",
            parent_colony_key="parent-A",
            experimental_unit_type="Colony-level",
            experimental_unit_id="colony-1",
        ).status_code
        == 201
    )
    # Plural aliases for the SAME parent and independent unit remain legitimate.
    assert (
        _register(
            client,
            project_id,
            "fragment-A2",
            "fragment",
            parent_colony_key="parent-A",
            experimental_unit_type="colonies",
            experimental_unit_id="colony-1",
        ).status_code
        == 201
    )
    before = client.get(registry_url).json()
    mixed = _register(
        client,
        project_id,
        "fragment-B1",
        "fragment",
        parent_colony_key="parent-B",
        experimental_unit_type="colonies",
        experimental_unit_id="colony-1",
    )
    assert mixed.status_code == 400, mixed.text
    assert "mix parent colonies" in mixed.json()["detail"]
    split = _register(
        client,
        project_id,
        "fragment-A3",
        "fragment",
        parent_colony_key="parent-A",
        experimental_unit_type="colony replicate",
        experimental_unit_id="colony-2",
    )
    assert split.status_code == 400, split.text
    assert "split across colony-level units" in split.json()["detail"]
    ambiguous = _register(
        client,
        project_id,
        "fragment-ambiguous",
        "fragment",
        parent_colony_key="parent-A",
        experimental_unit_type="colony/tank",
        experimental_unit_id="unit-3",
    )
    assert ambiguous.status_code == 400, ambiguous.text
    assert "mixes biological sampling levels" in ambiguous.json()["detail"]
    assert client.get(registry_url).json() == before

    assert (
        _register(
            client,
            project_id,
            "organism-1",
            "individual",
            experimental_unit_type="Organism",
            experimental_unit_id="organism-1",
        ).status_code
        == 201
    )
    duplicate = _register(
        client,
        project_id,
        "organism-2",
        "individual",
        experimental_unit_type="individuals",
        experimental_unit_id="organism-1",
    )
    assert duplicate.status_code == 400, duplicate.text
    assert "multiple organisms" in duplicate.json()["detail"]

    # Tanks can contain multiple parents; they are not silently colony-level.
    assert (
        _register(
            client,
            project_id,
            "fragment-B1",
            "fragment",
            parent_colony_key="parent-B",
            experimental_unit_type="tank",
            experimental_unit_id="tank-1",
        ).status_code
        == 201
    )
    assert (
        _register(
            client,
            project_id,
            "fragment-A3",
            "fragment",
            parent_colony_key="parent-A",
            experimental_unit_type="aquaria",
            experimental_unit_id="tank-1",
        ).status_code
        == 201
    )


def test_alias_collision_revision_and_import_fail_closed_in_saved_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Imported alias integrity")["id"])
    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    for parent in ("parent-A", "parent-B"):
        assert _register(client, project_id, parent).status_code == 201
    for suffix, parent, unit in (
        ("A", "parent-A", "colony-A"),
        ("B", "parent-B", "colony-B"),
    ):
        assert (
            _register(
                client,
                project_id,
                f"fragment-{suffix}",
                "fragment",
                parent_colony_key=parent,
                experimental_unit_type="colony",
                experimental_unit_id=unit,
            ).status_code
            == 201
        )
    before = client.get(registry_url).json()
    revision = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/fragment-B/revisions",
        json={
            "expected_revision": 1,
            "kind": "fragment",
            "parent_colony_key": "parent-B",
            "experimental_unit_type": "Colony-level",
            "experimental_unit_id": "colony-A",
            "reason": "Proposed unit correction",
        },
    )
    assert revision.status_code == 400, revision.text
    assert client.get(registry_url).json() == before

    # A malformed external import can bypass API validation.
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            EcologyIdentityRevision(
                project_id=project_id,
                organism_key="fragment-B",
                revision=2,
                kind="fragment",
                parent_colony_key="parent-B",
                experimental_unit_type="Colony-level",
                experimental_unit_id="colony-A",
                reason="Simulated unreviewed import",
            )
        )
        session.commit()
    invalid = client.get(registry_url)
    assert invalid.status_code == 400, invalid.text
    assert "mix parent colonies" in invalid.json()["detail"]

    graph: dict[str, Any] = {
        "graph_id": "ecology-alias-guard-1-2",
        "name": "Reject mixed parent colonies despite unit aliases",
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
        row["data_type"] == "ecology_identity_registry" for row in detail.json()["artifacts"]
    )

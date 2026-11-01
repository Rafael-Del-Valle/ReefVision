"""Alias-safe biological sampling units across registration, revisions, and workflows."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.storage.datasets import canonical_json_sha256
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


def test_ambiguous_experimental_unit_ids_cannot_create_or_revise_registry(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Canonical physical unit IDs")["id"])
    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    assert (
        _register(
            client,
            project_id,
            "fragment-A",
            "fragment",
            experimental_unit_type="tank",
            experimental_unit_id="tank-1",
        ).status_code
        == 201
    )
    before = client.get(registry_url).json()
    for invalid in (
        "tank-1 ",
        " tank-1",
        "tank-1\t",
        "tank-1\n",
        "tank-1\u200b",  # zero-width space
        "tank-1\u2060",  # invisible word joiner
        "tank-\u202e1",  # right-to-left override
        "\uff54\uff41\uff4e\uff4b-1",  # NFKC-compatible fullwidth letters
        "tank-①",  # NFKC-compatible circled digit
        "tank-cafe\u0301",  # decomposed canonical accent
    ):
        create = _register(
            client,
            project_id,
            "fragment-B",
            "fragment",
            experimental_unit_type="aquarium",
            experimental_unit_id=invalid,
        )
        assert create.status_code in (400, 422), create.text
        assert "Experimental unit ID" in create.text
        revision = client.post(
            f"/api/v1/projects/{project_id}/ecology/organisms/fragment-A/revisions",
            json={
                "expected_revision": 1,
                "kind": "fragment",
                "experimental_unit_type": "tank",
                "experimental_unit_id": invalid,
                "reason": "Attempt to split a physical unit with ambiguous ID",
            },
        )
        assert revision.status_code in (400, 422), revision.text
        assert "Experimental unit ID" in revision.text
        assert client.get(registry_url).json() == before

    # Non-ASCII identifiers in canonical form remain valid and unchanged.
    accepted = _register(
        client,
        project_id,
        "fragment-B",
        "fragment",
        experimental_unit_type="aquarium",
        experimental_unit_id="tank-café",
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["experimental_unit_id"] == "tank-café"


@pytest.mark.parametrize(
    "invalid",
    ["tank-1 ", "tank-1\u200b", "\uff54\uff41\uff4e\uff4b-1", "tank-①"],
    ids=["padded", "zero-width", "fullwidth", "compatibility-digit"],
)
def test_imported_ambiguous_unit_id_blocks_registry_and_executable_workflow(
    client: TestClient,
    invalid: str,
) -> None:
    project_id = str(create_project(client, "Imported physical-unit ambiguity")["id"])
    assert (
        _register(
            client,
            project_id,
            "fragment-A",
            "fragment",
            experimental_unit_type="tank",
            experimental_unit_id="tank-1",
        ).status_code
        == 201
    )
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            EcologyIdentityRevision(
                project_id=project_id,
                organism_key="fragment-A",
                revision=2,
                kind="fragment",
                parent_colony_key=None,
                experimental_unit_type="aquarium",
                experimental_unit_id=invalid,
                reason="Simulated unreviewed ambiguous unit import",
            )
        )
        session.commit()
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "invalid experimental unit ID" in registry.text

    graph: dict[str, Any] = {
        "graph_id": "ecology-unit-id-integrity-1-2",
        "name": "Reject ambiguous physical unit identifiers",
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
    assert "invalid experimental unit ID" in detail.json()["run"]["error_message"]
    assert not any(
        row["data_type"] == "ecology_identity_registry" for row in detail.json()["artifacts"]
    )


def test_case_alias_cannot_be_introduced_in_superseded_unit_history(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Historical tank aliases")["id"])
    base = f"/api/v1/projects/{project_id}/ecology"
    assert (
        _register(
            client,
            project_id,
            "fragment-A",
            "fragment",
            experimental_unit_type="tank",
            experimental_unit_id="Tank-A",
        ).status_code
        == 201
    )
    before = client.get(f"{base}/identity-registry").json()
    revised = client.post(
        f"{base}/organisms/fragment-A/revisions",
        json={
            "expected_revision": 1,
            "kind": "fragment",
            "experimental_unit_type": "aquarium",
            "experimental_unit_id": "tank-a",
            "reason": "Proposed case-only tank identifier correction",
        },
    )
    assert revised.status_code == 400, revised.text
    assert "experimental unit IDs differ only by case" in revised.text
    assert client.get(f"{base}/identity-registry").json() == before

    # Same exact physical ID across successive revisions is legitimate.
    accepted = client.post(
        f"{base}/organisms/fragment-A/revisions",
        json={
            "expected_revision": 1,
            "kind": "fragment",
            "experimental_unit_type": "aquarium",
            "experimental_unit_id": "Tank-A",
            "reason": "Record the equivalent aquarium sampling-level alias",
        },
    )
    assert accepted.status_code == 201, accepted.text
    registry = client.get(f"{base}/identity-registry")
    assert registry.status_code == 200, registry.text
    assert registry.json()["history_revision_count"] == 2
    assert registry.json()["review_gate"] == "scientist_review_required"


def test_imported_superseded_tank_alias_blocks_api_and_saved_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Imported historical tank aliases")["id"])
    base = f"/api/v1/projects/{project_id}/ecology"
    assert (
        _register(
            client,
            project_id,
            "fragment-A",
            "fragment",
            experimental_unit_type="tank",
            experimental_unit_id="Tank-A",
        ).status_code
        == 201
    )
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            EcologyIdentityRevision(
                project_id=project_id,
                organism_key="fragment-A",
                revision=2,
                kind="fragment",
                experimental_unit_type="aquarium",
                experimental_unit_id="tank-a",
                reason="Simulated imported historical sampling-unit alias",
            )
        )
        session.commit()
    invalid = client.get(f"{base}/identity-registry")
    assert invalid.status_code == 400, invalid.text
    assert "experimental unit IDs differ only by case" in invalid.text
    attempted = _register(client, project_id, "fragment-B")
    assert attempted.status_code == 400, attempted.text

    graph = {
        "graph_id": "ecology-historical-unit-alias-1-2",
        "name": "Reject historical tank aliases in saved workflows",
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
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert "experimental unit IDs differ only by case" in detail.json()["run"]["error_message"]
    assert not any(
        row["data_type"] == "ecology_identity_registry" for row in detail.json()["artifacts"]
    )


def test_resigned_registry_cannot_replay_historical_unit_alias(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Re-signed historical unit aliases")["id"])
    base = f"/api/v1/projects/{project_id}/ecology"
    assert (
        _register(
            client,
            project_id,
            "fragment-A",
            "fragment",
            experimental_unit_type="tank",
            experimental_unit_id="Tank-A",
        ).status_code
        == 201
    )
    revised = client.post(
        f"{base}/organisms/fragment-A/revisions",
        json={
            "expected_revision": 1,
            "kind": "fragment",
            "experimental_unit_type": "aquarium",
            "experimental_unit_id": "Tank-A",
            "reason": "Record a consistent physical sampling-unit identifier",
        },
    )
    assert revised.status_code == 201, revised.text
    original = client.get(f"{base}/identity-registry").json()
    EcologyIdentityRegistryResponse.model_validate(original)

    forged = deepcopy(original)
    forged["identity_history"][0]["experimental_unit_id"] = "tank-a"
    forged["history_sha256"] = canonical_json_sha256(
        {
            "algorithm_version": "ecology-identity-history-0001",
            "project_id": project_id,
            "revisions": [
                {
                    **{
                        field: row[field]
                        for field in (
                            "id",
                            "organism_key",
                            "revision",
                            "kind",
                            "parent_colony_key",
                            "experimental_unit_type",
                            "experimental_unit_id",
                            "reason",
                        )
                    },
                    "created_at": datetime.fromisoformat(
                        row["created_at"].replace("Z", "+00:00")
                    ).isoformat(),
                }
                for row in forged["identity_history"]
            ],
        }
    )
    with pytest.raises(PydanticValidationError, match="experimental unit IDs differ only by case"):
        EcologyIdentityRegistryResponse.model_validate(forged)

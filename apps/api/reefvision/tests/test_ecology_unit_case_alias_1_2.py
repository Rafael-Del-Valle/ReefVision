"""Case-alias physical-unit integrity across API, signed registry and saved workflows."""

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
    client: TestClient, project_id: str, organism_key: str, unit_type: str, unit_id: str
) -> Any:
    return client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms",
        json={
            "organism_key": organism_key,
            "kind": "individual",
            "experimental_unit_type": unit_type,
            "experimental_unit_id": unit_id,
            "reason": "Register physical sampling units for the study",
        },
    )


@pytest.mark.parametrize(
    ("original", "alias"),
    [
        ("Tank-1", "tank-1"),
        ("Stra\\u00dfe-1", "STRASSE-1"),
    ],
    ids=["ascii-case", "unicode-casefold"],
)
def test_case_alias_registration_revision_and_distinct_level(
    client: TestClient, original: str, alias: str
) -> None:
    project_id = str(create_project(client, "Case-safe independent units")["id"])
    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    first = _register(client, project_id, "individual-A", "tank", original)
    assert first.status_code == 201, first.text
    same_unit = _register(client, project_id, "individual-B", "aquarium", original)
    assert same_unit.status_code == 201, same_unit.text
    before = client.get(registry_url).json()

    collision = _register(client, project_id, "individual-C", "aquaria", alias)
    assert collision.status_code == 400, collision.text
    assert "differ only by case" in collision.json()["detail"]
    revision = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/individual-B/revisions",
        json={
            "expected_revision": 1,
            "kind": "individual",
            "experimental_unit_type": "tank",
            "experimental_unit_id": alias,
            "reason": "Attempt to relabel a physical unit using a case alias",
        },
    )
    assert revision.status_code == 400, revision.text
    assert "differ only by case" in revision.json()["detail"]
    assert client.get(registry_url).json() == before

    # A different physical sampling level has a distinct namespace.
    other_level = _register(client, project_id, "individual-C", "site", alias)
    assert other_level.status_code == 201, other_level.text
    assert client.get(registry_url).json()["evidence_level"] == "registered_unverified"


def test_case_alias_import_rejected_by_registry_and_executable_saved_graph(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Imported physical-unit case collision")["id"])
    assert _register(client, project_id, "individual-A", "tank", "Tank-1").status_code == 201
    assert _register(client, project_id, "individual-B", "tank", "tank-2").status_code == 201

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            EcologyIdentityRevision(
                project_id=project_id,
                organism_key="individual-B",
                revision=2,
                kind="individual",
                parent_colony_key=None,
                experimental_unit_type="aquarium",
                experimental_unit_id="tank-1",
                reason="Simulated unreviewed import using a case alias",
            )
        )
        session.commit()

    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "differ only by case" in registry.json()["detail"]

    graph: dict[str, Any] = {
        "graph_id": "ecology-case-alias-1-2",
        "name": "Reject physical-unit case aliases",
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
    assert "differ only by case" in detail.json()["run"]["error_message"]
    assert not any(
        artifact["data_type"] == "ecology_identity_registry"
        for artifact in detail.json()["artifacts"]
    )


def test_resigned_registry_cannot_replay_case_alias_as_independent_unit(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Case-alias persisted replay")["id"])
    assert _register(client, project_id, "individual-A", "tank", "Tank-1").status_code == 201
    assert _register(client, project_id, "individual-B", "tank", "tank-2").status_code == 201
    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    original = client.get(registry_url).json()
    EcologyIdentityRegistryResponse.model_validate(original)

    tampered = deepcopy(original)
    for collection in ("identities", "identity_history"):
        for row in tampered[collection]:
            if row["organism_key"] == "individual-B":
                row["experimental_unit_id"] = "tank-1"
    tampered["snapshot_sha256"] = canonical_json_sha256(
        {
            "schema_version": tampered["schema_version"],
            "project_id": project_id,
            "identities": [
                {
                    field: row[field]
                    for field in (
                        "id",
                        "organism_key",
                        "revision",
                        "kind",
                        "parent_colony_key",
                        "experimental_unit_type",
                        "experimental_unit_id",
                    )
                }
                for row in tampered["identities"]
            ],
        }
    )
    tampered["history_sha256"] = canonical_json_sha256(
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
                for row in tampered["identity_history"]
            ],
        }
    )
    with pytest.raises(PydanticValidationError, match="differ only by case"):
        EcologyIdentityRegistryResponse.model_validate(tampered)

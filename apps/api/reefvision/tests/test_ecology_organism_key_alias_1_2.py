"""Organism identity keys must not split into case or Unicode aliases."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.db.models.ecology_identity_revision import EcologyIdentityRevision
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_identity_registry_1_2 import _register


@pytest.mark.parametrize(
    ("alias", "expected_status"),
    [("coral-01", 409), ("\uff23\uff4f\uff52\uff41\uff4c-01", 422)],
)
def test_organism_case_alias_registration_rejected_without_mutating_registry(
    client: TestClient, alias: str, expected_status: int
) -> None:
    project_id = str(create_project(client, "Case-safe coral identity")["id"])
    base = f"/api/v1/projects/{project_id}/ecology"
    assert _register(client, project_id, "Coral-01").status_code == 201
    before = client.get(f"{base}/identity-registry").json()
    attempt = _register(client, project_id, alias)
    assert attempt.status_code == expected_status, attempt.text
    if expected_status == 409:
        assert "organism keys differ only by case" in attempt.text
    assert client.get(f"{base}/identity-registry").json() == before

    revised = client.post(
        f"{base}/organisms/Coral-01/revisions",
        json={
            "expected_revision": 1,
            "kind": "colony",
            "reason": "Preserve the same biological identity across revisions",
        },
    )
    assert revised.status_code == 201, revised.text
    registry = client.get(f"{base}/identity-registry")
    assert registry.status_code == 200, registry.text
    assert registry.json()["history_revision_count"] == 2


@pytest.mark.parametrize("alias", ["coral-01", "\uff23\uff4f\uff52\uff41\uff4c-01"])
def test_imported_case_alias_blocks_registry_writes_and_saved_workflow(
    client: TestClient, alias: str
) -> None:
    project_id = str(create_project(client, "Imported organism alias")["id"])
    base = f"/api/v1/projects/{project_id}/ecology"
    assert _register(client, project_id, "Coral-01").status_code == 201
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            EcologyIdentityRevision(
                project_id=project_id,
                organism_key=alias,
                revision=1,
                kind="colony",
                reason="Simulated imported compatibility-aliased biological identity",
            )
        )
        session.commit()

    registry = client.get(f"{base}/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "organism keys differ only by case" in registry.text
    attempted = _register(client, project_id, "Coral-02")
    assert attempted.status_code == 400, attempted.text

    graph = {
        "graph_id": "ecology-organism-key-case-1-2",
        "name": "Fail closed on biological identity aliases",
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
    assert "organism keys differ only by case" in detail.json()["run"]["error_message"]
    assert not any(
        row["data_type"] == "ecology_identity_registry" for row in detail.json()["artifacts"]
    )


@pytest.mark.parametrize("alias", ["coral-01", "\uff23\uff4f\uff52\uff41\uff4c-01"])
def test_resigned_registry_cannot_replay_organism_case_alias(
    client: TestClient, alias: str
) -> None:
    project_id = str(create_project(client, "Resigned organism aliases")["id"])
    assert _register(client, project_id, "Coral-01").status_code == 201
    assert _register(client, project_id, "coral-02").status_code == 201
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    original = registry.json()
    EcologyIdentityRegistryResponse.model_validate(original)

    changed = deepcopy(original)
    for collection in ("identities", "identity_history"):
        for row in changed[collection]:
            if row["organism_key"] == "coral-02":
                row["organism_key"] = alias
    changed["snapshot_sha256"] = canonical_json_sha256(
        {
            "schema_version": changed["schema_version"],
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
                for row in changed["identities"]
            ],
        }
    )
    changed["history_sha256"] = canonical_json_sha256(
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
                for row in changed["identity_history"]
            ],
        }
    )
    with pytest.raises(PydanticValidationError, match="organism keys differ only by case"):
        EcologyIdentityRegistryResponse.model_validate(changed)

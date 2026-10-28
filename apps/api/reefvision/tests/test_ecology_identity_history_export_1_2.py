"""Identity-history export must match typed saved Workflow Builder evidence."""

from __future__ import annotations

import csv
from io import StringIO
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.services.ecology_identity_history_export import render_ecology_identity_history_csv
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project


def _register(client: TestClient, project_id: str, organism_key: str, **kwargs: Any) -> None:
    response = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms",
        json={
            "organism_key": organism_key,
            "kind": "individual",
            "reason": "Initial biological identity registration",
            **kwargs,
        },
    )
    assert response.status_code == 201, response.text


def test_history_csv_matches_persisted_typed_workflow_and_retains_old_units(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Identity history CSV and workflow")["id"])
    _register(
        client,
        project_id,
        "specimen-1",
        experimental_unit_type="tank",
        experimental_unit_id="tank-A",
    )
    changed = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/specimen-1/revisions",
        json={
            "expected_revision": 1,
            "kind": "individual",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-B",
            "reason": "Correct assignment using reviewed laboratory notes",
        },
    )
    assert changed.status_code == 201, changed.text
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    url = f"/api/v1/projects/{project_id}/ecology/identity-registry/history.csv"
    response = client.get(url)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(StringIO(response.text)))
    assert len(rows) == 2
    assert [row["revision"] for row in rows] == ["1", "2"]
    assert [row["experimental_unit_id"] for row in rows] == ["tank-A", "tank-B"]
    assert all(row["evidence_level"] == "registered_unverified" for row in rows)
    assert all(row["review_gate"] == "scientist_review_required" for row in rows)
    assert all(row["history_sha256"] == registry.json()["history_sha256"] for row in rows)

    graph = {
        "graph_id": "ecology-history-csv-parity-1-2",
        "name": "Persist full identity history",
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
    typed = EcologyIdentityRegistryResponse.model_validate(artifacts[0]["payload_json"])
    assert typed.model_dump(mode="json") == registry.json()
    assert render_ecology_identity_history_csv(typed) == response.text


def test_identity_history_csv_rejects_tampered_or_legacy_artifacts(client: TestClient) -> None:
    project_id = str(create_project(client, "Identity history export corruption")["id"])
    _register(client, project_id, "specimen-2")
    payload = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert payload.status_code == 200, payload.text
    typed = EcologyIdentityRegistryResponse.model_validate(payload.json())

    altered = typed.model_copy(deep=True)
    altered.identity_history[0].reason = "Forged revision reason"
    with pytest.raises(ValidationError, match="history fingerprint mismatch"):
        render_ecology_identity_history_csv(altered)

    altered = typed.model_copy(deep=True)
    altered.history_revision_count += 1
    with pytest.raises(ValidationError, match="revision count mismatch"):
        render_ecology_identity_history_csv(altered)

    altered = typed.model_copy(deep=True)
    altered.identities[0].experimental_unit_id = "invented-unit"
    with pytest.raises(ValidationError, match="latest record differs"):
        render_ecology_identity_history_csv(altered)

    snapshot_sha256 = canonical_json_sha256(
        {
            "schema_version": "ecology-identity-registry-0001",
            "project_id": project_id,
            "identities": [],
        }
    )
    legacy = EcologyIdentityRegistryResponse.model_validate(
        {"project_id": project_id, "identities": [], "snapshot_sha256": snapshot_sha256}
    )
    with pytest.raises(ValidationError, match="fingerprint is missing"):
        render_ecology_identity_history_csv(legacy)


def test_identity_history_csv_escapes_spreadsheet_formulas(client: TestClient) -> None:
    project_id = str(create_project(client, "Identity spreadsheet injection")["id"])
    _register(
        client,
        project_id,
        "specimen-3",
        experimental_unit_type="tank",
        experimental_unit_id="=2+2",
        reason="=HYPERLINK(1,2)",
    )
    response = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry/history.csv")
    assert response.status_code == 200, response.text
    row = next(csv.DictReader(StringIO(response.text)))
    assert row["experimental_unit_id"] == "'=2+2"
    assert row["reason"] == "'=HYPERLINK(1,2)"
    assert row["review_gate"] == "scientist_review_required"

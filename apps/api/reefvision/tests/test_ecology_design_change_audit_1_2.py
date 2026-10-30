"""Project-scoped design revision QC and saved-workflow parity."""

from __future__ import annotations

import csv
import json
from io import StringIO
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.services.ecology_identity_history_export import render_ecology_identity_history_csv
from reefvision.tests.test_annotations import create_project


def _register(client: TestClient, project_id: str, key: str, kind: str, **extra: str) -> None:
    response = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms",
        json={
            "organism_key": key,
            "kind": kind,
            "reason": "Initial biological identity registration",
            **extra,
        },
    )
    assert response.status_code == 201, response.text


def _revise(client: TestClient, project_id: str, key: str, revision: int, **extra: str) -> None:
    response = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/{key}/revisions",
        json={
            "expected_revision": revision,
            "reason": "Correct registered scientific design metadata",
            **extra,
        },
    )
    assert response.status_code == 201, response.text


def test_design_reassignment_reversion_and_saved_workflow_parity(client: TestClient) -> None:
    project_id = str(create_project(client, "Tank assignment revision QC")["id"])
    _register(
        client,
        project_id,
        "coral-1",
        "individual",
        experimental_unit_type="tank",
        experimental_unit_id="tank-A",
    )
    url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    initial = client.get(url).json()
    assert initial["design_history_status"] == "no_design_changes_recorded"
    assert initial["design_change_events"] == []

    _revise(
        client,
        project_id,
        "coral-1",
        1,
        kind="individual",
        experimental_unit_type="tank",
        experimental_unit_id="tank-A",
    )
    assert client.get(url).json()["design_change_count"] == 0
    _revise(
        client,
        project_id,
        "coral-1",
        2,
        kind="individual",
        experimental_unit_type="tank",
        experimental_unit_id="tank-B",
    )
    _revise(
        client,
        project_id,
        "coral-1",
        3,
        kind="individual",
        experimental_unit_type="tank",
        experimental_unit_id="tank-A",
    )
    response = client.get(url)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["design_history_status"] == "design_changes_require_review"
    assert payload["design_change_count"] == 2
    events = payload["design_change_events"]
    assert [(e["from_revision"], e["to_revision"]) for e in events] == [(2, 3), (3, 4)]
    assert [e["changed_fields"] for e in events] == [
        ["experimental_unit_id"],
        ["experimental_unit_id"],
    ]
    assert events[0]["previous_experimental_unit_id"] == "tank-A"
    assert events[0]["current_experimental_unit_id"] == "tank-B"
    assert payload["evidence_level"] == "registered_unverified"
    assert payload["review_gate"] == "scientist_review_required"

    graph = {
        "graph_id": "design-revision-audit-1-2",
        "name": "Saved design revision audit",
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
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
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
    assert artifacts[0]["payload_json"] == payload
    exported = client.get(f"{url}/history.csv")
    assert exported.status_code == 200, exported.text
    rows = list(csv.DictReader(StringIO(exported.text)))
    assert all(row["design_history_status"] == "design_changes_require_review" for row in rows)
    assert all(row["design_change_count"] == "2" for row in rows)
    # Each change is exported on its actual append-only revision, rather
    # than leaving reviewers with an aggregate count and no assignment trail.
    assert [row["design_revision_change_json"] for row in rows[:2]] == ["", ""]
    exported_events = [json.loads(row["design_revision_change_json"]) for row in rows[2:]]
    assert exported_events == events
    assert [(row["revision"], event["to_revision"]) for row, event in zip(
        rows[2:], exported_events, strict=True
    )] == [("3", 3), ("4", 4)]
    assert exported_events[0]["previous_experimental_unit_id"] == "tank-A"
    assert exported_events[0]["current_experimental_unit_id"] == "tank-B"
    assert exported_events[1]["current_experimental_unit_id"] == "tank-A"
    assert render_ecology_identity_history_csv(
        EcologyIdentityRegistryResponse.model_validate(artifacts[0]["payload_json"])
    ) == exported.text


def test_parent_change_is_flagged_and_not_promoted_to_verified(client: TestClient) -> None:
    project_id = str(create_project(client, "Parent design correction")["id"])
    _register(client, project_id, "colony-A", "colony")
    _register(client, project_id, "colony-B", "colony")
    _register(client, project_id, "fragment-1", "fragment", parent_colony_key="colony-A")
    _revise(client, project_id, "fragment-1", 1, kind="fragment", parent_colony_key="colony-B")
    result = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert result.status_code == 200, result.text
    assert result.json()["design_change_count"] == 1
    event = result.json()["design_change_events"][0]
    assert event["changed_fields"] == ["parent_colony_key"]
    assert event["previous_parent_colony_key"] == "colony-A"
    assert event["current_parent_colony_key"] == "colony-B"
    assert result.json()["review_gate"] == "scientist_review_required"


def test_history_export_detects_tampering_and_marks_legacy_unknown(client: TestClient) -> None:
    project_id = str(create_project(client, "Design history integrity")["id"])
    _register(
        client,
        project_id,
        "coral-2",
        "individual",
        experimental_unit_type="tank",
        experimental_unit_id="tank-A",
    )
    _revise(
        client,
        project_id,
        "coral-2",
        1,
        kind="individual",
        experimental_unit_type="tank",
        experimental_unit_id="tank-B",
    )
    response = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert response.status_code == 200, response.text
    typed = EcologyIdentityRegistryResponse.model_validate(response.json())
    assert "design_changes_require_review" in render_ecology_identity_history_csv(typed)
    forged = typed.model_copy(deep=True)
    forged.design_change_events.clear()
    with pytest.raises(ValidationError, match="design-change audit differs"):
        render_ecology_identity_history_csv(forged)
    forged = typed.model_copy(deep=True)
    forged.design_change_count = 0
    with pytest.raises(ValidationError, match="design-change audit differs"):
        render_ecology_identity_history_csv(forged)
    forged = typed.model_copy(deep=True)
    forged.design_history_status = "no_design_changes_recorded"
    with pytest.raises(ValidationError, match="design-change audit differs"):
        render_ecology_identity_history_csv(forged)
    legacy_payload = response.json()
    for key in ("design_history_status", "design_change_count", "design_change_events"):
        legacy_payload.pop(key)
    legacy = EcologyIdentityRegistryResponse.model_validate(legacy_payload)
    assert legacy.design_history_status == "history_unavailable"
    legacy_rows = list(csv.DictReader(StringIO(render_ecology_identity_history_csv(legacy))))
    assert legacy_rows
    assert all(row["design_history_status"] == "history_unavailable" for row in legacy_rows)
    assert all(row["design_revision_change_json"] == "" for row in legacy_rows)

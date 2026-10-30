"""Registered shared-parent study-design QC through API and saved workflows."""

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
from reefvision.schemas.ecology_identity import (
    EcologyCrossUnitParentDetail,
    EcologyIdentityRegistryResponse,
)
from reefvision.services.ecology_identity_history_export import render_ecology_identity_history_csv
from reefvision.tests.test_annotations import create_project


def _register(
    client: TestClient,
    project_id: str,
    key: str,
    kind: str,
    *,
    parent: str | None = None,
    unit_type: str | None = None,
    unit_id: str | None = None,
) -> None:
    response = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms",
        json={
            "organism_key": key,
            "kind": kind,
            "parent_colony_key": parent,
            "experimental_unit_type": unit_type,
            "experimental_unit_id": unit_id,
            "reason": "Register biological identity for experimental design review",
        },
    )
    assert response.status_code == 201, response.text


def test_shared_parent_tanks_api_csv_and_saved_workflow(client: TestClient) -> None:
    project_id = str(create_project(client, "Shared-parent tank review")["id"])
    _register(client, project_id, "parent-A", "colony")
    _register(client, project_id, "parent-B", "colony")
    _register(
        client,
        project_id,
        "fragment-A",
        "fragment",
        parent="parent-A",
        unit_type="tank",
        unit_id="tank-1",
    )
    _register(
        client,
        project_id,
        "fragment-B",
        "fragment",
        parent="parent-A",
        unit_type="aquarium",
        unit_id="tank-2",
    )
    _register(
        client,
        project_id,
        "fragment-C",
        "fragment",
        parent="parent-A",
        unit_type="tank",
        unit_id="tank-2",
    )
    _register(
        client,
        project_id,
        "fragment-D",
        "fragment",
        parent="parent-B",
        unit_type="tank",
        unit_id="tank-1",
    )
    url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    response = client.get(url)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["cross_unit_parent_audit_status"] == "shared_parent_requires_review"
    assert payload["cross_unit_shared_parent_colony_keys"] == ["parent-A"]
    assert payload["cross_unit_parent_details"] == [
        {
            "parent_colony_key": "parent-A",
            "experimental_unit_level": "tank",
            "experimental_unit_ids": ["tank-1", "tank-2"],
            "fragment_keys": ["fragment-A", "fragment-B", "fragment-C"],
        }
    ]
    assert payload["evidence_level"] == "registered_unverified"
    assert payload["review_gate"] == "scientist_review_required"

    csv_response = client.get(f"{url}/history.csv")
    assert csv_response.status_code == 200, csv_response.text
    csv_rows = list(csv.DictReader(StringIO(csv_response.text)))
    assert all(
        row["cross_unit_parent_audit_status"] == "shared_parent_requires_review" for row in csv_rows
    )
    assert all(row["cross_unit_shared_parent_colony_keys"] == "parent-A" for row in csv_rows)
    expected_details = json.dumps(
        payload["cross_unit_parent_details"], sort_keys=True, separators=(",", ":")
    )
    assert all(row["cross_unit_parent_details_json"] == expected_details for row in csv_rows)

    graph = {
        "graph_id": "registered-shared-parent-review",
        "name": "Registered shared parent review",
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
    typed = EcologyIdentityRegistryResponse.model_validate(artifacts[0]["payload_json"])
    assert render_ecology_identity_history_csv(typed) == csv_response.text

    # Revalidation of copied typed artifacts now fails closed before the
    # derived audit-specific error paths, without exposing source details.
    # An explicitly supplied modern detail list is authenticated against
    # fingerprint-checked identities; dropping the shared-parent evidence
    # must fail closed rather than suppressing the pseudoreplication warning.
    tampered = typed.model_copy(deep=True)
    tampered.cross_unit_parent_details = []
    with pytest.raises(ValidationError, match="source evidence integrity check failed"):
        render_ecology_identity_history_csv(tampered)

    # Altered contributing fragments or units are likewise rejected.
    tampered = typed.model_copy(deep=True)
    tampered.cross_unit_parent_details[0].fragment_keys = ["fragment-A", "fragment-B"]
    with pytest.raises(ValidationError, match="source evidence integrity check failed"):
        render_ecology_identity_history_csv(tampered)

    # Existing saved artifacts with the older, status-only audit remain
    # exportable; the CSV recomputes details from fingerprint-checked rows.
    pre_detail = payload.copy()
    pre_detail.pop("cross_unit_parent_details")
    restored = EcologyIdentityRegistryResponse.model_validate(pre_detail)
    assert restored.cross_unit_parent_audit_status == "shared_parent_requires_review"
    assert restored.cross_unit_parent_details == []
    assert render_ecology_identity_history_csv(restored) == csv_response.text


def test_no_false_cross_unit_parent_claims_and_csv_tampering(client: TestClient) -> None:
    project_id = str(create_project(client, "Separate tank and site levels")["id"])
    _register(client, project_id, "parent-C", "colony")
    _register(
        client,
        project_id,
        "fragment-1",
        "fragment",
        parent="parent-C",
        unit_type="tank",
        unit_id="unit-1",
    )
    _register(
        client,
        project_id,
        "fragment-2",
        "fragment",
        parent="parent-C",
        unit_type="tank",
        unit_id="unit-1",
    )
    _register(
        client,
        project_id,
        "fragment-3",
        "fragment",
        parent="parent-C",
        unit_type="site",
        unit_id="site-2",
    )
    url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    response = client.get(url)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["cross_unit_parent_audit_status"] == "no_cross_unit_parent_reuse"
    assert payload["cross_unit_shared_parent_colony_keys"] == []
    assert payload["cross_unit_parent_details"] == []
    assert payload["review_gate"] == "scientist_review_required"

    typed = EcologyIdentityRegistryResponse.model_validate(payload)
    tampered = typed.model_copy(deep=True)
    tampered.cross_unit_parent_audit_status = "shared_parent_requires_review"
    with pytest.raises(ValidationError, match="source evidence integrity check failed"):
        render_ecology_identity_history_csv(tampered)
    tampered = typed.model_copy(deep=True)
    tampered.cross_unit_shared_parent_colony_keys = ["invented-parent"]
    with pytest.raises(ValidationError, match="source evidence integrity check failed"):
        render_ecology_identity_history_csv(tampered)
    # The expected details are already empty for a parent present in only
    # one tank; assigning [] again is not tampering. A fabricated detail
    # naming a second tank must be rejected instead.
    tampered = typed.model_copy(deep=True)
    tampered.cross_unit_parent_details = [
        EcologyCrossUnitParentDetail(
            parent_colony_key="parent-C",
            experimental_unit_level="tank",
            experimental_unit_ids=["unit-1", "invented-unit"],
            fragment_keys=["fragment-1", "fragment-2"],
        )
    ]
    with pytest.raises(ValidationError, match="source evidence integrity check failed"):
        render_ecology_identity_history_csv(tampered)

    legacy = payload.copy()
    legacy.pop("cross_unit_parent_audit_status")
    legacy.pop("cross_unit_shared_parent_colony_keys")
    legacy.pop("cross_unit_parent_details")
    old = EcologyIdentityRegistryResponse.model_validate(legacy)
    assert old.cross_unit_parent_audit_status == "unavailable"
    assert old.cross_unit_parent_details == []
    assert "unavailable" in render_ecology_identity_history_csv(old)


def test_historical_parent_unit_exposure_api_workflow_and_csv(
    client: TestClient,
) -> None:
    """A corrected latest tank assignment must not erase earlier QC evidence."""
    project_id = str(create_project(client, "Historical parent-unit audit")["id"])
    _register(client, project_id, "parent-history", "colony")
    _register(
        client,
        project_id,
        "fragment-history",
        "fragment",
        parent="parent-history",
        unit_type="tank",
        unit_id="tank-A",
    )
    url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    initial = client.get(url)
    assert initial.status_code == 200, initial.text
    assert (
        initial.json()["historical_cross_unit_parent_audit_status"]
        == "no_recorded_cross_unit_parent_reuse"
    )

    for revision, tank in [(1, "tank-B"), (2, "tank-A")]:
        response = client.post(
            f"/api/v1/projects/{project_id}/ecology/organisms/fragment-history/revisions",
            json={
                "expected_revision": revision,
                "kind": "fragment",
                "parent_colony_key": "parent-history",
                "experimental_unit_type": "aquarium" if revision == 1 else "tank",
                "experimental_unit_id": tank,
                "reason": "Correct historical experimental assignment for audit",
            },
        )
        assert response.status_code == 201, response.text

    response = client.get(url)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["cross_unit_parent_details"] == []
    assert payload["cross_unit_parent_audit_status"] == "no_cross_unit_parent_reuse"
    assert (
        payload["historical_cross_unit_parent_audit_status"]
        == "recorded_across_units_requires_review"
    )
    details = payload["historical_cross_unit_parent_details"]
    assert len(details) == 1
    assert details[0]["experimental_unit_level"] == "tank"
    assert details[0]["experimental_unit_ids"] == ["tank-A", "tank-B"]
    assert [
        (row["identity_revision"], row["experimental_unit_id"]) for row in details[0]["assignments"]
    ] == [(1, "tank-A"), (3, "tank-A"), (2, "tank-B")]
    assert payload["evidence_level"] == "registered_unverified"
    assert payload["review_gate"] == "scientist_review_required"

    csv_response = client.get(f"{url}/history.csv")
    assert csv_response.status_code == 200, csv_response.text
    csv_rows = list(csv.DictReader(StringIO(csv_response.text)))
    assert len(csv_rows) == 4
    expected_json = json.dumps(details, sort_keys=True, separators=(",", ":"))
    assert all(
        row["historical_cross_unit_parent_details_json"] == expected_json for row in csv_rows
    )

    graph = {
        "graph_id": "historical-parent-unit-audit",
        "name": "Historical parent unit review",
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
    result = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert result.status_code == 200, result.text
    assert result.json()["run"]["status"] == "succeeded"
    artifacts = [
        item
        for item in result.json()["artifacts"]
        if item["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == payload

    typed = EcologyIdentityRegistryResponse.model_validate(payload)
    assert render_ecology_identity_history_csv(typed) == csv_response.text
    tampered = typed.model_copy(deep=True)
    tampered.historical_cross_unit_parent_details[0].assignments.pop()
    with pytest.raises(ValidationError, match="source evidence integrity check failed"):
        render_ecology_identity_history_csv(tampered)
    tampered = typed.model_copy(deep=True)
    tampered.historical_cross_unit_parent_audit_status = "no_recorded_cross_unit_parent_reuse"
    with pytest.raises(ValidationError, match="source evidence integrity check failed"):
        render_ecology_identity_history_csv(tampered)

    legacy = payload.copy()
    legacy.pop("historical_cross_unit_parent_audit_status")
    legacy.pop("historical_cross_unit_parent_details")
    old = EcologyIdentityRegistryResponse.model_validate(legacy)
    assert old.historical_cross_unit_parent_audit_status == "unavailable"
    assert old.historical_cross_unit_parent_details == []
    assert "unavailable" in render_ecology_identity_history_csv(old)

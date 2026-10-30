"""Identity-history export must match typed saved Workflow Builder evidence."""

from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models.ecology_identity_image_evidence import EcologyIdentityImageEvidence
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.services.ecology_identity_history_export import render_ecology_identity_history_csv
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_ecology_calibration_evidence_1_2 import (
    _link_calibration,
    _prepared_annotation,
    _save_calibration,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _link, _workflow


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
    # A correction with no earlier source links has empty review queues,
    # not invented observations or implied independent replicates.
    assert rows[0]["design_change_prior_annotation_evidence_ids_json"] == ""
    assert rows[0]["design_change_prior_calibration_evidence_ids_json"] == ""
    assert rows[1]["design_change_prior_annotation_evidence_ids_json"] == "[]"
    assert rows[1]["design_change_prior_calibration_evidence_ids_json"] == "[]"

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


def test_history_csv_traces_revision_sources_and_prior_design_change_evidence(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    linked = _link_calibration(client, project_id, annotation)
    assert linked.status_code == 201, linked.text

    revised = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/colony-a/revisions",
        json={
            "expected_revision": 1,
            "kind": "colony",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-A",
            "reason": "Correct study design after checking original tank records",
        },
    )
    assert revised.status_code == 201, revised.text
    url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    response = client.get(url)
    assert response.status_code == 200, response.text
    registry = response.json()
    csv_response = client.get(f"{url}/history.csv")
    assert csv_response.status_code == 200, csv_response.text
    rows = list(csv.DictReader(StringIO(csv_response.text)))
    assert len(rows) == 2

    image_id_link = registry["image_evidence_links"][0]["id"]
    annotation_id_link = registry["annotation_evidence_links"][0]["id"]
    calibration_id_link = registry["calibration_evidence_links"][0]["id"]
    assert json.loads(rows[0]["revision_image_evidence_ids_json"]) == [image_id_link]
    assert rows[0]["revision_image_metadata_qc_status"] == "frozen_metadata_linked_unverified"
    assert json.loads(rows[0]["revision_legacy_unfrozen_image_evidence_ids_json"]) == []
    assert rows[1]["revision_image_metadata_qc_status"] == "no_image_evidence"
    assert json.loads(rows[1]["revision_legacy_unfrozen_image_evidence_ids_json"]) == []
    assert json.loads(rows[0]["revision_annotation_evidence_ids_json"]) == [annotation_id_link]
    assert json.loads(rows[0]["revision_calibration_evidence_ids_json"]) == [calibration_id_link]
    for field in (
        "revision_image_evidence_ids_json",
        "revision_annotation_evidence_ids_json",
        "revision_calibration_evidence_ids_json",
    ):
        assert json.loads(rows[1][field]) == []
    assert rows[0]["design_change_prior_image_evidence_ids_json"] == ""
    assert rows[0]["design_change_prior_annotation_evidence_ids_json"] == ""
    assert rows[0]["design_change_prior_calibration_evidence_ids_json"] == ""
    assert json.loads(rows[1]["design_change_prior_image_evidence_ids_json"]) == [image_id_link]
    assert json.loads(rows[1]["design_change_prior_annotation_evidence_ids_json"]) == [
        annotation_id_link
    ]
    assert json.loads(rows[1]["design_change_prior_calibration_evidence_ids_json"]) == [
        calibration_id_link
    ]
    for row in rows:
        for name in (
            "image_evidence_sha256",
            "annotation_evidence_sha256",
            "calibration_evidence_sha256",
        ):
            assert row[name] == registry[name]
        assert row["evidence_level"] == "registered_unverified"
        assert row["review_gate"] == "scientist_review_required"

    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [
        item for item in run["artifacts"] if item["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    typed = EcologyIdentityRegistryResponse.model_validate(artifacts[0]["payload_json"])
    assert render_ecology_identity_history_csv(typed) == csv_response.text

    for collection, field, invalid in (
        ("image_evidence_links", "identity_revision", 2),
        ("annotation_evidence_links", "image_evidence_id", "unknown-image-link"),
        ("calibration_evidence_links", "annotation_evidence_id", "unknown-annotation-link"),
    ):
        forged = typed.model_copy(deep=True)
        setattr(getattr(forged, collection)[0], field, invalid)
        with pytest.raises(ValidationError, match="source evidence integrity check failed"):
            render_ecology_identity_history_csv(forged)


def test_history_csv_flags_legacy_unfrozen_source_metadata_with_workflow_parity(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Legacy ecological source metadata QC")["id"])
    _register(client, project_id, "specimen-legacy")
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    linked = _link(client, project_id, "specimen-legacy", image_id)
    assert linked.status_code == 201, linked.text
    assert linked.json()["source_metadata_evidence_status"] == "frozen"

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        evidence = session.scalar(
            select(EcologyIdentityImageEvidence).where(
                EcologyIdentityImageEvidence.project_id == project_id
            )
        )
        assert evidence is not None
        evidence.source_metadata_sha256 = None
        session.commit()

    url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    registry = client.get(url)
    assert registry.status_code == 200, registry.text
    assert registry.json()["image_evidence_links"][0]["source_metadata_evidence_status"] == (
        "legacy_unfrozen"
    )
    response = client.get(f"{url}/history.csv")
    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(StringIO(response.text)))
    assert len(rows) == 1
    assert rows[0]["revision_image_metadata_qc_status"] == "legacy_unfrozen_requires_review"
    assert json.loads(rows[0]["revision_legacy_unfrozen_image_evidence_ids_json"]) == [
        linked.json()["id"]
    ]
    assert rows[0]["review_gate"] == "scientist_review_required"

    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [
        row for row in run["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    typed = EcologyIdentityRegistryResponse.model_validate(artifacts[0]["payload_json"])
    assert render_ecology_identity_history_csv(typed) == response.text

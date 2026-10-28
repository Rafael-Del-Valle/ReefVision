"""Source-image identity links must remain project-scoped and unverified."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import pytest
from sqlalchemy import select

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaValidationError

from reefvision.db.models import ImageAsset
from reefvision.db.models.ecology_identity_image_evidence import EcologyIdentityImageEvidence
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.tests.test_annotations import create_project, import_one


def _register(client: TestClient, project_id: str, key: str) -> None:
    response = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms",
        json={
            "organism_key": key,
            "kind": "colony",
            "reason": "Registered colony for image provenance",
        },
    )
    assert response.status_code == 201, response.text


def _link(client: TestClient, project_id: str, key: str, image_id: str) -> Any:
    return client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/{key}/image-evidence",
        json={
            "image_id": image_id,
            "expected_identity_revision": 1,
            "reason": "Source image associated with this colony",
        },
    )


def _workflow(client: TestClient, project_id: str) -> dict[str, Any]:
    graph = {
        "graph_id": "ecology-image-evidence-1-2",
        "name": "Image evidence registry",
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
    process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        str(queued.json()["job_id"]),
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    return cast(dict[str, Any], detail.json())


def test_project_image_link_is_append_only_and_workflow_persists_same_unverified_evidence(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Linked image provenance")["id"])
    _register(client, project_id, "colony-16")
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    before = client.get(url).json()
    linked = _link(client, project_id, "colony-16", image_id)
    assert linked.status_code == 201, linked.text
    assert linked.json()["identity_revision"] == 1
    assert linked.json()["evidence_level"] == "linked_unverified"
    assert len(linked.json()["image_sha256"]) == 64
    assert _link(client, project_id, "colony-16", image_id).status_code == 409

    registry = client.get(url)
    assert registry.status_code == 200, registry.text
    snapshot = registry.json()
    assert snapshot["snapshot_sha256"] == before["snapshot_sha256"]
    assert snapshot["history_sha256"] == before["history_sha256"]
    assert snapshot["image_evidence_sha256"] != before["image_evidence_sha256"]
    assert snapshot["image_evidence_count"] == 1
    assert snapshot["image_evidence_links"] == [linked.json()]
    assert snapshot["review_gate"] == "scientist_review_required"
    assert snapshot["evidence_level"] == "registered_unverified"

    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [row for row in run["artifacts"] if row["data_type"] == "ecology_identity_registry"]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == snapshot


def test_image_link_rejects_cross_project_stale_identity_and_unknown_organism(
    client: TestClient,
) -> None:
    first = str(create_project(client, "Evidence owner A")["id"])
    second = str(create_project(client, "Evidence owner B")["id"])
    _register(client, first, "colony-39")
    image_id = str(import_one(client, second)["successful"][0]["image_id"])
    assert _link(client, first, "colony-39", image_id).status_code == 400
    assert _link(client, first, "unknown-colony", image_id).status_code == 404
    own_image = str(import_one(client, first)["successful"][0]["image_id"])
    revise = client.post(
        f"/api/v1/projects/{first}/ecology/organisms/colony-39/revisions",
        json={
            "expected_revision": 1,
            "kind": "colony",
            "reason": "Correct the registered identity notes",
        },
    )
    assert revise.status_code == 201, revise.text
    assert _link(client, first, "colony-39", own_image).status_code == 409
    registry = client.get(f"/api/v1/projects/{first}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    assert registry.json()["image_evidence_links"] == []


def test_changed_source_image_hash_fails_closed_for_api_and_saved_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Image source integrity")["id"])
    _register(client, project_id, "colony-68")
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    assert _link(client, project_id, "colony-68", image_id).status_code == 201
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.sha256 = "0" * 64
        session.commit()

    response = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert response.status_code == 400, response.text
    assert "source is missing or changed" in response.json()["detail"]
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "failed"
    assert "source is missing or changed" in run["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in run["artifacts"])


def test_malformed_imported_image_metadata_fails_closed_before_linking(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Invalid imported image metadata")["id"])
    _register(client, project_id, "colony-source-qc")
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.sha256 = "not-a-valid-sha256"
        session.commit()

    linked = _link(client, project_id, "colony-source-qc", image_id)
    assert linked.status_code == 400, linked.text
    assert "invalid source SHA-256" in linked.json()["detail"]
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    assert registry.json()["image_evidence_count"] == 0


def test_malformed_source_dimensions_fail_closed_in_api_and_saved_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Image metadata QC after linking")["id"])
    _register(client, project_id, "colony-image-qc")
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    assert _link(client, project_id, "colony-image-qc", image_id).status_code == 201
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.width_px = 0
        session.commit()

    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 400, registry.text
    assert "invalid source dimensions or size" in registry.json()["detail"]
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "failed"
    assert "invalid source dimensions or size" in run["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in run["artifacts"])


@pytest.mark.parametrize(
    ("original", "changed"),
    [
        (None, datetime(2026, 4, 3, 8)),
        (datetime(2026, 4, 3, 8), datetime(2026, 4, 4, 8)),
    ],
)
def test_changed_capture_metadata_revokes_api_and_saved_workflow(
    client: TestClient,
    original: datetime | None,
    changed: datetime,
) -> None:
    """Even a plausible date correction cannot rewrite linked source evidence."""
    project_id = str(create_project(client, "Frozen capture provenance")["id"])
    _register(client, project_id, "colony-time")
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.capture_timestamp = original
        session.commit()

    linked = _link(client, project_id, "colony-time", image_id)
    assert linked.status_code == 201, linked.text
    assert linked.json()["source_metadata_evidence_status"] == "frozen"
    assert len(linked.json()["source_metadata_sha256"]) == 64
    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    before = client.get(registry_url)
    assert before.status_code == 200, before.text
    assert before.json()["image_evidence_links"] == [linked.json()]

    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.capture_timestamp = changed
        session.commit()

    response = client.get(registry_url)
    assert response.status_code == 400, response.text
    assert "metadata changed after linking" in response.json()["detail"]
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert "metadata changed after linking" in workflow["run"]["error_message"]
    assert not any(
        row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"]
    )


def test_changed_positive_image_dimensions_revoke_source_link(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Frozen image dimensions")["id"])
    _register(client, project_id, "colony-size")
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    assert _link(client, project_id, "colony-size", image_id).status_code == 201
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.width_px += 1
        session.commit()
    response = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert response.status_code == 400, response.text
    assert "metadata changed after linking" in response.json()["detail"]


def test_legacy_image_link_is_explicitly_unfrozen_in_api_and_workflow(
    client: TestClient,
) -> None:
    """A NULL pre-migration fingerprint must not masquerade as frozen evidence."""
    project_id = str(create_project(client, "Legacy source evidence")["id"])
    _register(client, project_id, "colony-legacy")
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    assert _link(client, project_id, "colony-legacy", image_id).status_code == 201
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        link = session.scalar(
            select(EcologyIdentityImageEvidence).where(
                EcologyIdentityImageEvidence.project_id == project_id
            )
        )
        assert link is not None
        link.source_metadata_sha256 = None
        session.commit()
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    evidence = registry.json()["image_evidence_links"][0]
    assert evidence["source_metadata_sha256"] is None
    assert evidence["source_metadata_evidence_status"] == "legacy_unfrozen"
    assert evidence["evidence_level"] == "linked_unverified"
    tampered = registry.json()
    tampered["image_evidence_links"][0]["source_metadata_evidence_status"] = "frozen"
    with pytest.raises(SchemaValidationError, match="contradicts its fingerprint"):
        EcologyIdentityRegistryResponse.model_validate(tampered)
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == registry.json()

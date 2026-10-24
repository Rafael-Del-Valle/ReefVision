"""Source-image identity links must remain project-scoped and unverified."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset
from reefvision.jobs.workflow import process_workflow_run_job
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
    artifacts = [
        row for row in run["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
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
    assert not any(
        row["data_type"] == "ecology_identity_registry" for row in run["artifacts"]
    )

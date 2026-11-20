from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project


def _settings(client: TestClient) -> Settings:
    return cast(Settings, cast(FastAPI, client.app).state.settings)


def _manifest_file(client: TestClient) -> Path:
    directory = _settings(client).resolved_data_dir / "provider-manifests"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "local-depth.json"
    path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "provider_id": "local_depth",
                "display_name": "Local Depth Inspector",
                "provider_version": "0.1.0",
                "description": "An inspect-only local provider declaration.",
                "capabilities": ["image_semantic_segmentation", "cpu_inference"],
                "supported_tasks": ["relative_depth"],
                "availability": {
                    "status": "unavailable",
                    "reason": "A reviewed ReefVision adapter is not installed.",
                },
                "code_license": "Apache-2.0",
                "weight_license": "User supplied",
                "notes": ["Inspection only"],
            }
        ),
        encoding="utf-8",
    )
    return path


def _graph(source_sha256: str) -> dict[str, object]:
    return {
        "graph_id": "provider-manifest-snapshot",
        "name": "Snapshot a local provider manifest",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "manifest",
                "node_type": "provider_manifest_snapshot",
                "parameters": {
                    "record_id": "local_depth",
                    "expected_source_sha256": source_sha256,
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-manifest",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "manifest",
                "target_port_id": "project",
            }
        ],
    }


def _save_and_queue(
    client: TestClient,
    project_id: str,
    graph: dict[str, object],
) -> dict[str, object]:
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    return cast(dict[str, object], queued.json())


def test_registry_exposes_metadata_only_provider_manifest_snapshot(client: TestClient) -> None:
    response = client.get("/api/v1/workflow-graphs/node-registry")

    assert response.status_code == 200, response.text
    node = next(
        item for item in response.json() if item["node_type"] == "provider_manifest_snapshot"
    )
    assert node["executable"] is True
    assert node["required_parameters"] == ["record_id"]
    assert node["input_ports"][0]["accepted_types"] == ["project_reference"]
    assert node["output_ports"][0]["accepted_types"] == ["provider_manifest_snapshot"]
    assert any("never executes" in note for note in node["implementation_notes"])


def test_saved_workflow_snapshots_manifest_provenance_without_executing_provider(
    client: TestClient,
) -> None:
    _manifest_file(client)
    manifest = next(
        item
        for item in client.get("/api/v1/advanced-providers/manifests").json()
        if item["provider_id"] == "local_depth"
    )
    project = create_project(client, "Provider manifest workflow")
    graph = _graph(manifest["source_sha256"])

    plan = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/plan",
        json=graph,
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is True

    run = _save_and_queue(client, project["id"], graph)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        str(run["job_id"]),
    )

    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    artifact = next(
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "provider_manifest_snapshot"
    )
    payload = artifact["payload_json"]
    assert payload["schema_version"] == "provider-manifest-snapshot-0001"
    assert payload["project_id"] == project["id"]
    assert payload["record_id"] == "local_depth"
    assert payload["source_filename"] == "local-depth.json"
    assert payload["source_sha256"] == manifest["source_sha256"]
    assert payload["manifest"]["provider_id"] == "local_depth"
    assert payload["manifest"]["capabilities"] == [
        "image_semantic_segmentation",
        "cpu_inference",
    ]
    assert payload["execution_allowed"] is False
    assert len(payload["snapshot_sha256"]) == 64
    assert len(artifact["payload_sha256"]) == 64


def test_workflow_can_snapshot_an_invalid_manifest_as_unavailable_evidence(
    client: TestClient,
) -> None:
    directory = _settings(client).resolved_data_dir / "provider-manifests"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "broken.json").write_text("{invalid", encoding="utf-8")
    manifest = next(
        item
        for item in client.get("/api/v1/advanced-providers/manifests").json()
        if item["source_filename"] == "broken.json"
    )
    project = create_project(client, "Invalid provider manifest evidence")
    graph = _graph(manifest["source_sha256"])
    nodes = cast(list[dict[str, object]], graph["nodes"])
    parameters = cast(dict[str, object], nodes[1]["parameters"])
    parameters["record_id"] = manifest["provider_id"]
    run = _save_and_queue(client, project["id"], graph)

    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        str(run["job_id"]),
    )
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}").json()
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "provider_manifest_snapshot"
    )
    assert artifact["payload_json"]["manifest"] is None
    assert artifact["payload_json"]["discovery_status"] == "invalid"
    assert artifact["payload_json"]["discovery_errors"]
    assert artifact["payload_json"]["execution_allowed"] is False


@pytest.mark.parametrize("mutation", ["changed", "missing"])
def test_saved_workflow_rejects_changed_or_missing_manifest(
    client: TestClient,
    mutation: str,
) -> None:
    path = _manifest_file(client)
    manifest = next(
        item
        for item in client.get("/api/v1/advanced-providers/manifests").json()
        if item["provider_id"] == "local_depth"
    )
    project = create_project(client, f"Provider manifest {mutation}")
    run = _save_and_queue(client, project["id"], _graph(manifest["source_sha256"]))
    if mutation == "missing":
        path.unlink()
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["notes"] = ["Changed after graph save"]
        path.write_text(json.dumps(payload), encoding="utf-8")

    app = cast(FastAPI, client.app)
    assert not process_workflow_run_job(
        app.state.settings,
        app.state.session_factory,
        str(run["job_id"]),
    )
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}").json()
    assert detail["run"]["status"] == "failed"
    assert not any(
        item["data_type"] == "provider_manifest_snapshot" for item in detail["artifacts"]
    )

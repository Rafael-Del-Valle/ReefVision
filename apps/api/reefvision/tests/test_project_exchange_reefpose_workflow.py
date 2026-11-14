"""Exercise saved ReefPose workflow bindings after an integrated exchange."""

from hashlib import sha256
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models import ModelRegistration
from reefvision.jobs import video_tracking
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_reefpose_validation import freeze_fixture
from reefvision.tests.test_scientific_project_exchange import (
    export_archive,
    import_archive,
    rewrite,
)


def _execute(client: TestClient, project_id: str, graph_id: str) -> dict[str, Any]:
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs", json={"graph_record_id": graph_id}
    )
    assert queued.status_code == 202, queued.text
    run = queued.json()
    app = cast(FastAPI, client.app)
    process_workflow_run_job(app.state.settings, app.state.session_factory, run["job_id"])
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}")
    assert detail.status_code == 200, detail.text
    return cast(dict[str, Any], detail.json())


@pytest.fixture
def scored_workflow(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    endpoint, _, frozen = freeze_fixture(client, monkeypatch)
    project_id = endpoint.split("/")[-2]
    recording = frozen["manifest"]["recordings"][0]
    app = cast(FastAPI, client.app)
    settings = app.state.settings
    with app.state.session_factory() as session:
        relative_path = f"projects/{project_id}/models/fixture.pt"
        weights = resolve_managed_project_path(settings, relative_path)
        weights.parent.mkdir(parents=True, exist_ok=True)
        weights.write_bytes(b"synthetic empty prediction checkpoint")
        model = ModelRegistration(
            project_id=project_id,
            display_name="Synthetic empty pose tracker",
            purpose="detector",
            source_filename=weights.name,
            managed_path=relative_path,
            sha256=sha256(weights.read_bytes()).hexdigest(),
            file_size_bytes=weights.stat().st_size,
            framework="ultralytics",
            task="pose",
            provider_name="ultralytics",
            provider_version="fixture",
            metadata_json={
                "pose_landmark_schema": {
                    "schema_id": recording["schema_id"],
                    "schema_revision": recording["schema_revision"],
                    "content_hash": recording["schema_sha256"],
                    "expanded_labels": ["Jaw"],
                }
            },
        )
        session.add(model)
        session.commit()
        model_id = model.id

    class NoDetections:
        provider_id = "ultralytics"
        provider_version = "fixture"

        def track(self, *_paths: object, **_options: object) -> list[Any]:
            return []

    monkeypatch.setattr(
        video_tracking, "video_tracking_provider_for_name", lambda _: NoDetections()
    )
    nodes = [
        ("project", "project_source", {}),
        ("video", "project_video_source", {"video_id": recording["video_id"]}),
        ("model", "registered_model_source", {"model_id": model_id}),
        ("pose", "pose_inference", {"device": "cpu", "allow_zero_detections": True}),
        (
            "reference",
            "reefpose_reference_source",
            {"reference_id": frozen["id"], "manifest_sha256": frozen["manifest_sha256"]},
        ),
        (
            "score",
            "reefpose_scientific_validation",
            {
                "rater_id": "rater-a",
                "configurations": [
                    {
                        "definitions": [
                            {
                                "id": "gap",
                                "name": "Displacement",
                                "kind": "displacement",
                                "landmark_ids": ["jaw"],
                            }
                        ],
                        "events": [
                            {
                                "label": "gape",
                                "definition_id": "gap",
                                "unit": "pixels",
                                "open_threshold": 5,
                                "close_threshold": 2,
                            }
                        ],
                    }
                ],
            },
        ),
    ]
    connections = [
        ("project", "project", "video", "project"),
        ("project", "project", "model", "project"),
        ("video", "video", "pose", "video"),
        ("model", "model", "pose", "model"),
        ("reference", "reference", "score", "reference"),
        ("pose", "poses", "score", "zero_detections"),
    ]
    graph = {
        "graph_id": "phase6-pinned-reference",
        "name": "Pinned reference exchange",
        "nodes": [
            {"node_id": node, "node_type": kind, "parameters": parameters}
            for node, kind, parameters in nodes
        ],
        "edges": [
            {
                "edge_id": f"{source}-{target}",
                "source_node_id": source,
                "source_port_id": source_port,
                "target_node_id": target,
                "target_port_id": target_port,
            }
            for source, source_port, target, target_port in connections
        ],
    }
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    graph_id = saved.json()["id"]
    run = _execute(client, project_id, graph_id)
    assert run["run"]["status"] == "succeeded", run["run"]["error_message"]
    return {"project_id": project_id, "graph_id": graph_id, "frozen": frozen, "run": run}


def _report_artifact(run: dict[str, Any]) -> dict[str, Any]:
    return next(
        item for item in run["artifacts"] if item["data_type"] == "reefpose_validation_report"
    )


def test_pinned_workflow_and_report_artifact_reopen_after_exchange(
    client: TestClient, test_settings: Settings, scored_workflow: dict[str, Any]
) -> None:
    source = scored_workflow["project_id"]
    queued = client.post(
        f"/api/v1/projects/{source}/exchange-packages",
        json={"include_media": True, "include_model_weights": True},
    )
    assert queued.status_code == 202, queued.text
    exported = queued.json()
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        test_settings, app.state.session_factory, exported["job_id"]
    )
    archive = client.get(f"/api/v1/exchange-packages/{exported['package']['id']}/download")
    assert archive.status_code == 200, archive.text
    imported = import_archive(client, archive.content)
    assert imported.status_code == 201, imported.text
    result = imported.json()
    project_id = result["project_id"]
    mapping = result["package"]["options_json"]["id_map"]
    reopened_run = client.get(
        f"/api/v1/workflow-runs/{mapping[scored_workflow['run']['run']['id']]}"
    )
    assert reopened_run.status_code == 200, reopened_run.text
    artifact = _report_artifact(reopened_run.json())
    payload = artifact["payload_json"]
    original_payload = _report_artifact(scored_workflow["run"])["payload_json"]
    job_id = mapping[original_payload["job_id"]]
    assert payload["export_path"] == f"/projects/{project_id}/reefpose-validations/{job_id}/export"
    report = client.get(f"/api/v1{payload['export_path']}")
    assert report.status_code == 200, report.text
    assert payload["result_sha256"] == report.json()["result_sha256"]
    assert payload["input_sha256"] == report.json()["input_sha256"]
    assert artifact["payload_sha256"] == canonical_json_sha256(payload)
    pinned_node = next(
        node for node in reopened_run.json()["nodes"] if node["node_id"] == "reference"
    )
    frozen_id = mapping[scored_workflow["frozen"]["id"]]
    reference = client.get(f"/api/v1/projects/{project_id}/reefpose-references/{frozen_id}")
    assert reference.status_code == 200, reference.text
    assert pinned_node["parameters_json"]["manifest_sha256"] == reference.json()["manifest_sha256"]
    replay = _execute(client, project_id, mapping[scored_workflow["graph_id"]])
    assert replay["run"]["status"] == "succeeded", replay["run"]["error_message"]


def test_exchange_inspection_rejects_rehashed_inconsistent_event_totals(
    client: TestClient, test_settings: Settings, scored_workflow: dict[str, Any]
) -> None:
    archive = export_archive(client, test_settings, scored_workflow["project_id"])

    def contradict_events(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        job = next(row for row in sections["jobs"] if row["job_type"] == "reefpose_validation")
        report = job["result_json"]
        report["sensitivity"][0]["complete"].update(tp=777, fn=0, fp=0, f1=1)
        report.pop("result_sha256")
        report["result_sha256"] = canonical_json_sha256(report)

    damaged = rewrite(archive, contradict_events)
    inspected = client.post(
        "/api/v1/exchange-packages/inspect", files={"file": ("inconsistent.zip", damaged)}
    )
    assert inspected.status_code == 200, inspected.text
    assert not inspected.json()["compatible"]
    assert "event" in " ".join(inspected.json()["errors"]).lower()
    assert import_archive(client, damaged).status_code == 400

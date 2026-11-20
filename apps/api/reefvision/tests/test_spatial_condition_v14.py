from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project

_RUBRIC = {
    "rubric_id": "condition-fixture",
    "version": "fixture-v1",
    "reference": "Synthetic rubric for software acceptance",
    "observation_unit": "fixture specimen",
    "labels": ["fixture-alpha", "fixture-beta"],
}
_OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


def _asset(client: TestClient) -> tuple[str, str, dict]:
    project_id = str(create_project(client, "Condition acceptance")["id"])
    root = f"/api/v1/projects/{project_id}/spatial/assets"
    response = client.post(root, files={"file": ("sample.obj", _OBJ, "text/plain")})
    assert response.status_code == 201, response.text
    asset = response.json()
    return project_id, f"{root}/{asset['id']}", asset


def _observation(asset: dict, **changes: object) -> dict:
    return {
        "rubric": _RUBRIC,
        "source_sha256": asset["sha256"],
        "metadata_revision_id": None,
        "observation_unit_id": "synthetic-specimen-1",
        "reference_evidence": "Fixture evidence F1",
        "observer_id": "Fixture observer",
        "observed_at_utc": "2026-01-01T00:00:00Z",
        "label": "fixture-alpha",
        "uncertainty": "Fixture visibility is partial",
        **changes,
    }


def _decision(**changes: object) -> dict:
    return {
        "actor_id": "Fixture reviewer",
        "decision": "disagree",
        "label": "fixture-beta",
        "reference_evidence": "Independent fixture evidence F2",
        "decided_at_utc": "2026-01-02T00:00:00Z",
        "uncertainty": "Single fixture view",
        **changes,
    }


def test_condition_preserves_independent_disagreement_and_adjudication(client: TestClient) -> None:
    _, asset_path, asset = _asset(client)
    scope = f"{asset_path}/condition-observations"
    created = client.post(scope, json=_observation(asset))
    assert created.status_code == 201, created.text
    observed = created.json()
    assert observed["phase"] == "observation"
    assert observed["resolved_label"] is None
    assertion = f"{scope}/{observed['id']}/decisions"
    same_person = client.post(assertion, json=_decision(actor_id="fixture OBSERVER"))
    assert same_person.status_code == 400, same_person.text
    decided = client.post(assertion, json=_decision())
    assert decided.status_code == 201, decided.text
    disputed = decided.json()
    assert disputed["phase"] == "review"
    assert disputed["previous_revision_id"] == observed["id"]
    assert disputed["decision"]["decision"] == "disagree"
    assert disputed["resolved_label"] is None
    assert client.post(assertion, json=_decision(decision="agree", label=None)).status_code == 409
    response = client.post(
        f"{scope}/{disputed['id']}/decisions",
        json=_decision(
            actor_id="Fixture adjudicator",
            decision="adjudicated",
            decided_at_utc="2026-01-03T00:00:00Z",
        ),
    )
    assert response.status_code == 201, response.text
    adjudicated = response.json()
    assert adjudicated["observation_id"] == observed["id"]
    assert adjudicated["resolved_label"] == "fixture-beta"
    assert adjudicated["reviewer_authenticated"] is False
    assert adjudicated["scientifically_verified"] is False
    reopened = client.get(scope).json()
    assert [item["id"] for item in reopened] == [observed["id"], disputed["id"], adjudicated["id"]]
    exported = client.get(f"{scope}/{adjudicated['id']}/report")
    assert exported.status_code == 200, exported.text
    assert exported.json()["revisions"] == reopened
    assert exported.json()["revisions"][0]["observation"]["rubric"] == _RUBRIC


def test_condition_requires_declared_evidence_and_freezes_rubric_version(
    client: TestClient,
) -> None:
    _, asset_path, asset = _asset(client)
    scope = f"{asset_path}/condition-observations"
    missing = client.post(scope, json=_observation(asset, reference_evidence=" "))
    assert missing.status_code == 422, missing.text
    mismatched = client.post(scope, json=_observation(asset, source_sha256="0" * 64))
    assert mismatched.status_code == 400, mismatched.text
    assert client.post(scope, json=_observation(asset)).status_code == 201
    edited = _RUBRIC | {"reference": "A changed declaration"}
    assert client.post(scope, json=_observation(asset, rubric=edited)).status_code == 409
    revised = edited | {"version": "fixture-v2"}
    assert client.post(scope, json=_observation(asset, rubric=revised)).status_code == 201


def test_new_metadata_makes_existing_condition_unavailable_for_review(client: TestClient) -> None:
    _, asset_path, asset = _asset(client)
    scope = f"{asset_path}/condition-observations"
    response = client.post(scope, json=_observation(asset))
    assert response.status_code == 201, response.text
    observed = response.json()
    metadata = client.post(
        f"{asset_path}/metadata-revisions",
        json={
            "coordinate_unit": "unitless",
            "coordinate_frame_id": "fixture-frame",
            "created_by_identity": "fixture-operator",
        },
    )
    assert metadata.status_code == 201, metadata.text
    stale = client.get(f"{scope}/{observed['id']}")
    assert stale.json()["stale_source_metadata"] is True
    assert client.post(f"{scope}/{observed['id']}/decisions", json=_decision()).status_code == 409
    assert client.post(scope, json=_observation(asset)).status_code == 409
    assert (
        client.post(
            scope, json=_observation(asset, metadata_revision_id=metadata.json()["id"])
        ).status_code
        == 201
    )


def test_saved_condition_workflow_replays_the_report_and_rejects_stale_metadata(
    client: TestClient,
) -> None:
    project_id, asset_path, asset = _asset(client)
    scope = f"{asset_path}/condition-observations"
    first = client.post(scope, json=_observation(asset)).json()
    accepted = client.post(
        f"{scope}/{first['id']}/decisions", json=_decision(decision="agree", label=None)
    )
    assert accepted.status_code == 201, accepted.text
    revision_id = accepted.json()["id"]
    report = client.get(f"{scope}/{revision_id}/report").json()
    graph = {
        "graph_id": "synthetic-condition-report",
        "name": "Review receipt replay",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "condition",
                "node_type": "spatial_condition_report",
                "parameters": {"asset_id": asset["id"], "revision_id": revision_id},
            },
        ],
        "edges": [
            {
                "edge_id": "project-condition",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "condition",
                "target_port_id": "project",
            }
        ],
    }
    base = f"/api/v1/projects/{project_id}"
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)

    def run_graph() -> dict:
        queued = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert queued.status_code == 202, queued.text
        job = queued.json()
        process_workflow_run_job(app.state.settings, app.state.session_factory, job["job_id"])
        return client.get(f"/api/v1/workflow-runs/{job['id']}").json()

    for detail in (run_graph(), run_graph()):
        assert detail["run"]["status"] == "succeeded", detail
        assert [
            item["payload_json"]
            for item in detail["artifacts"]
            if item["data_type"] == "spatial_condition_report"
        ] == [report]

    changed = client.post(
        f"{asset_path}/metadata-revisions",
        json={"coordinate_unit": "unitless", "created_by_identity": "fixture-operator"},
    )
    assert changed.status_code == 201, changed.text
    stale = run_graph()
    assert stale["run"]["status"] == "failed", stale
    assert not any(item["data_type"] == "spatial_condition_report" for item in stale["artifacts"])


def test_project_exchange_preserves_condition_chain_and_literal_reference(
    client: TestClient,
) -> None:
    project_id, asset_path, asset = _asset(client)
    scope = f"{asset_path}/condition-observations"
    metadata = client.post(
        f"{asset_path}/metadata-revisions",
        json={"coordinate_unit": "unitless", "created_by_identity": "fixture-operator"},
    )
    assert metadata.status_code == 201, metadata.text
    metadata_id = metadata.json()["id"]
    observation = _observation(
        asset,
        reference_evidence=asset["id"],
        metadata_revision_id=metadata_id,
    )
    recorded = client.post(scope, json=observation)
    assert recorded.status_code == 201, recorded.text
    first = recorded.json()
    accepted = client.post(
        f"{scope}/{first['id']}/decisions", json=_decision(decision="agree", label=None)
    )
    assert accepted.status_code == 201, accepted.text
    api = f"/api/v1/projects/{project_id}"
    request = client.post(
        f"{api}/exchange-packages", json={"include_media": True, "notes": "condition fixture"}
    )
    assert request.status_code == 202, request.text
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        app.state.settings, app.state.session_factory, request.json()["job_id"]
    )
    package_id = request.json()["package"]["id"]
    archive = client.get(f"/api/v1/exchange-packages/{package_id}/download")
    assert archive.status_code == 200, archive.text
    imported = client.post(
        "/api/v1/exchange-packages/import",
        files={"file": ("condition.reefvision.zip", archive.content, "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    restored_project_id = imported.json()["project_id"]
    restored_scope = f"/api/v1/projects/{restored_project_id}/spatial/assets"
    [restored_asset] = client.get(restored_scope).json()
    reopened = client.get(f"{restored_scope}/{restored_asset['id']}/condition-observations")
    assert reopened.status_code == 200, reopened.text
    reopened_observation, reopened_review = reopened.json()
    assert reopened_observation["id"] != first["id"]
    assert reopened_observation["observation"]["metadata_revision_id"] != metadata_id
    assert reopened_observation["observation"]["reference_evidence"] == asset["id"]
    assert reopened_observation["observation"]["source_sha256"] == asset["sha256"]
    assert reopened_observation["observation"]["rubric"] == _RUBRIC
    assert reopened_observation["stale_source_metadata"] is False
    assert reopened_review["observation_id"] == reopened_observation["id"]
    assert reopened_review["previous_revision_id"] == reopened_observation["id"]
    assert reopened_review["decision"] == accepted.json()["decision"]
    assert reopened_review["resolved_label"] == "fixture-alpha"

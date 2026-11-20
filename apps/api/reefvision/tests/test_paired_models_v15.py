from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.paired_models_v15 import process_comparison, summarize_groups
from reefvision.tests.test_model_comparison_stills_v15 import (
    _confirm_runtime,
    _dataset,
    _register,
)
from reefvision.tests.test_model_comparison_stills_v15 import (
    reviewed_runtime as reviewed_runtime_fixture,
)
from reefvision.tests.test_model_comparison_video_v15 import VideoFixture
from reefvision.tests.test_model_comparison_video_v15 import video_comparison as video_fixture

reviewed_runtime = reviewed_runtime_fixture
video_comparison = video_fixture


def sample(left: float | None, right: float | None) -> dict:
    return {
        "media_kind": "image",
        "media_id": str(uuid4()),
        "metrics": [{"name": "count error", "unit": "objects/image", "left": left, "right": right}],
    }


def test_independent_units_weight_equally_and_missing_pairs_stay_excluded() -> None:
    groups = [
        {"group_id": "tank-a", "observations": [sample(0, 2), sample(2, 6), sample(5, None)]},
        {"group_id": "tank-b", "observations": [sample(4, 2)]},
    ]
    summary = summarize_groups(groups)
    value = summary["metrics"][0]
    assert value["left"] == 2.5 and value["right"] == 3
    assert value["right_minus_left"] == 0.5
    assert value["groups"] == 2 and value["paired_observations"] == 3
    assert value["missing_pairs"] == 1
    assert [g["group_id"] for g in summary["per_group"]] == ["tank-a", "tank-b"]


def test_all_unsupported_and_duplicate_units_do_not_yield_statistics() -> None:
    one = {"group_id": "tank-a", "observations": [sample(None, 5)]}
    with pytest.raises(ValidationError, match=r"paired|support"):
        summarize_groups([one])
    with pytest.raises(ValidationError, match="group"):
        summarize_groups([one, one])


def test_queued_comparison_reopens_exports_and_recomputes_twice(
    client: TestClient,
    reviewed_runtime: None,
) -> None:
    app = cast(FastAPI, client.app)
    project, class_id, _, dataset = _dataset(client)
    models = [
        _register(client, project, dataset, class_id, "detect", label)
        for label in ("left", "right")
    ]
    pins = [_confirm_runtime(client, project, model) for model in models]
    base = f"/api/v1/projects/{project}"
    url = base + "/paired-model-comparisons"
    choices = client.get(url + "/sources", params={"task": "detector"}).json()
    source = next(s for s in choices if s["id"] == dataset["id"])
    left, right = [
        {"id": p["runtime_selection_id"], "sha256": p["runtime_selection_sha256"]} for p in pins
    ]
    payload = {
        "task": "detector",
        "left": left,
        "right": right,
        "sources": [{"id": source["id"], "sha256": source["sha256"]}],
    }
    rejected = client.post(url, json={**payload, "right": left})
    assert rejected.status_code == 422
    submitted = client.post(url, json=payload)
    assert submitted.status_code == 202, submitted.text
    assert submitted.json()["created_at"].endswith("Z")
    jid = submitted.json()["id"]
    assert process_comparison(app.state.settings, app.state.session_factory, jid)
    assert not process_comparison(app.state.settings, app.state.session_factory, jid)
    job = client.get(url + "/" + jid).json()
    assert job["status"] == "succeeded", job["error_message"]
    report = client.get(url + "/" + jid + "/export").json()
    assert report == job["result_json"]
    assert report["snapshot"]["evidence"]["evaluation_status"] == "held_out"
    assert report["snapshot"]["summary"]["group_count"] == 2
    assert any(m["right_minus_left"] for m in report["snapshot"]["summary"]["metrics"])
    assert report["content_sha256"] in client.get(url + "/" + jid + "/export?format=csv").text
    assert client.get(url, params={"completed_only": True}).json()[0]["id"] == jid
    graph = {
        "graph_id": "paired-models",
        "name": "Paired models",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "scores",
                "node_type": "paired_model_comparison",
                "parameters": {"comparison_id": jid, "comparison_sha256": report["content_sha256"]},
            },
        ],
        "edges": [
            {
                "edge_id": "scope",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "scores",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(base + "/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    hashes = []
    for _ in range(2):
        started = client.post(base + "/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert started.status_code in (200, 201, 202), started.text
        run = started.json()
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, run["job_id"]
        )
        outcome = client.get("/api/v1/workflow-runs/" + run["id"]).json()
        assert outcome["run"]["status"] == "succeeded", outcome
        artifact = next(a for a in outcome["artifacts"] if a["data_type"] == "paired_model_report")
        assert artifact["payload_json"]["snapshot"] == report["snapshot"]
        hashes.append(artifact["payload_sha256"])
    assert hashes[0] == hashes[1]
    queued = client.post(url, json=payload).json()
    from reefvision.storage.projects import resolve_managed_project_path

    resolve_managed_project_path(app.state.settings, models[0].managed_path).write_bytes(b"changed")
    process_comparison(app.state.settings, app.state.session_factory, queued["id"])
    failed = client.get(url + "/" + queued["id"]).json()
    assert failed["status"] == "failed" and "checkpoint" in failed["error_message"].lower()
    assert client.get(url + "/" + jid + "/export").json() == report


def test_completed_video_scores_enter_through_the_same_workspace(
    client: TestClient,
    video_comparison: VideoFixture,
    reviewed_runtime: None,
) -> None:
    app, project, jobs, models, reference_sha = video_comparison
    path = f"/api/v1/projects/{project}/paired-model-comparisons"
    with app.state.session_factory() as session:
        pins = []
        for identifier in models:
            model = session.get(ModelRegistration, identifier)
            assert model is not None
            pin = _confirm_runtime(client, project, model)
            pins.append(
                {"id": pin["runtime_selection_id"], "sha256": pin["runtime_selection_sha256"]}
            )
    for task in ("pose", "tracking", "event"):
        options = client.get(path + "/sources", params={"task": task})
        assert options.status_code == 200, options.text
        by_id = {row["id"]: row["sha256"] for row in options.json()}
        req = {
            "task": task,
            "left": pins[0],
            "right": pins[1],
            "sources": [{"id": identifier, "sha256": by_id[identifier]} for identifier in jobs],
        }
        response = client.post(path, json=req)
        assert response.status_code == 202, response.text
        job = response.json()["id"]
        process_comparison(app.state.settings, app.state.session_factory, job)
        result = client.get(path + "/" + job).json()
        assert result["status"] == "succeeded", result["error_message"]
        snapshot = result["result_json"]["snapshot"]
        assert snapshot["evidence"]["reference_sha256"] == reference_sha
        assert snapshot["summary"]["group_count"] == 2
        assert all(
            obs["media_kind"] == "video"
            for g in snapshot["evidence"]["groups"]
            for obs in g["observations"]
        )

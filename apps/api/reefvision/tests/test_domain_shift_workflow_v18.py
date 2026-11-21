from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import Job, PredictionProposal, Project
from reefvision.db.models.image_adjustment import ImageAdjustmentRecipe
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.domain_shift_v18 import DomainShiftDraft
from reefvision.services.domain_shift_metrics_v18 import summarize_domain_shift
from reefvision.services.domain_shift_v18 import process_domain_shift
from reefvision.services.paired_models_v15 import process_comparison
from reefvision.services.project_exchange import _row
from reefvision.services.project_exchange_domain_shift_v18 import validate_domain_shift_exchange
from reefvision.services.project_exchange_v1 import ProjectExchangeV1Service
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_model_comparison_stills_v15 import _confirm_runtime, _dataset, _register
from reefvision.tests.test_model_comparison_stills_v15 import reviewed_runtime as reviewed_runtime


def test_domain_shift_uses_pinned_adjustments_and_replays_with_groups(
    client: TestClient,
    reviewed_runtime: None,
) -> None:
    app = cast(FastAPI, client.app)
    settings, factory = app.state.settings, app.state.session_factory
    project, class_id, images, frozen = _dataset(client)
    root = f"/api/v1/projects/{project}"
    picks = [
        _confirm_runtime(
            client, project, _register(client, project, frozen, class_id, "detect", name)
        )
        for name in ("left", "right")
    ]
    baseline = client.post(
        root + "/paired-model-comparisons",
        json={
            "task": "detector",
            "left": {
                "id": picks[0]["runtime_selection_id"],
                "sha256": picks[0]["runtime_selection_sha256"],
            },
            "right": {
                "id": picks[1]["runtime_selection_id"],
                "sha256": picks[1]["runtime_selection_sha256"],
            },
            "sources": [{"id": frozen["id"], "sha256": frozen["manifest_sha256"]}],
        },
    )
    assert baseline.status_code == 202, baseline.text
    baseline_id = baseline.json()["id"]
    assert process_comparison(settings, factory, baseline_id)
    previous = client.get(root + "/paired-model-comparisons/" + baseline_id).json()["result_json"]
    domain = root + "/domain-shift"
    pins = []
    for key in ("first", "second", "blank"):
        image_id = images[key]
        url = f"/api/v1/images/{image_id}"
        original = client.get(url).json()["sha256"]
        saved = client.post(
            url + "/adjustments",
            json={"original_sha256": original, "parameters": {"red_gain_percent": 125}},
        )
        assert saved.status_code == 201, saved.text
        row = saved.json()
        pins.append(
            {
                "image_id": image_id,
                "recipe_id": row["id"],
                "content_sha256": row["content_sha256"],
                "original_sha256": original,
                "rendition_sha256": row["receipt"]["rendition_sha256"],
            }
        )
    study = {
        "comparison_id": baseline_id,
        "comparison_sha256": previous["content_sha256"],
        "independent_unit": "Tank",
        "reference": {"label": "Clear water", "groups": ["held-out-tank-a"]},
        "target": {"label": "Turbid", "groups": ["held-out-tank-b", "Unobserved tank"]},
        "preprocessing": "adjusted",
        "adjustments": pins,
    }
    stale = client.post(domain, json={**study, "comparison_sha256": "0" * 64})
    assert stale.status_code == 409
    submitted = client.post(domain, json=study)
    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()["id"]
    assert process_domain_shift(settings, factory, job_id)
    reopened = client.get(f"{domain}/{job_id}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "succeeded", reopened.text
    report = reopened.json()["result_json"]
    snapshot = report["snapshot"]
    assert snapshot["summary"]["status"] == "scored"
    assert snapshot["summary"]["lineage"] == "held_out"
    assert any(row["status"] == "missing" for row in snapshot["summary"]["groups"])
    assert {row["status"] for row in snapshot["summary"]["groups"]} == {"included", "missing"}
    assert snapshot["reference"]["manifest_sha256"] == frozen["manifest_sha256"]
    assert snapshot["declaration"]["adjustments"] == pins
    assert len(snapshot["observed_evidence"]["inference_job_ids"]) == 6
    with factory() as session:
        child_jobs = [
            session.get(Job, item) for item in snapshot["observed_evidence"]["inference_job_ids"]
        ]
        assert all(child.request_json["evaluation_only"] is True for child in child_jobs)
        assert {child.result_json["model_input"]["rendition_sha256"] for child in child_jobs} == {
            item["rendition_sha256"] for item in pins
        }
        proposals = session.scalars(
            select(PredictionProposal).where(
                PredictionProposal.inference_job_id.in_([child.id for child in child_jobs])
            )
        ).all()
        assert proposals and all(item.review_status == "evaluation_only" for item in proposals)

    graph = {
        "graph_id": "domain-report-test",
        "name": "Frozen domain shift",
        "nodes": [
            {"node_id": "p", "node_type": "project_source"},
            {
                "node_id": "d",
                "node_type": "domain_shift_report",
                "parameters": {"report_id": job_id, "content_sha256": report["content_sha256"]},
            },
        ],
        "edges": [
            {
                "edge_id": "bound",
                "source_node_id": "p",
                "source_port_id": "project",
                "target_node_id": "d",
                "target_port_id": "project",
            }
        ],
    }
    saved_graph = client.post(root + "/workflow-graphs", json={"graph": graph})
    assert saved_graph.status_code == 201, saved_graph.text
    artifacts: list[dict[str, Any]] = []
    for _ in range(2):
        queued = client.post(
            root + "/workflow-runs", json={"graph_record_id": saved_graph.json()["id"]}
        )
        assert queued.status_code == 202
        run = queued.json()
        assert process_workflow_run_job(settings, factory, run["job_id"])
        detail = client.get("/api/v1/workflow-runs/" + run["id"]).json()
        assert detail["run"]["status"] == "succeeded", detail
        artifacts.append(
            next(row for row in detail["artifacts"] if row["data_type"] == "domain_shift_report")
        )
    assert artifacts[0]["payload_sha256"] == artifacts[1]["payload_sha256"]
    assert artifacts[0]["payload_json"] == report
    assert client.get(f"{domain}/{job_id}/report").json() == report
    assert "target,Unobserved tank,missing" in client.get(f"{domain}/{job_id}/groups.csv").text

    with factory() as session:
        session.add(
            Job(
                project_id=project,
                job_type="learning_evaluation",
                status="succeeded",
                completed_at=datetime.now(UTC),
                request_json={
                    "candidate_model_id": picks[0]["model_id"],
                    "dataset_version_id": frozen["id"],
                    "split": "test",
                },
            )
        )
        session.commit()
    overlap = client.post(
        domain, json={**study, "preprocessing": "original", "adjustments": []}
    ).json()["id"]
    assert process_domain_shift(settings, factory, overlap)
    withhold = client.get(f"{domain}/{overlap}").json()["result_json"]["snapshot"]["summary"]
    assert withhold["lineage"] == "overlap" and withhold["metrics"] == []

    with factory() as session:
        records = ProjectExchangeV1Service(session, settings)._records(
            session.get_one(Project, project)
        )
        records["image_adjustment_recipes"] = session.scalars(
            select(ImageAdjustmentRecipe).where(ImageAdjustmentRecipe.project_id == project)
        ).all()
        sections = {name: [_row(row) for row in rows] for name, rows in records.items()}
    validate_domain_shift_exchange(project, sections, {})

    def archived_report(rows: dict[str, Any], target: str) -> dict[str, Any]:
        return next(row["result_json"] for row in rows["jobs"] if row["id"] == target)

    forged = deepcopy(sections)
    changed = archived_report(forged, job_id)
    body = changed["snapshot"]
    body["observed_evidence"]["groups"][0]["observations"][0]["metrics"][0]["left"] = 42.0
    body["summary"] = summarize_domain_shift(
        DomainShiftDraft.model_validate(body["declaration"]),
        body["observed_evidence"]["groups"],
        "held_out",
    )
    changed["content_sha256"] = canonical_json_sha256(body)
    with pytest.raises(ValidationError, match="scores no longer match"):
        validate_domain_shift_exchange(project, forged, {})

    foreign = deepcopy(sections)
    children = snapshot["observed_evidence"]["inference_job_ids"]
    child = next(row for row in foreign["jobs"] if row["id"] == children[0])
    child["request_json"]["paired_owner_run_id"] = baseline_id
    with pytest.raises(ValidationError, match="belongs to a different domain report"):
        validate_domain_shift_exchange(project, foreign, {})

    artifact_rows = deepcopy(sections)
    artifact = next(
        row
        for row in artifact_rows["workflow_artifacts"]
        if row["data_type"] == "domain_shift_report"
    )
    artifact["payload_json"]["snapshot"]["reference"]["split"] = "train"
    artifact["payload_sha256"] = canonical_json_sha256(artifact["payload_json"])
    with pytest.raises(
        ValidationError, match="workflow does not produce its declared frozen report"
    ):
        validate_domain_shift_exchange(project, artifact_rows, {})

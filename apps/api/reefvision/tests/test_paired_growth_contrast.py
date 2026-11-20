from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_reviewed_growth_sampling_1_3 import _growth_sources


def _study(client: TestClient) -> tuple[str, str, dict[str, Any], dict[str, str]]:
    project = create_project(client, "Paired calibrated study")
    project_id = str(project["id"])
    ecology = f"/api/v1/projects/{project_id}/ecology"
    roster = {
        "Tank-1": ["a-left", "a-right", "b"],
        "Tank-2": ["c"],
        "Tank-3": ["d"],
        "Tank-4": ["e", "f"],
    }

    def register(organism: str, tank: str, kind: str, parent: str | None = None) -> None:
        response = client.post(
            f"{ecology}/organisms",
            json={
                "organism_key": organism,
                "experimental_unit_type": "tank",
                "experimental_unit_id": tank,
                "kind": kind,
                "parent_colony_key": parent,
                "reason": "Reviewed fixture sampling roster",
            },
        )
        assert response.status_code == 201, response.text

    register("a", "Tank-1", "colony")
    for tank, organisms in roster.items():
        for organism in organisms:
            parent = "a" if organism.startswith("a-") else f"parent-{organism}"
            if parent != "a":
                register(parent, tank, "colony")
            register(organism, tank, "fragment", parent)

    widths = {
        "a-left": [(1, 10), (2, 14)],
        "a-right": [(1, 12), (2, 24)],
        "b": [(1, 16), (2, 32)],
        "c": [(1, 21), (2, 41)],
        "d": [(1, 23), (2, 51)],
        "e": [(1, 25), (2, 53)],
    }
    sources = [
        row
        for organism, visits in widths.items()
        for row in _growth_sources(client, project, organism, visits)
    ]
    sources[-1]["exclusion_reason"] = "Glare obscured follow-up boundary"
    path = f"{ecology}/verified-analyses"
    response = client.post(
        path,
        json={
            "selection": {
                "kind": "growth",
                "metric": "box_width",
                "sources": sources,
                "sampling_plan": [
                    {
                        "experimental_unit_id": tank,
                        "organism_keys": organisms,
                        "dates": ["2026-11-01", "2026-11-02", "2026-11-03"],
                    }
                    for tank, organisms in roster.items()
                ],
            },
            "reviewed_by": "Fixture reviewer",
            "review_note": "Reviewed the roster, observations and omissions.",
            "confirm_reviewed_selection": True,
        },
    )
    assert response.status_code == 201, response.text
    analysis = response.json()
    return (
        project_id,
        f"{path}/{analysis['id']}/paired-contrast",
        analysis,
        {
            "source_sha256": analysis["content_sha256"],
            "baseline_date": "2026-11-01",
            "followup_date": "2026-11-02",
            "experimental_unit_type": "tank",
            "estimand": "Mean change in the declared independent tanks with both visits complete.",
            "missingness_policy": "complete_unit",
        },
    )


def test_paired_growth_known_answer_and_two_saved_replays(client: TestClient) -> None:
    project_id, url, analysis, design = _study(client)
    response = client.post(url, json=design)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["analysis_id"] == analysis["id"]
    assert report["source_sha256"] == analysis["content_sha256"]
    assert report["planned_unit_count"] == 4
    assert report["included_unit_count"] == 3
    assert report["metric"] == "box_width"
    assert report["unit"] == "mm"
    assert report["mean_difference"] == pytest.approx(5.0)
    assert report["standard_error"] == pytest.approx(2 / 3**0.5)
    assert report["degrees_of_freedom"] == 2
    pytest.importorskip("scipy")
    assert report["confidence_interval_95"] == pytest.approx([0.031724576, 9.968275424])
    assert [unit["difference"] for unit in report["units"][:3]] == pytest.approx([3, 5, 7])
    assert [pair["difference"] for pair in report["units"][0]["organisms"]] == [1, 3, 4]
    unavailable = report["units"][3]
    assert unavailable["status"] == "excluded"
    assert unavailable["reason"] == "incomplete_unit"
    assert unavailable["difference"] is None
    assert unavailable["organisms"][0]["baseline_source_record_id"]
    assert unavailable["organisms"][0]["followup_source_record_id"] is None
    assert unavailable["organisms"][1]["reason"] == "missing_both_visits"
    assert any(
        row["reason"] == "Glare obscured follow-up boundary" for row in report["source_exclusions"]
    )
    assert report["report_sha256"] == canonical_json_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )

    workflow = {
        "graph_id": "paired-growth-known-pairs",
        "name": "Paired calibrated tank contrast",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "paired",
                "node_type": "paired_growth_contrast",
                "parameters": {"analysis_id": analysis["id"], **design},
            },
        ],
        "edges": [
            {
                "edge_id": "project-paired",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "paired",
                "target_port_id": "project",
            }
        ],
    }
    graphs = f"/api/v1/projects/{project_id}/workflow-graphs"
    saved = client.post(graphs, json={"graph": workflow, "create_new_revision": True})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    for _ in range(2):
        queued = client.post(
            f"/api/v1/projects/{project_id}/workflow-runs",
            json={"graph_record_id": saved.json()["id"]},
        )
        assert queued.status_code == 202, queued.text
        process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}").json()
        assert detail["run"]["status"] == "succeeded", detail
        assert (
            next(
                row["payload_json"]
                for row in detail["artifacts"]
                if row["data_type"] == "paired_growth_contrast"
            )
            == report
        )


def test_paired_growth_rejects_invalid_design_and_excludes_absent_visits(
    client: TestClient,
) -> None:
    project_id, url, analysis, design = _study(client)
    for change, status in [
        ({"source_sha256": "0" * 64}, 409),
        ({"baseline_date": "2026-11-02"}, 422),
        ({"followup_date": "2026-11-04"}, 400),
        ({"baseline_date": 1793491200}, 422),
        ({"experimental_unit_type": "colony"}, 400),
        ({"experimental_unit_type": "videoFrame"}, 422),
        ({"missingness_policy": "zero"}, 422),
        ({"organism_ids": ["a-left"]}, 422),
    ]:
        result = client.post(url, json={**design, **change})
        assert result.status_code == status, result.text
    foreign = create_project(client, "Unrelated")
    assert client.post(url.replace(project_id, foreign["id"]), json=design).status_code == 404

    no_followup = client.post(url, json={**design, "followup_date": "2026-11-03"})
    assert no_followup.status_code == 200, no_followup.text
    empty = no_followup.json()
    assert empty["included_unit_count"] == 0
    for statistic in (
        "mean_difference",
        "standard_error",
        "degrees_of_freedom",
        "confidence_interval_95",
    ):
        assert empty[statistic] is None
    assert all(unit["status"] == "excluded" for unit in empty["units"])

    changed = client.post(
        f"/api/v1/projects/{project_id}/ecology/organisms/f/revisions",
        json={
            "expected_revision": 1,
            "kind": "fragment",
            "parent_colony_key": "parent-f",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "Tank-4",
            "reason": "Recorded a changed planned roster membership",
        },
    )
    assert changed.status_code == 201, changed.text
    stale = client.post(url, json=design)
    assert stale.status_code == 409, stale.text
    reopened = client.get(url.removesuffix("/paired-contrast")).json()
    assert reopened["stale"]
    assert reopened["snapshot"] == analysis["snapshot"]

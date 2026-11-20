from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_paired_growth_contrast import (
    _revise_planned_identity,
    _run_graph,
    _study,
)


def _path(project: str) -> str:
    return f"/api/v1/projects/{project}/ecology/study-designs"


def _declaration(timing: str = "retrospective") -> dict[str, Any]:
    return {
        "title": "Paired tank census",
        "timing": timing,
        "reviewed_by": "Study fixture reviewer",
        "review_note": "Reviewed treatment allocation, tank nesting and visits.",
        "confirm_review": True,
        "contrast": {
            "baseline_date": "2026-11-01",
            "followup_date": "2026-11-02",
            "experimental_unit_type": "tank",
            "estimand": "Mean change for the declared tanks with both visits complete.",
            "missingness_policy": "complete_unit",
        },
        "metric": "box_width",
        "method": "paired_growth_contrast",
        "nesting": "parent_colony_within_unit",
        "exclusion_policy": "reviewed_source_exclusions",
        "exclusion_rule": "Exclude a source when glare prevents a boundary review.",
        "organism_keys": ["a-left", "a-right", "b", "c", "d", "e", "f"],
        "treatments": [
            {"code": "reference", "label": "Reference tank"},
            {"code": "comparison", "label": "Comparison tank"},
        ],
    }


def _source(analysis: dict[str, Any]) -> dict[str, str]:
    return {
        "growth_analysis_id": analysis["id"],
        "growth_source_sha256": analysis["content_sha256"],
    }


def _freeze(client: TestClient, project: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(_path(project), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_retrospective_design_reopens_exports_and_replays_twice(client: TestClient) -> None:
    project, _, analysis, _ = _study(client, reviewed_assignments=True)
    path = _path(project)
    record = _freeze(client, project, {"declaration": _declaration(), **_source(analysis)})
    assert record["revision"] == 1
    snapshot = record["snapshot"]
    assert snapshot["project_id"] == project
    assert snapshot["declaration"]["timing"] == "retrospective"
    assert len(snapshot["roster"]) == 7
    assert snapshot["roster"][0]["assignment"]["treatment_code"] == "reference"
    assert snapshot["roster"][0]["parent_colony_key"] == "a"
    assert snapshot["binding"]["paired_report"]["mean_difference"] == pytest.approx(5.0)
    exclusions = snapshot["binding"]["paired_report"]["source_exclusions"]
    assert any(row["reason"] == "Glare obscured follow-up boundary" for row in exclusions)
    assert canonical_json_sha256(snapshot) == record["content_sha256"]
    assert client.get(path).json()["items"] == [record]
    assert client.get(f"{path}/{record['id']}").json() == record
    export = client.get(f"{path}/{record['id']}/design.json")
    assert export.json() == snapshot
    assert export.headers["X-ReefVision-Content-SHA256"] == record["content_sha256"]

    graph = {
        "graph_id": "known-study-design",
        "name": "Replay tank design",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "study",
                "node_type": "reviewed_study_design",
                "parameters": {
                    "design_revision_id": record["id"],
                    "design_sha256": record["content_sha256"],
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-study",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "study",
                "target_port_id": "project",
            },
        ],
    }
    graph_path = f"/api/v1/projects/{project}/workflow-graphs"
    saved = client.post(graph_path, json={"graph": graph, "create_new_revision": True})
    assert saved.status_code == 201, saved.text
    graph_id = saved.json()["id"]

    newer = _freeze(
        client,
        project,
        {
            "declaration": {**_declaration(), "title": "Revised reviewer label"},
            **_source(analysis),
            "supersedes_revision_id": record["id"],
            "supersedes_sha256": record["content_sha256"],
        },
    )
    assert newer["design_id"] == record["design_id"]
    assert newer["revision"] == 2
    assert newer["content_sha256"] != record["content_sha256"]

    for _ in range(2):
        run = _run_graph(client, project, graph_id)
        assert run["run"]["status"] == "succeeded", run
        receipt = next(
            row["payload_json"]
            for row in run["artifacts"]
            if row["data_type"] == "study_design_report"
        )
        assert receipt == {"content_sha256": record["content_sha256"], "snapshot": snapshot}

    _revise_planned_identity(client, project)
    stale = _run_graph(client, project, graph_id)
    assert stale["run"]["status"] == "failed", stale
    assert "identity revision changed" in stale["run"]["error_message"]
    assert client.get(f"{path}/{record['id']}/design.json").json() == snapshot


def test_prospective_freeze_then_evidence_binding_is_a_new_revision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reefvision.services import study_design

    def freeze_before_observations(project: str) -> None:
        with monkeypatch.context() as clock:
            clock.setattr(study_design, "utc_now", lambda: datetime(2026, 10, 31, tzinfo=UTC))
            prospect.update(_freeze(client, project, {"declaration": _declaration("prospective")}))

    prospect: dict[str, Any] = {}
    project, _, analysis, _ = _study(
        client, reviewed_assignments=True, before_observations=freeze_before_observations
    )
    path = _path(project)
    assert prospect["snapshot"]["binding"] is None
    assert prospect["snapshot"]["declared_at"].startswith("2026-10-31")
    bind = f"{path}/{prospect['id']}/bind"
    body = {"design_sha256": prospect["content_sha256"], **_source(analysis)}
    assert client.post(bind, json={**body, "design_sha256": "a" * 64}).status_code == 409
    assert client.post(bind, json={**body, "growth_analysis_id": str(uuid4())}).status_code == 404
    bound = client.post(bind, json=body)
    assert bound.status_code == 201, bound.text
    replay = bound.json()
    assert replay["id"] != prospect["id"]
    assert replay["design_id"] == prospect["design_id"]
    assert replay["revision"] == 2
    assert replay["snapshot"]["supersedes_revision_id"] == prospect["id"]
    assert replay["snapshot"]["declaration"] == prospect["snapshot"]["declaration"]
    assert replay["snapshot"]["declared_at"] == prospect["snapshot"]["declared_at"]
    assert replay["snapshot"]["binding"]["analysis_id"] == analysis["id"]
    assert client.post(bind, json=body).status_code == 409
    assert client.get(f"{path}/{prospect['id']}").json() == prospect


@pytest.mark.parametrize(
    ("changes", "status", "detail"),
    [
        ({"timing": "prospective"}, 400, "after the freeze"),
        (
            {
                "organism_keys": ["a-left"],
                "treatments": [{"code": "reference", "label": "Reference"}],
            },
            400,
            "same enrolled organisms",
        ),
        (
            {"treatments": [{"code": "reference", "label": "Reference"}]},
            400,
            "treatments must match",
        ),
        ({"metric": "box_height"}, 400, "measurement metric"),
        ({"exclusion_policy": "no_source_exclusions"}, 400, "contains excluded sources"),
    ],
)
def test_rejects_incompatible_declarations_without_persisting(
    client: TestClient, changes: dict[str, Any], status: int, detail: str
) -> None:
    project, _, analysis, _ = _study(client, reviewed_assignments=True)
    declaration = {**_declaration(), **changes}
    body = {"declaration": declaration}
    if declaration["timing"] != "prospective":
        body.update(_source(analysis))
    response = client.post(_path(project), json=body)
    assert response.status_code == status, response.text
    assert detail in response.text
    assert client.get(_path(project)).json()["items"] == []

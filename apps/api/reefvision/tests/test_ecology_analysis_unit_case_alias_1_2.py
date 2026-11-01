"""Case-alias physical units cannot inflate longitudinal or human-model sample sizes."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_longitudinal_lineage_1_2 import _rows
from reefvision.tests.test_workflow_ecology_1_2 import _graph as longitudinal_graph
from reefvision.tests.test_workflow_model_agreement_1_2 import (
    _graph as paired_graph,
)
from reefvision.tests.test_workflow_model_agreement_1_2 import _pairs


def _case(
    kind: str, first_id: str, second_id: str
) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    if kind == "longitudinal":
        observations = _rows(
            parent_b="colony-A",
            unit_type="tank",
            unit_a=first_id,
            unit_b=second_id,
        )
        for observation in observations[2:]:
            observation["experimental_unit_type"] = "aquarium"
        return (
            "/api/v1/ecology/longitudinal-analysis",
            {"observations": observations},
            longitudinal_graph(observations),
            "longitudinal_analysis",
        )
    pairs = _pairs()
    pairs[0]["experimental_unit_id"] = first_id
    pairs[1]["experimental_unit_id"] = second_id
    pairs[1]["experimental_unit_type"] = "aquarium"
    graph = cast(dict[str, Any], paired_graph())
    graph["nodes"][1]["parameters"]["pairs"] = pairs
    return (
        "/api/v1/ecology/paired-count-comparison",
        {"pairs": pairs, "reference_kind": "human_consensus"},
        graph,
        "paired_count_comparison",
    )


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
@pytest.mark.parametrize(
    ("first_id", "second_id"),
    [
        ("Tank-A", "tank-a"),
        ("Stra\u00dfe-A", "STRASSE-A"),
    ],
    ids=["ascii-case", "unicode-casefold"],
)
def test_case_alias_fails_standalone_and_saved_workflow(
    client: TestClient, kind: str, first_id: str, second_id: str
) -> None:
    endpoint, payload, graph, artifact_type = _case(kind, first_id, second_id)
    rejected = client.post(endpoint, json=payload)
    assert rejected.status_code == 400, rejected.text
    assert "differ only by case" in rejected.json()["detail"]

    project_id = str(create_project(client, f"Unit alias {kind}")["id"])
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
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
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert "differ only by case" in detail.json()["run"]["error_message"]
    assert all(row["data_type"] != artifact_type for row in detail.json()["artifacts"])


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
def test_same_exact_physical_unit_remains_one_unverified_vote(
    client: TestClient, kind: str
) -> None:
    endpoint, payload, _, _ = _case(kind, "Tank-A", "Tank-A")
    accepted = client.post(endpoint, json=payload)
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()
    assert result["evidence_level"] == "caller_supplied_unverified"
    count = (
        result["independent_unit_count"]
        if kind == "longitudinal"
        else result["declared_independent_unit_count"]
    )
    assert count == 1


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
def test_request_level_unit_type_also_rejects_case_aliases(client: TestClient, kind: str) -> None:
    endpoint, payload, _, _ = _case(kind, "Tank-A", "tank-a")
    rows = payload["observations"] if kind == "longitudinal" else payload["pairs"]
    for row in rows:
        row.pop("experimental_unit_type")
    payload["experimental_unit_type"] = "tank"
    rejected = client.post(endpoint, json=payload)
    assert rejected.status_code == 400, rejected.text
    assert "differ only by case" in rejected.json()["detail"]


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
def test_shared_tank_alias_saved_workflow_preserves_one_unit_and_review(
    client: TestClient, kind: str
) -> None:
    endpoint, payload, graph, artifact_type = _case(kind, "Tank-A", "Tank-A")
    standalone = client.post(endpoint, json=payload)
    assert standalone.status_code == 200, standalone.text

    project_id = str(create_project(client, f"Shared tank {kind}")["id"])
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
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
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = [row for row in detail.json()["artifacts"] if row["data_type"] == artifact_type]
    assert len(artifacts) == 1
    result = artifacts[0]["payload_json"]
    count_field = "independent_unit_count"
    if kind == "paired":
        count_field = "declared_independent_unit_count"
    assert result[count_field] == standalone.json()[count_field] == 1
    assert result["evidence_level"] == "caller_supplied_unverified"
    assert result["analysis_provenance"] == standalone.json()["analysis_provenance"]

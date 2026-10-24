"""Reject ambiguous ecological sampling levels through API and saved workflows."""

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
from reefvision.tests.test_workflow_model_agreement_1_2 import (
    _pairs,
)


def _case(kind: str, unit_type: str) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    if kind == "longitudinal":
        observations = _rows(unit_type=unit_type)
        return (
            "/api/v1/ecology/longitudinal-analysis",
            {"observations": observations},
            longitudinal_graph(observations),
            "longitudinal_analysis",
        )
    pairs = _pairs()
    for index, pair in enumerate(pairs):
        pair["parent_colony_id"] = f"parent-{index}"
        pair["experimental_unit_type"] = unit_type
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
    ("unit_type", "expected"),
    [
        ("colony replicate", "different parent colonies"),
        ("colony/tank", "Ambiguous experimental_unit_type"),
    ],
)
def test_standalone_rejects_disguised_or_mixed_sampling_levels(
    client: TestClient, kind: str, unit_type: str, expected: str
) -> None:
    path, payload, _, _ = _case(kind, unit_type)
    response = client.post(path, json=payload)
    assert response.status_code == 400, response.text
    assert expected in response.json()["detail"]


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
@pytest.mark.parametrize(
    ("unit_type", "expected"),
    [
        ("colony replicate", "different parent colonies"),
        ("colony/tank", "Ambiguous experimental_unit_type"),
    ],
)
def test_saved_workflow_fails_without_analysis_artifact(
    client: TestClient, kind: str, unit_type: str, expected: str
) -> None:
    _, _, graph, artifact_type = _case(kind, unit_type)
    project_id = str(create_project(client, f"Sampling-level QC {kind}")["id"])
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
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert expected in detail.json()["run"]["error_message"]
    assert all(row["data_type"] != artifact_type for row in detail.json()["artifacts"])

"""Expose shared parent colonies across units in API and saved workflow results."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.ecology_lineage_policy import cross_unit_shared_parent_colony_ids
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


class _DeclaredRow:
    def __init__(self, parent: str | None, unit: str | None) -> None:
        self.parent_colony_id = parent
        self.experimental_unit_id = unit


def test_cross_unit_parent_audit_is_sorted_and_ignores_technical_repeats() -> None:
    rows = [
        _DeclaredRow("parent-B", "tank-2"),
        _DeclaredRow("parent-A", "tank-1"),
        _DeclaredRow("parent-B", "tank-1"),
        _DeclaredRow("parent-A", "tank-2"),
        _DeclaredRow("parent-C", "tank-1"),
        _DeclaredRow("parent-C", "tank-1"),
        _DeclaredRow(None, "tank-2"),
        _DeclaredRow("parent-D", None),
    ]
    assert cross_unit_shared_parent_colony_ids(rows) == ["parent-A", "parent-B"]
    assert cross_unit_shared_parent_colony_ids(reversed(rows)) == [
        "parent-A",
        "parent-B",
    ]


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
def test_shared_parent_disclosed_in_standalone_and_saved_workflow(
    client: TestClient, kind: str
) -> None:
    if kind == "longitudinal":
        observations = _rows(
            parent_a="shared-parent",
            parent_b="shared-parent",
            unit_type="tank",
            unit_a="tank-1",
            unit_b="tank-2",
        )
        api_path = "/api/v1/ecology/longitudinal-analysis"
        api_payload: dict[str, Any] = {"observations": observations}
        graph = longitudinal_graph(observations)
        artifact_type = "longitudinal_analysis"
    else:
        pairs = _pairs()
        for index, pair in enumerate(pairs):
            pair["parent_colony_id"] = "shared-parent"
            pair["experimental_unit_id"] = f"tank-{index + 1}"
        api_path = "/api/v1/ecology/paired-count-comparison"
        api_payload = {"pairs": pairs, "reference_kind": "human_consensus"}
        graph = cast(dict[str, Any], paired_graph())
        graph["nodes"][1]["parameters"]["pairs"] = pairs
        artifact_type = "paired_count_comparison"

    standalone = client.post(api_path, json=api_payload)
    assert standalone.status_code == 200, standalone.text
    result = standalone.json()
    assert result["cross_unit_shared_parent_colony_ids"] == ["shared-parent"]
    assert result["evidence_level"] == "caller_supplied_unverified"
    count_key = "declared_independent_unit_count" if kind == "paired" else "independent_unit_count"
    assert result[count_key] == 2

    project_id = str(create_project(client, f"Shared parent review {kind}")["id"])
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
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = [row for row in detail.json()["artifacts"] if row["data_type"] == artifact_type]
    assert len(artifacts) == 1
    payload = artifacts[0]["payload_json"]
    assert payload["cross_unit_shared_parent_colony_ids"] == ["shared-parent"]
    assert payload["analysis_provenance"] == result["analysis_provenance"]
    assert payload["evidence_level"] == "caller_supplied_unverified"
    if kind == "paired":
        assert payload["review_status"] == "requires_source_verification"


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
def test_no_false_cross_unit_parent_flag_for_single_tank(client: TestClient, kind: str) -> None:
    if kind == "longitudinal":
        rows = _rows(
            parent_a="same-parent",
            parent_b="same-parent",
            unit_type="tank",
            unit_a="tank-1",
            unit_b="tank-1",
        )
        path = "/api/v1/ecology/longitudinal-analysis"
        payload = {"observations": rows}
    else:
        rows = _pairs()
        for row in rows:
            row["parent_colony_id"] = "same-parent"
        path = "/api/v1/ecology/paired-count-comparison"
        payload = {"pairs": rows, "reference_kind": "human_consensus"}
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["cross_unit_shared_parent_colony_ids"] == []

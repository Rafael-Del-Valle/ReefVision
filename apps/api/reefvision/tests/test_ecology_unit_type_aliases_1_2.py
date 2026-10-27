"""Canonical biological sampling-level aliases in standalone and saved ecology."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.ecology_lineage_policy import ecological_unit_types_equivalent
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_longitudinal_lineage_1_2 import _rows
from reefvision.tests.test_workflow_ecology_1_2 import _graph as longitudinal_graph
from reefvision.tests.test_workflow_model_agreement_1_2 import (
    _graph as paired_graph,
    _pairs,
)


def _case(
    kind: str, *, conflicting: bool = False, explicit: bool = False
) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    if kind == "longitudinal":
        observations = _rows(parent_b="colony-A", unit_type="tank")
        observations[1]["experimental_unit_type"] = "aquarium"
        observations[2]["experimental_unit_type"] = "site" if conflicting else "Tank-level"
        payload: dict[str, Any] = {"observations": observations}
        graph = longitudinal_graph(observations)
        path = "/api/v1/ecology/longitudinal-analysis"
        artifact_type = "longitudinal_analysis"
    else:
        pairs = _pairs()
        pairs[1]["experimental_unit_type"] = "site" if conflicting else "aquarium"
        payload = {"pairs": pairs, "reference_kind": "human_consensus"}
        graph = cast(dict[str, Any], paired_graph())
        graph["nodes"][1]["parameters"]["pairs"] = pairs
        path = "/api/v1/ecology/paired-count-comparison"
        artifact_type = "paired_count_comparison"
    if explicit:
        payload["experimental_unit_type"] = "aquaria"
        graph["nodes"][1]["parameters"]["experimental_unit_type"] = "aquaria"
    return path, payload, graph, artifact_type


@pytest.mark.parametrize(
    ("first", "second", "equivalent"),
    [
        ("tank", "aquarium", True),
        ("Tank-level", "aquaria", True),
        ("colony", "colonies", True),
        ("organism", "fragment", True),
        ("site", "transect", True),
        ("tank", "site", False),
        ("tank", "custom study block", False),
    ],
)
def test_biological_sampling_level_alias_policy(
    first: str, second: str, equivalent: bool
) -> None:
    assert ecological_unit_types_equivalent(first, second) is equivalent


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
@pytest.mark.parametrize("explicit", [False, True])
def test_standalone_aliases_do_not_split_one_physical_tank(
    client: TestClient, kind: str, explicit: bool
) -> None:
    path, payload, _, _ = _case(kind, explicit=explicit)
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["experimental_unit_type"] == ("aquaria" if explicit else "tank")
    if kind == "longitudinal":
        assert result["independent_unit_count"] == 1
        assert result["unit_summaries"][0]["organism_count"] == 2
    else:
        assert result["declared_independent_unit_count"] == 1
        assert result["unit_summaries"][0]["organism_count"] == 2
    assert result["evidence_level"] == "caller_supplied_unverified"
    assert result["analysis_provenance"]["canonical_input_sha256"]


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
def test_alias_inputs_remain_distinguishable_in_provenance(
    client: TestClient, kind: str
) -> None:
    path, payload, _, _ = _case(kind)
    first = client.post(path, json=payload)
    assert first.status_code == 200, first.text
    rows = payload["observations"] if kind == "longitudinal" else payload["pairs"]
    for row in rows:
        row["experimental_unit_type"] = "tank"
    second = client.post(path, json=payload)
    assert second.status_code == 200, second.text
    assert (
        first.json()["analysis_provenance"]["canonical_input_sha256"]
        != second.json()["analysis_provenance"]["canonical_input_sha256"]
    )
    assert second.json()["experimental_unit_type"] == "tank"


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
def test_incompatible_sampling_levels_still_fail_closed(
    client: TestClient, kind: str
) -> None:
    path, payload, _, _ = _case(kind, conflicting=True)
    response = client.post(path, json=payload)
    assert response.status_code == (422 if kind == "longitudinal" else 400)
    assert "conflicting experimental unit types" in response.text.lower()


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
@pytest.mark.parametrize("explicit", [False, True])
def test_saved_workflow_alias_parity_preserves_review_gate(
    client: TestClient, kind: str, explicit: bool
) -> None:
    path, payload, graph, artifact_type = _case(kind, explicit=explicit)
    standalone = client.post(path, json=payload)
    assert standalone.status_code == 200, standalone.text
    project_id = str(create_project(client, f"Alias QC {kind} {explicit}")["id"])
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
    artifact = next(
        row for row in detail.json()["artifacts"] if row["data_type"] == artifact_type
    )
    stored = artifact["payload_json"]
    assert stored["project_id"] == project_id
    assert stored["experimental_unit_type"] == standalone.json()["experimental_unit_type"]
    assert stored["analysis_provenance"] == standalone.json()["analysis_provenance"]
    assert stored["evidence_level"] == "caller_supplied_unverified"
    if kind == "paired":
        assert stored["review_status"] == "requires_source_verification"


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
def test_saved_workflow_rejects_conflicting_levels_without_artifact(
    client: TestClient, kind: str
) -> None:
    _, _, graph, artifact_type = _case(kind, conflicting=True)
    project_id = str(create_project(client, f"Conflicting alias QC {kind}")["id"])
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
    assert "conflicting experimental unit types" in (
        detail.json()["run"]["error_message"].lower()
    )
    assert all(row["data_type"] != artifact_type for row in detail.json()["artifacts"])

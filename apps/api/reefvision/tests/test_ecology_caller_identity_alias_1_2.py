"""Caller-declared organism and parent aliases must not create biological votes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.longitudinal_monitoring import LongitudinalAnalysisResponse
from reefvision.schemas.model_agreement import PairedCountComparisonResponse
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_longitudinal_lineage_1_2 import _rows
from reefvision.tests.test_workflow_ecology_1_2 import _graph as longitudinal_graph
from reefvision.tests.test_workflow_model_agreement_1_2 import (
    _graph as paired_graph,
)
from reefvision.tests.test_workflow_model_agreement_1_2 import _pairs


def _case(
    analysis: str, identity: str, *, compatible_unicode: bool
) -> tuple[str, dict[str, Any], dict[str, Any], str, str]:
    if analysis == "longitudinal":
        rows = _rows(
            parent_b="colony-A",
            unit_type="tank",
            unit_a="tank-A",
            unit_b="tank-A",
        )
        if identity == "organism":
            alias = "\uff46\uff52\uff41\uff47-A" if compatible_unicode else "FRAG-A"
            for row in rows[2:]:
                row["organism_id"] = alias
        else:
            alias = "\uff43\uff4f\uff4c\uff4f\uff4e\uff59-A" if compatible_unicode else "COLONY-A"
            for row in rows[2:]:
                row["parent_colony_id"] = alias
        return (
            "/api/v1/ecology/longitudinal-analysis",
            {"observations": rows},
            cast(dict[str, Any], longitudinal_graph(rows)),
            "longitudinal_analysis",
            "Caller-declared",
        )

    pairs = _pairs()
    pairs[0]["parent_colony_id"] = "colony-A"
    pairs[1]["parent_colony_id"] = "colony-A"
    if identity == "organism":
        alias = (
            "\uff46\uff52\uff41\uff47\uff4d\uff45\uff4e\uff54-A"
            if compatible_unicode
            else "FRAGMENT-A"
        )
        pairs[1]["organism_id"] = alias
    else:
        alias = "\uff43\uff4f\uff4c\uff4f\uff4e\uff59-A" if compatible_unicode else "COLONY-A"
        pairs[1]["parent_colony_id"] = alias
    graph = cast(dict[str, Any], paired_graph())
    graph["nodes"][1]["parameters"]["pairs"] = pairs
    return (
        "/api/v1/ecology/paired-count-comparison",
        {"pairs": pairs, "reference_kind": "human_consensus"},
        graph,
        "paired_count_comparison",
        "Caller-declared",
    )


def _run_saved(
    client: TestClient, graph: dict[str, Any], artifact_type: str, name: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    project_id = str(create_project(client, name)["id"])
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
    completed = process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert (body["run"]["status"] == "succeeded") is completed
    artifacts = [item for item in body["artifacts"] if item["data_type"] == artifact_type]
    return body["run"], artifacts


@pytest.mark.parametrize("analysis", ["longitudinal", "paired"])
@pytest.mark.parametrize("identity", ["organism", "parent"])
@pytest.mark.parametrize("compatible_unicode", [False, True], ids=["case", "unicode-nfkc"])
def test_aliases_fail_standalone_and_saved_workflow(
    client: TestClient, analysis: str, identity: str, compatible_unicode: bool
) -> None:
    endpoint, payload, graph, artifact_type, _ = _case(
        analysis, identity, compatible_unicode=compatible_unicode
    )
    rejected = client.post(endpoint, json=payload)
    assert rejected.status_code == 400, rejected.text
    label = "organism" if identity == "organism" else "parent-colony"
    assert (
        f"Caller-declared {label} IDs differ only by case or Unicode compatibility"
        in rejected.json()["detail"]
    )

    run, artifacts = _run_saved(client, graph, artifact_type, f"Caller alias {analysis} {identity}")
    assert run["status"] == "failed"
    assert "differ only by case or Unicode compatibility" in run["error_message"]
    assert artifacts == []


@pytest.mark.parametrize("analysis", ["longitudinal", "paired"])
def test_exact_shared_parent_and_saved_result_remain_unverified(
    client: TestClient, analysis: str
) -> None:
    endpoint, payload, graph, artifact_type, _ = _case(analysis, "parent", compatible_unicode=False)
    rows = payload["observations"] if analysis == "longitudinal" else payload["pairs"]
    for row in rows:
        row["parent_colony_id"] = "colony-A"
    if analysis == "paired":
        graph["nodes"][1]["parameters"]["pairs"] = rows
    else:
        graph = cast(dict[str, Any], longitudinal_graph(rows))

    standalone = client.post(endpoint, json=payload)
    assert standalone.status_code == 200, standalone.text
    run, artifacts = _run_saved(client, graph, artifact_type, f"Exact parent {analysis}")
    assert run["status"] == "succeeded"
    assert len(artifacts) == 1
    persisted = artifacts[0]["payload_json"]
    assert persisted["analysis_provenance"] == standalone.json()["analysis_provenance"]
    assert persisted["evidence_level"] == "caller_supplied_unverified"
    if analysis == "paired":
        assert persisted["review_status"] == "requires_source_verification"
        assert persisted["declared_independent_unit_count"] == 1
        schema = PairedCountComparisonResponse
        forged = deepcopy(persisted)
        forged["paired_differences"][1]["organism_id"] = "FRAGMENT-A"
        message = "Directional persisted organism IDs"
    else:
        assert persisted["independent_unit_count"] == 1
        schema = LongitudinalAnalysisResponse
        forged = deepcopy(persisted)
        forged["changes"][1]["organism_id"] = "FRAG-A"
        message = "Longitudinal persisted organism IDs"
    with pytest.raises(PydanticValidationError, match=message):
        schema.model_validate(forged)


def test_exact_repeated_paired_organism_is_one_vote(client: TestClient) -> None:
    pairs = _pairs()
    pairs[1]["organism_id"] = pairs[0]["organism_id"]
    response = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": pairs, "reference_kind": "human_consensus"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["observed_organism_count"] == 1
    assert response.json()["declared_independent_unit_count"] == 1

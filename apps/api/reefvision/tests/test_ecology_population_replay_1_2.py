"""Persisted 1.2 population strata must never multiply biological replicates."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.longitudinal_monitoring import LongitudinalAnalysisResponse
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_sampling_schedule_1_2 import _payload
from reefvision.tests.test_workflow_ecology_1_2 import _graph


def _two_tank_payload() -> dict[str, Any]:
    request = _payload()
    second_tank = deepcopy(request["observations"])
    for row in second_tank:
        row["organism_id"] = "X-" + row["organism_id"]
        row["source_record_id"] = "X-" + row["source_record_id"]
        row["experimental_unit_id"] = "tank-2"
        day = int(row["observed_at"][8:10])
        row["value"] = 20 + 3 * day
    request["observations"].extend(second_tank)
    request["expected_sampling_dates_by_unit"]["tank-2"] = list(
        request["expected_sampling_dates_by_unit"]["tank-1"]
    )
    return request


def test_population_replay_weights_two_tanks_not_four_fragments(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=_two_tank_payload())
    assert response.status_code == 200, response.text
    result = response.json()
    LongitudinalAnalysisResponse.model_validate(result)
    assert len(result["unit_summaries"]) == 2
    assert len(result["population_summaries"]) == 1
    population = result["population_summaries"][0]
    assert population["experimental_unit_ids"] == ["tank-1", "tank-2"]
    assert population["independent_unit_count"] == 2
    assert population["contributing_organism_count"] == 4
    assert population["mean_unit_absolute_change"] == pytest.approx(4)
    assert population["mean_unit_change_per_day"] == pytest.approx(2)
    assert result["evidence_level"] == "caller_supplied_unverified"


@pytest.mark.parametrize(
    "tampering",
    [
        "duplicate_unit",
        "removed_unit",
        "inflated_organisms",
        "forged_unit_roster",
        "forged_independent_count",
        "forged_contributors",
        "forged_mean",
        "forged_rate",
        "duplicate_stratum",
        "changed_stratum",
        "changed_unit_window",
        "coordinated_unicode_unit_alias",
    ],
)
def test_population_replay_rejects_pseudoreplication_and_forged_means(
    client: TestClient, tampering: str
) -> None:
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=_two_tank_payload())
    assert response.status_code == 200, response.text
    original = response.json()
    LongitudinalAnalysisResponse.model_validate(original)
    forged = deepcopy(original)
    units = forged["unit_summaries"]
    population = forged["population_summaries"][0]
    if tampering == "duplicate_unit":
        units.append(deepcopy(units[0]))
    elif tampering == "removed_unit":
        units.pop()
    elif tampering == "inflated_organisms":
        units[0]["organism_count"] += 1
    elif tampering == "forged_unit_roster":
        population["experimental_unit_ids"] = ["tank-1", "tank-1"]
    elif tampering == "forged_independent_count":
        population["independent_unit_count"] = 3
    elif tampering == "forged_contributors":
        population["contributing_organism_count"] = 5
    elif tampering == "forged_mean":
        population["mean_unit_absolute_change"] += 1
    elif tampering == "forged_rate":
        population["mean_unit_change_per_day"] += 1
    elif tampering == "duplicate_stratum":
        forged["population_summaries"].append(deepcopy(population))
    elif tampering == "changed_stratum":
        population["final_date"] = "2026-04-04"
    elif tampering == "changed_unit_window":
        units[1]["final_at"] = "2026-04-04T12:00:00Z"
    elif tampering == "coordinated_unicode_unit_alias":
        units[1]["experimental_unit_id"] = "TANK-1"
        population["experimental_unit_ids"] = ["TANK-1", "tank-1"]
    expected_error = (
        "persisted experimental unit IDs differ only by case or Unicode compatibility"
        if tampering == "coordinated_unicode_unit_alias"
        else "Population summary"
    )
    with pytest.raises(PydanticValidationError, match=expected_error):
        LongitudinalAnalysisResponse.model_validate(forged)


@pytest.mark.parametrize(
    "tampering",
    [
        "coordinated_mean",
        "coordinated_rate",
        "coordinated_organism_count",
        "baseline_hour",
        "final_hour",
    ],
)
def test_unit_summary_replay_rejects_forged_organism_aggregates(
    client: TestClient, tampering: str
) -> None:
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=_two_tank_payload())
    assert response.status_code == 200, response.text
    original = response.json()
    LongitudinalAnalysisResponse.model_validate(original)
    forged = deepcopy(original)
    unit = forged["unit_summaries"][0]
    population = forged["population_summaries"][0]
    if tampering == "coordinated_mean":
        unit["mean_absolute_change"] += 2
        population["mean_unit_absolute_change"] += 1
    elif tampering == "coordinated_rate":
        unit["mean_change_per_day"] += 2
        population["mean_unit_change_per_day"] += 1
    elif tampering == "coordinated_organism_count":
        unit["organism_count"] += 1
        population["contributing_organism_count"] += 1
    elif tampering == "baseline_hour":
        unit["baseline_at"] = unit["baseline_at"].replace("T12:", "T13:")
    elif tampering == "final_hour":
        unit["final_at"] = unit["final_at"].replace("T12:", "T13:")
    with pytest.raises(PydanticValidationError, match="Unit summary"):
        LongitudinalAnalysisResponse.model_validate(forged)


def test_saved_workflow_population_artifact_rejects_forged_unit_weight(
    client: TestClient,
) -> None:
    request = _two_tank_payload()
    project_id = str(create_project(client, "Population replay QC")["id"])
    graph = _graph(request["observations"])
    graph["nodes"][1]["parameters"].update(
        {
            "experimental_unit_type": "tank",
            "expected_sampling_dates_by_unit": request["expected_sampling_dates_by_unit"],
        }
    )
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    ecology = next(
        item for item in registry.json() if item["node_type"] == "ecology_longitudinal_analysis"
    )
    assert ecology["output_ports"][0]["accepted_types"] == ["longitudinal_analysis"]
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
    artifacts = [
        item for item in detail.json()["artifacts"] if item["data_type"] == "longitudinal_analysis"
    ]
    assert len(artifacts) == 1
    persisted = artifacts[0]["payload_json"]
    standalone = client.post("/api/v1/ecology/longitudinal-analysis", json=request)
    assert standalone.status_code == 200, standalone.text
    assert persisted["population_summaries"] == standalone.json()["population_summaries"]
    assert persisted["analysis_provenance"] == standalone.json()["analysis_provenance"]
    assert persisted["evidence_level"] == "caller_supplied_unverified"
    LongitudinalAnalysisResponse.model_validate(persisted)
    forged = deepcopy(persisted)
    forged["population_summaries"][0]["independent_unit_count"] = 4
    with pytest.raises(PydanticValidationError, match="Population summary"):
        LongitudinalAnalysisResponse.model_validate(forged)
    # A coordinated alteration of both unit and population rosters must not
    # turn one tank into two independent biological replicates on replay.
    forged = deepcopy(persisted)
    forged["unit_summaries"][1]["experimental_unit_id"] = "TANK-1"
    forged["population_summaries"][0]["experimental_unit_ids"] = ["TANK-1", "tank-1"]
    with pytest.raises(
        PydanticValidationError,
        match="persisted experimental unit IDs differ only by case or Unicode compatibility",
    ):
        LongitudinalAnalysisResponse.model_validate(forged)
    # Re-signing both levels of a descriptive mean must not detach the
    # unit result from the organism-level measurements it summarizes.
    forged = deepcopy(persisted)
    forged["unit_summaries"][0]["mean_absolute_change"] += 2
    forged["population_summaries"][0]["mean_unit_absolute_change"] += 1
    with pytest.raises(PydanticValidationError, match="Unit summary means"):
        LongitudinalAnalysisResponse.model_validate(forged)

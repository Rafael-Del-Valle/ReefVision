"""Ecological unit/population CSV: science, API and persisted workflow parity."""

from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
)
from reefvision.schemas.workflow_graphs import WorkflowPortDefinition
from reefvision.services.ecology_population_export import render_ecology_population_csv
from reefvision.tests.test_ecology_projected_series_csv_1_2 import (
    _dated_artifact,
    _resign_derived_evidence,
)
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def test_population_csv_is_a_strictly_typed_workflow_artifact() -> None:
    """Registry ports must accept the new export type before graph planning."""
    port = WorkflowPortDefinition(
        port_id="csv",
        display_name="Unverified population summary CSV",
        accepted_types=["ecology_population_csv"],
    )
    assert port.accepted_types == ["ecology_population_csv"]


def _rows(value: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(value)))


def test_population_csv_preserves_excluded_units_and_api_parity(client: TestClient) -> None:
    project_id, _ = _source(client)
    base = f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    response = client.get(base)
    exported = client.get(base + "/population.csv")
    assert response.status_code == exported.status_code == 200
    typed = EcologyMeasurementCandidatesResponse.model_validate(response.json())
    assert render_ecology_population_csv(typed) == exported.text
    rows = _rows(exported.text)
    assert len(rows) == len(typed.projected_unit_summaries)
    assert rows
    assert all(row["row_type"] == "declared_unit" for row in rows)
    assert all(row["unit_status"] == "missing_unit_declaration" for row in rows)
    assert all(row["declared_unit_count"] == "0" for row in rows)
    assert all(row["mean_absolute_change"] == "" for row in rows)
    assert all(row["independent_unit_inference_allowed"] == "false" for row in rows)
    assert all(row["review_gate"] == "scientist_review_required" for row in rows)


def test_population_csv_reports_declared_unit_weighting_without_inference(
    client: TestClient,
) -> None:
    source = _dated_artifact(client)
    rows = _rows(render_ecology_population_csv(source))
    assert len(rows) == 2
    unit = next(row for row in rows if row["row_type"] == "declared_unit")
    population = next(row for row in rows if row["row_type"] == "population_stratum")
    assert unit["unit_status"] == "candidate"
    assert unit["declared_unit_count"] == "1"
    assert population["declared_unit_count"] == "1"
    assert json.loads(population["experimental_unit_ids_json"]) == ["tank-A"]
    assert json.loads(population["organism_keys_json"]) == []
    assert population["contributing_organism_count"] == "1"
    assert float(population["mean_absolute_change"]) == pytest.approx(2)
    assert population["sample_sd_unit_absolute_change"] == ""
    assert "single_declared_unit" in json.loads(population["design_review_blockers_json"])
    assert population["independent_unit_inference_allowed"] == "false"
    assert population["evidence_level"] == "linked_unverified"



def test_population_csv_stratum_fields_match_typed_scientific_summary(
    client: TestClient,
) -> None:
    """Keep population and unit fields distinct across CSV serialization."""
    source = _dated_artifact(client)
    summary = source.projected_population_summaries[0]
    population = next(
        row
        for row in _rows(render_ecology_population_csv(source))
        if row["row_type"] == "population_stratum"
    )
    assert population["metric"] == summary.metric
    assert population["experimental_unit_type"] == summary.experimental_unit_type
    assert json.loads(population["experimental_unit_ids_json"]) == (summary.experimental_unit_ids)
    assert json.loads(population["physical_units_json"]) == [summary.unit]
    assert json.loads(population["sampling_windows_utc_json"]) == [summary.sampling_window_utc]
    assert json.loads(population["parent_colony_keys_json"]) == (summary.parent_colony_keys)
    assert json.loads(population["shared_parent_colony_keys_json"]) == (
        summary.shared_parent_colony_keys
    )
    assert json.loads(population["units_missing_parent_colony_json"]) == (
        summary.units_missing_parent_colony
    )
    assert json.loads(population["design_review_blockers_json"]) == (summary.design_review_blockers)
    assert int(population["declared_unit_count"]) == summary.declared_unit_count
    assert int(population["contributing_organism_count"]) == (summary.contributing_organism_count)
    assert float(population["mean_absolute_change"]) == pytest.approx(
        summary.mean_unit_absolute_change
    )
    assert population["review_gate"] == "scientist_review_required"
    assert population["independent_unit_inference_allowed"] == "false"


def test_population_csv_rejects_resigned_or_legacy_unreviewed_science(
    client: TestClient,
) -> None:
    source = _dated_artifact(client)
    tampered = source.model_copy(deep=True)
    tampered.projected_population_summaries[0].mean_unit_absolute_change = 999
    with pytest.raises(ValidationError, match="Projected population summaries"):
        render_ecology_population_csv(tampered)
    legacy = source.model_copy(update={"source_fingerprint_contract": None})
    with pytest.raises(ValidationError, match="recheckable source"):
        render_ecology_population_csv(legacy)


@pytest.mark.parametrize(
    "forged_fields",
    [
        {"declared_unit_count": 2},
        {"contributing_organism_count": 2},
        {"shared_parent_colony_keys": ["forged-shared-parent"]},
        {"design_review_blockers": []},
        {"sample_sd_unit_absolute_change": 2.0},
        {"mean_unit_percent_change": 12345.0},
        {"experimental_unit_ids": ["tank-A", "forged-tank-B"]},
        {"parent_colony_keys": ["forged-parent"]},
        {"units_missing_parent_colony": ["tank-A"]},
    ],
)
def test_population_csv_rejects_resigned_forged_replication_evidence(
    client: TestClient,
    forged_fields: dict[str, Any],
) -> None:
    """Re-signing a CSV source cannot manufacture independent replicates.

    The one-unit fixture must retain its actual unit/organism denominators,
    lack of estimable sample SD, true unit roster/parent lineage, and review blockers.
    """
    source = _dated_artifact(client)
    assert source.projected_population_summaries[0].declared_unit_count == 1
    altered_summary = source.projected_population_summaries[0].model_copy(update=forged_fields)
    forged = _resign_derived_evidence(
        source.model_copy(update={"projected_population_summaries": [altered_summary]})
    )
    with pytest.raises(ValidationError, match="Projected population summaries"):
        render_ecology_population_csv(forged)


def test_saved_workflow_population_csv_matches_standalone_and_blocks_promotion(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200
    node = next(
        row for row in registry.json() if row["node_type"] == "ecology_population_csv_export"
    )
    assert node["executable"] is True
    assert node["input_ports"][0]["accepted_types"] == ["ecology_measurement_candidates"]
    assert node["output_ports"][0]["accepted_types"] == ["ecology_population_csv"]

    graph: dict[str, Any] = {
        "graph_id": "ecology-population-csv-1-2",
        "name": "Review unverified ecological population strata",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "identity", "node_type": "ecology_identity_registry_source"},
            {"node_id": "export", "node_type": "ecology_population_csv_export"},
        ],
        "edges": [
            {
                "edge_id": "project-identity",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "identity",
                "target_port_id": "project",
            },
            {
                "edge_id": "candidate-export",
                "source_node_id": "identity",
                "source_port_id": "measurement_candidates",
                "target_node_id": "export",
                "target_port_id": "candidates",
            },
        ],
    }
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
    artifacts = [
        row for row in detail.json()["artifacts"] if row["data_type"] == "ecology_population_csv"
    ]
    assert len(artifacts) == 1
    payload = artifacts[0]["payload_json"]
    standalone = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates/population.csv"
    )
    assert standalone.status_code == 200, standalone.text
    assert payload["csv_text"] == standalone.text
    assert payload["source_fingerprint_rechecked"] is True
    assert payload["evidence_level"] == "linked_unverified"
    assert payload["review_gate"] == "scientist_review_required"

    graph["nodes"].append({"node_id": "dataset", "node_type": "dataset_version_create"})
    graph["edges"].append(
        {
            "edge_id": "csv-to-verified",
            "source_node_id": "export",
            "source_port_id": "csv",
            "target_node_id": "dataset",
            "target_port_id": "reviewed",
        }
    )
    invalid = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/validate", json=graph)
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False
    assert any(issue["code"] == "incompatible_port_types" for issue in invalid.json()["issues"])

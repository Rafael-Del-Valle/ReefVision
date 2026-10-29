"""Saved Workflow Builder execution and unverified-data boundary for paired counts."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.model_agreement import PairedCountComparisonResponse
from reefvision.tests.test_annotations import create_project


def _pairs() -> list[dict[str, object]]:
    return [
        {
            "observation_id": "image-1",
            "organism_id": "fragment-A",
            "metric_name": "polyp_count",
            "reference_source_record_id": "human-image-1",
            "model_source_record_id": "model-image-1",
            "reference_count": 10,
            "model_count": 12,
            "experimental_unit_id": "tank-A",
            "experimental_unit_type": "tank",
        },
        {
            "observation_id": "image-2",
            "organism_id": "fragment-B",
            "metric_name": "polyp_count",
            "reference_source_record_id": "human-image-2",
            "model_source_record_id": "model-image-2",
            "reference_count": 20,
            "model_count": 16,
            "experimental_unit_id": "tank-A",
            "experimental_unit_type": "tank",
        },
    ]


def _graph() -> dict[str, object]:
    return {
        "graph_id": "paired-count-comparison-1-2",
        "name": "Exploratory paired human-model count comparison",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "comparison",
                "node_type": "ecology_paired_count_comparison",
                "parameters": {"pairs": _pairs(), "reference_kind": "human_consensus"},
            },
        ],
        "edges": [
            {
                "edge_id": "project-comparison",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "comparison",
                "target_port_id": "project",
            }
        ],
    }


def test_standalone_paired_comparison_returns_unverified_evidence(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": _pairs(), "reference_kind": "human_consensus"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["evidence_level"] == "caller_supplied_unverified"
    assert payload["review_status"] == "requires_source_verification"
    assert payload["paired_observation_count"] == 2
    assert payload["observed_organism_count"] == 2
    assert payload["repeated_pair_count_beyond_first_per_organism"] == 0
    assert payload["unequal_pair_counts_across_organisms"] is False
    assert payload["declared_independent_unit_count"] == 1
    assert payload["mean_signed_bias"] == -1
    assert payload["mean_absolute_error"] == 3
    assert payload["organism_and_unit_balanced_mean_signed_bias"] == -1
    assert payload["unit_balanced_mean_absolute_percent_deviation"] == 20
    assert payload["mean_signed_percent_deviation"] == 0
    assert payload["unit_balanced_mean_signed_percent_deviation"] == 0
    assert payload["organism_and_unit_balanced_mean_signed_percent_deviation"] == 0


def test_saved_comparison_workflow_persists_typed_unverified_artifact(
    client: TestClient,
) -> None:
    project = create_project(client, "Paired count agreement workflow")
    project_id = str(project["id"])
    registry_response = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry_response.status_code == 200
    definitions = {item["node_type"]: item for item in registry_response.json()}
    node = definitions["ecology_paired_count_comparison"]
    assert node["executable"] is True
    assert node["input_ports"][0]["accepted_types"] == ["project_reference"]
    assert node["output_ports"][0]["accepted_types"] == ["paired_count_comparison"]
    graph = _graph()
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
        row for row in detail.json()["artifacts"] if row["data_type"] == "paired_count_comparison"
    )
    payload = artifact["payload_json"]
    assert PairedCountComparisonResponse.model_validate(payload).paired_observation_count == 2
    # The persisted typed artifact must reject tampering even when the raw
    # direction-frequency totals themselves have not been modified.
    tampered = dict(payload)
    tampered["paired_differences"] = [dict(row) for row in payload["paired_differences"]]
    tampered["paired_differences"][0]["signed_difference"] = 99
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(tampered)
    tampered_mean = dict(payload)
    tampered_mean["mean_signed_bias"] = 999
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(tampered_mean)
    # A saved workflow artifact cannot conceal a forged tank-level mean by
    # changing the corresponding grand mean to match it.
    tampered_unit = dict(payload)
    tampered_unit["unit_summaries"] = [dict(row) for row in payload["unit_summaries"]]
    tampered_unit["unit_summaries"][0]["mean_absolute_error"] += 1
    tampered_unit["unit_balanced_mean_absolute_error"] += 1
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(tampered_unit)
    # Persisted Workflow Builder outputs must retain distinct paired evidence
    # on reload, not merely consistent directional statistics.
    tampered_sources = dict(payload)
    tampered_sources["paired_differences"] = [
        dict(row) for row in payload["paired_differences"]
    ]
    tampered_sources["paired_differences"][1]["reference_source_record_id"] = (
        tampered_sources["paired_differences"][0]["reference_source_record_id"]
    )
    with pytest.raises(SchemaValidationError, match="Directional"):
        PairedCountComparisonResponse.model_validate(tampered_sources)
    assert payload["project_id"] == project_id
    assert payload["evidence_level"] == "caller_supplied_unverified"
    assert payload["review_status"] == "requires_source_verification"
    assert payload["mean_signed_bias"] == -1
    assert payload["observed_organism_count"] == 2
    assert payload["observation_counts_by_organism"] == {"fragment-A": 1, "fragment-B": 1}
    assert payload["declared_independent_unit_count"] == 1
    assert payload["organism_and_unit_balanced_mean_signed_bias"] == -1
    assert payload["unit_balanced_mean_absolute_percent_deviation"] == 20
    assert payload["mean_signed_percent_deviation"] == 0
    assert payload["unit_balanced_mean_signed_percent_deviation"] == 0
    assert payload["organism_and_unit_balanced_mean_signed_percent_deviation"] == 0
    assert payload["percent_contributing_independent_unit_count"] == 1
    assert payload["reference_source_record_ids"] == ["human-image-1", "human-image-2"]
    assert payload["overcount_pair_count"] == 1
    assert payload["undercount_pair_count"] == 1
    assert payload["exact_match_pair_count"] == 0
    assert payload["overcount_organism_count"] == 1
    assert payload["undercount_organism_count"] == 1
    assert payload["balanced_organism_count"] == 0
    assert payload["unit_summaries"][0]["overcount_organism_count"] == 1
    assert payload["unit_summaries"][0]["undercount_organism_count"] == 1
    assert payload["unit_summaries"][0]["overcount_pair_count"] == 1
    assert payload["unit_summaries"][0]["undercount_pair_count"] == 1
    assert payload["unit_summaries"][0]["exact_match_pair_count"] == 0
    assert payload["model_source_record_ids"] == ["model-image-1", "model-image-2"]
    standalone = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": _pairs(), "reference_kind": "human_consensus"},
    )
    assert standalone.status_code == 200, standalone.text
    assert (
        PairedCountComparisonResponse.model_validate(standalone.json()).paired_observation_count
        == 2
    )
    assert payload["analysis_provenance"] == standalone.json()["analysis_provenance"]
    for key in (
        "observed_organism_count",
        "observation_counts_by_organism",
        "repeated_pair_count_beyond_first_per_organism",
        "unequal_pair_counts_across_organisms",
        "unit_summaries",
        "overcount_pair_count",
        "undercount_pair_count",
        "exact_match_pair_count",
        "overcount_organism_count",
        "undercount_organism_count",
        "balanced_organism_count",
        "mean_signed_percent_deviation",
        "unit_balanced_mean_signed_percent_deviation",
        "organism_and_unit_balanced_mean_signed_percent_deviation",
    ):
        assert payload[key] == standalone.json()[key]


def test_unverified_comparison_cannot_enter_verified_dataset(
    client: TestClient,
) -> None:
    project = create_project(client, "Paired count review boundary")
    graph = _graph()
    graph["nodes"].append({"node_id": "dataset", "node_type": "dataset_version_create"})
    graph["edges"].append(
        {
            "edge_id": "unverified-comparison-into-dataset",
            "source_node_id": "comparison",
            "source_port_id": "comparison",
            "target_node_id": "dataset",
            "target_port_id": "reviewed",
        }
    )
    response = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/validate", json=graph)
    assert response.status_code == 200, response.text
    assert response.json()["valid"] is False
    assert any(issue["code"] == "incompatible_port_types" for issue in response.json()["issues"])


def test_saved_repeated_organism_pairs_retain_frequency_qc(client: TestClient) -> None:
    """Saved typed analysis must expose repeat-pair risk, not image-level N."""
    project = create_project(client, "Repeated organism count review")
    project_id = str(project["id"])
    pairs = _pairs()
    repeat = dict(pairs[0])
    repeat.update(
        observation_id="image-3",
        reference_source_record_id="human-image-3",
        model_source_record_id="model-image-3",
        model_count=8,
    )
    pairs.append(repeat)
    graph = cast(dict[str, Any], _graph())
    graph["nodes"][1]["parameters"]["pairs"] = pairs
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
        row for row in detail.json()["artifacts"] if row["data_type"] == "paired_count_comparison"
    )["payload_json"]
    standalone = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": pairs, "reference_kind": "human_consensus"},
    )
    assert standalone.status_code == 200, standalone.text
    assert artifact["observed_organism_count"] == 2
    assert artifact["repeated_pair_count_beyond_first_per_organism"] == 1
    assert artifact["overcount_pair_count"] == 1
    assert artifact["undercount_pair_count"] == 2
    assert artifact["exact_match_pair_count"] == 0
    assert artifact["overcount_organism_count"] == 0
    assert artifact["undercount_organism_count"] == 1
    assert artifact["balanced_organism_count"] == 1
    assert artifact["unit_summaries"][0]["balanced_organism_count"] == 1
    assert artifact["unequal_pair_counts_across_organisms"] is True
    assert artifact["unit_summaries"][0]["unequal_pair_counts_within_unit"] is True
    for key in (
        "analysis_provenance",
        "observed_organism_count",
        "observation_counts_by_organism",
        "repeated_pair_count_beyond_first_per_organism",
        "unequal_pair_counts_across_organisms",
        "unit_summaries",
        "overcount_organism_count",
        "undercount_organism_count",
        "balanced_organism_count",
    ):
        assert artifact[key] == standalone.json()[key]
    assert artifact["evidence_level"] == "caller_supplied_unverified"
    assert artifact["review_status"] == "requires_source_verification"

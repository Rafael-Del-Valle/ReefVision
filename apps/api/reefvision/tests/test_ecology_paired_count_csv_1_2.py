"""Scientific CSV export parity across standalone API and saved Workflow Builder."""

from __future__ import annotations

import csv
import hashlib
from io import StringIO
from typing import Any, cast, get_args

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.domain.model_agreement import compare_paired_counts
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.model_agreement import (
    PairedCountComparisonRequest,
    PairedCountComparisonResponse,
)
from reefvision.schemas.workflow_graphs import WorkflowDataType, WorkflowPortDefinition
from reefvision.services.ecology_paired_count_export import render_paired_count_csv
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_model_agreement_1_2 import _graph, _pairs


def _request(pairs: list[dict[str, object]]) -> dict[str, object]:
    return {"pairs": pairs, "reference_kind": "human_consensus"}


def test_standalone_csv_has_source_provenance_and_correct_denominators(
    client: TestClient,
) -> None:
    pairs = _pairs()
    zero = dict(pairs[0])
    zero.update(
        observation_id="image-3",
        reference_source_record_id="human-image-3",
        model_source_record_id="model-image-3",
        reference_count=0,
        model_count=3,
    )
    pairs.append(zero)
    response = client.post("/api/v1/ecology/paired-count-comparison", json=_request(pairs))
    assert response.status_code == 200, response.text
    exported = client.post(
        "/api/v1/ecology/paired-count-comparison/report.csv", json=_request(pairs)
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    comparison = PairedCountComparisonResponse.model_validate(response.json())
    assert exported.text == render_paired_count_csv(comparison)
    rows = list(csv.DictReader(StringIO(exported.text)))
    assert [row["row_type"] for row in rows] == [
        "pair",
        "pair",
        "pair",
        "organism_descriptive",
        "organism_descriptive",
        "declared_unit",
        "overall",
    ]
    assert all(row["evidence_level"] == "caller_supplied_unverified" for row in rows)
    assert all(row["review_status"] == "requires_source_verification" for row in rows)
    assert all(row["independent_inference_allowed"] == "false" for row in rows)
    assert all(row["export_schema_version"] == "ecology-paired-count-csv-0004" for row in rows)
    assert all(
        row["source_input_sha256"] == comparison.analysis_provenance.canonical_input_sha256
        for row in rows
    )
    assert rows[2]["reference_count"] == "0.0"
    assert rows[2]["signed_percent_deviation"] == ""
    assert rows[2]["absolute_percent_deviation"] == ""
    assert rows[3]["organism_id"] == "fragment-A"
    assert rows[3]["paired_observation_count"] == "2"
    assert rows[3]["repeated_observation_count"] == "1"
    assert rows[3]["nonzero_reference_count"] == "1"
    assert rows[3]["mean_signed_bias"] == "2.5"
    assert rows[3]["mean_signed_percent_deviation"] == "20.0"
    assert rows[4]["organism_id"] == "fragment-B"
    assert rows[4]["mean_signed_bias"] == "-4.0"
    assert rows[-1]["paired_observation_count"] == "3"
    assert rows[-1]["observed_organism_count"] == "2"
    assert rows[-1]["declared_independent_unit_count"] == "1"
    assert rows[-1]["nonzero_reference_count"] == "2"
    shuffled = client.post(
        "/api/v1/ecology/paired-count-comparison/report.csv",
        json=_request(list(reversed(pairs))),
    )
    assert shuffled.status_code == 200, shuffled.text
    assert shuffled.text == exported.text


def test_csv_exposes_nested_biological_unit_balancing_without_inflating_n(
    client: TestClient,
) -> None:
    """Repeated images cannot masquerade as equally weighted biological units."""
    original = _pairs()
    a_first = dict(original[0])
    a_first.update(reference_count=10, model_count=20)
    a_repeat = dict(a_first)
    a_repeat.update(
        observation_id="image-3",
        reference_source_record_id="human-image-3",
        model_source_record_id="model-image-3",
    )
    b = dict(original[1])
    b.update(reference_count=10, model_count=10)
    c = dict(b)
    c.update(
        observation_id="image-4",
        organism_id="fragment-C",
        reference_source_record_id="human-image-4",
        model_source_record_id="model-image-4",
        experimental_unit_id="tank-B",
    )
    pairs = [a_first, a_repeat, b, c]
    response = client.post(
        "/api/v1/ecology/paired-count-comparison/report.csv", json=_request(pairs)
    )
    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(StringIO(response.text)))
    units = {row["experimental_unit_id"]: row for row in rows if row["row_type"] == "declared_unit"}
    overall = next(row for row in rows if row["row_type"] == "overall")
    assert len(units) == 2
    assert overall["paired_observation_count"] == "4"
    assert overall["observed_organism_count"] == "3"
    assert overall["declared_independent_unit_count"] == "2"
    assert overall["percent_contributing_organism_count"] == "3"
    assert overall["percent_contributing_independent_unit_count"] == "2"
    assert float(overall["mean_signed_bias"]) == pytest.approx(5)
    assert float(overall["unit_balanced_mean_signed_bias"]) == pytest.approx(10 / 3)
    assert float(overall["organism_and_unit_balanced_mean_signed_bias"]) == pytest.approx(2.5)
    assert float(overall["unit_balanced_mean_absolute_percent_deviation"]) == (
        pytest.approx(100 / 3)
    )
    assert float(
        overall["organism_and_unit_balanced_mean_absolute_percent_deviation"]
    ) == pytest.approx(25)
    assert units["tank-A"]["paired_observation_count"] == "3"
    assert units["tank-A"]["observed_organism_count"] == "2"
    assert units["tank-A"]["percent_contributing_organism_count"] == "2"
    assert float(units["tank-A"]["mean_signed_bias"]) == pytest.approx(20 / 3)
    assert float(units["tank-A"]["organism_balanced_mean_signed_bias"]) == 5
    assert units["tank-B"]["paired_observation_count"] == "1"
    assert units["tank-B"]["percent_contributing_organism_count"] == "1"
    assert all(row["independent_inference_allowed"] == "false" for row in rows)

    # A comparison with no declared independent units cannot invent balanced N.
    no_units = [
        {
            key: value
            for key, value in pair.items()
            if key not in ("experimental_unit_id", "experimental_unit_type")
        }
        for pair in pairs
    ]
    unregistered = client.post(
        "/api/v1/ecology/paired-count-comparison/report.csv",
        json=_request(no_units),
    )
    assert unregistered.status_code == 200, unregistered.text
    unregistered_rows = list(csv.DictReader(StringIO(unregistered.text)))
    unregistered_overall = next(row for row in unregistered_rows if row["row_type"] == "overall")
    assert not any(row["row_type"] == "declared_unit" for row in unregistered_rows)
    for field in (
        "declared_independent_unit_count",
        "unit_balanced_mean_signed_bias",
        "organism_and_unit_balanced_mean_signed_bias",
        "percent_contributing_independent_unit_count",
    ):
        assert unregistered_overall[field] == ""


def test_csv_directional_votes_distinguish_repeated_images_from_organisms(
    client: TestClient,
) -> None:
    """Opposing image errors can cancel for one organism without being exact matches."""
    pairs = _pairs()
    repeat = dict(pairs[0])
    repeat.update(
        observation_id="image-3",
        reference_source_record_id="human-image-3",
        model_source_record_id="model-image-3",
        reference_count=10,
        model_count=8,
    )
    response = client.post(
        "/api/v1/ecology/paired-count-comparison/report.csv",
        json=_request([*pairs, repeat]),
    )
    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(StringIO(response.text)))
    organism_a = next(
        row
        for row in rows
        if row["row_type"] == "organism_descriptive" and row["organism_id"] == "fragment-A"
    )
    unit = next(row for row in rows if row["row_type"] == "declared_unit")
    overall = next(row for row in rows if row["row_type"] == "overall")
    for row in (organism_a, unit, overall):
        assert row["export_schema_version"] == "ecology-paired-count-csv-0004"
        assert row["independent_inference_allowed"] == "false"
    assert organism_a["repeated_observation_count"] == "1"
    assert organism_a["overcount_pair_count"] == "1"
    assert organism_a["undercount_pair_count"] == "1"
    assert organism_a["exact_match_pair_count"] == "0"
    assert organism_a["balanced_organism_count"] == "1"
    assert organism_a["mean_signed_bias"] == "0.0"
    for row in (unit, overall):
        assert row["paired_observation_count"] == "3"
        assert row["observed_organism_count"] == "2"
        assert row["repeated_observation_count"] == "1"
        assert row["overcount_pair_count"] == "1"
        assert row["undercount_pair_count"] == "2"
        assert row["exact_match_pair_count"] == "0"
        assert row["overcount_organism_count"] == "0"
        assert row["undercount_organism_count"] == "1"
        assert row["balanced_organism_count"] == "1"


def test_csv_escapes_user_supplied_formula_identifiers(client: TestClient) -> None:
    pairs = _pairs()
    pairs[0]["organism_id"] = "=HYPERLINK(1)"
    pairs[0]["observation_id"] = "+SUM(1,2)"
    pairs[0]["reference_source_record_id"] = "@human"
    pairs[0]["model_source_record_id"] = "-model"
    response = client.post(
        "/api/v1/ecology/paired-count-comparison/report.csv", json=_request(pairs)
    )
    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(StringIO(response.text)))
    assert rows[0]["organism_id"] == "'=HYPERLINK(1)"
    assert rows[0]["observation_id"] == "'+SUM(1,2)"
    assert rows[0]["reference_source_record_id"] == "'@human"
    assert rows[0]["model_source_record_id"] == "'-model"
    organism = next(row for row in rows if row["row_type"] == "organism_descriptive")
    assert organism["organism_id"] == "'=HYPERLINK(1)"


def test_saved_csv_workflow_persists_typed_unverified_parity(client: TestClient) -> None:
    project = create_project(client, "Paired count CSV scientific export")
    project_id = str(project["id"])
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    node = next(
        row for row in registry.json() if row["node_type"] == "ecology_paired_count_csv_export"
    )
    assert node["executable"] is True
    assert node["input_ports"][0]["accepted_types"] == ["paired_count_comparison"]
    assert node["output_ports"][0]["accepted_types"] == ["paired_count_comparison_csv"]

    graph = cast(dict[str, Any], _graph())
    graph["nodes"].append({"node_id": "csv-export", "node_type": "ecology_paired_count_csv_export"})
    graph["edges"].append(
        {
            "edge_id": "comparison-csv",
            "source_node_id": "comparison",
            "source_port_id": "comparison",
            "target_node_id": "csv-export",
            "target_port_id": "comparison",
        }
    )
    planned = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert planned.status_code == 200, planned.text
    assert planned.json()["executable"] is True
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
    artifacts = detail.json()["artifacts"]
    comparison = next(
        row["payload_json"] for row in artifacts if row["data_type"] == "paired_count_comparison"
    )
    csv_artifact = next(
        row["payload_json"]
        for row in artifacts
        if row["data_type"] == "paired_count_comparison_csv"
    )
    standalone = client.post(
        "/api/v1/ecology/paired-count-comparison/report.csv",
        json=_request(_pairs()),
    )
    assert standalone.status_code == 200, standalone.text
    assert csv_artifact["schema_version"] == "ecology-paired-count-csv-0004"
    assert csv_artifact["csv_text"] == standalone.text
    assert "organism_descriptive" in csv_artifact["csv_text"]
    assert "independent_inference_allowed" in csv_artifact["csv_text"]
    assert (
        csv_artifact["source_input_sha256"]
        == (comparison["analysis_provenance"]["canonical_input_sha256"])
    )
    assert csv_artifact["csv_sha256"] == hashlib.sha256(standalone.content).hexdigest()
    assert csv_artifact["evidence_level"] == "caller_supplied_unverified"
    assert csv_artifact["review_status"] == "requires_source_verification"
    assert csv_artifact["independent_unit_inference_allowed"] is False

    graph["nodes"].append({"node_id": "dataset", "node_type": "dataset_version_create"})
    graph["edges"].append(
        {
            "edge_id": "csv-into-reviewed",
            "source_node_id": "csv-export",
            "source_port_id": "csv",
            "target_node_id": "dataset",
            "target_port_id": "reviewed",
        }
    )
    rejected = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/validate", json=graph)
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["valid"] is False
    assert any(issue["code"] == "incompatible_port_types" for issue in rejected.json()["issues"])


def test_csv_rechecks_tampered_results_and_provenance() -> None:
    comparison = compare_paired_counts(
        PairedCountComparisonRequest.model_validate(_request(_pairs()))
    )
    tampered = comparison.model_copy(update={"mean_signed_bias": 999.0})
    with pytest.raises(ValidationError, match="integrity"):
        render_paired_count_csv(tampered)
    bad_roster = comparison.model_copy(
        update={
            "analysis_provenance": comparison.analysis_provenance.model_copy(
                update={"source_record_ids": ["fabricated"]}
            )
        }
    )
    with pytest.raises(ValidationError, match="source roster"):
        render_paired_count_csv(bad_roster)


def test_workflow_csv_type_is_declared_and_pydantic_validated() -> None:
    """Prevent a registry-only port type from breaking every Workflow Builder graph."""
    assert "paired_count_comparison_csv" in get_args(WorkflowDataType)
    port = WorkflowPortDefinition(
        port_id="csv",
        display_name="Unverified paired count CSV",
        accepted_types=["paired_count_comparison_csv"],
    )
    assert port.accepted_types == ["paired_count_comparison_csv"]

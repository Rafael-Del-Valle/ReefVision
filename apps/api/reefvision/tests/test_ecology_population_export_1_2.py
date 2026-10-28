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
from reefvision.services import ecology_population_export as exporter
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


@pytest.mark.parametrize("column_delta", [-1, 1])
def test_population_csv_fails_closed_on_header_row_drift(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    column_delta: int,
) -> None:
    """Never emit misaligned scientific CSV when the export schema drifts."""
    source = _dated_artifact(client)
    columns = exporter._COLUMNS
    altered = columns[:-1] if column_delta < 0 else (*columns, "unexpected_column")
    monkeypatch.setattr(exporter, "_COLUMNS", altered)
    with pytest.raises(ValidationError, match="column count"):
        exporter.render_ecology_population_csv(source)


def test_population_csv_rejects_duplicate_column_names(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same-length schema drift must not create ambiguous scientific fields."""
    source = _dated_artifact(client)
    columns = list(exporter._COLUMNS)
    columns[-1] = columns[0]
    monkeypatch.setattr(exporter, "_COLUMNS", tuple(columns))
    with pytest.raises(ValidationError, match="duplicate column"):
        exporter.render_ecology_population_csv(source)


@pytest.mark.parametrize(
    ("field", "forged_value", "error"),
    [
        ("source_fingerprint_rechecked", "false", "verified evidence or inference"),
        ("evidence_level", "verified", "verified evidence or inference"),
        ("review_gate", "approved", "verified evidence or inference"),
        (
            "independent_unit_inference_allowed",
            "true",
            "verified evidence or inference",
        ),
        ("declared_unit_count", 2, "declared-unit denominator"),
        ("contributing_organism_count", -1, "declared-unit denominator"),
        ("row_type", "synthetic_replicate", "row type"),
    ],
)
def test_population_csv_refuses_invalid_scientific_row_before_writing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    forged_value: object,
    error: str,
) -> None:
    """Export guards also apply if future serializers accidentally mislabel rows."""
    source = _dated_artifact(client)
    original = exporter._write_checked_row

    def corrupt_first_row(writer: Any, values: tuple[object, ...]) -> None:
        corrupted = list(values)
        corrupted[exporter._COLUMNS.index(field)] = forged_value
        original(writer, tuple(corrupted))

    monkeypatch.setattr(exporter, "_write_checked_row", corrupt_first_row)
    with pytest.raises(ValidationError, match=error):
        exporter.render_ecology_population_csv(source)


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
    assert all(row["source_declared_experimental_unit_count"] == "0" for row in rows)
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


def test_population_csv_carries_rechecked_source_lineage_for_all_rows(
    client: TestClient,
) -> None:
    """Both excluded and population rows expose the source audit chain."""
    source = _dated_artifact(client)
    rows = _rows(render_ecology_population_csv(source))
    assert {row["export_schema_version"] for row in rows} == {"ecology-population-export-0004"}
    assert {row["row_type"] for row in rows} == {"declared_unit", "population_stratum"}
    report = source.candidate_report
    assert report is not None
    expected = {
        "source_fingerprint_rechecked": "true",
        "source_fingerprint_contract": source.source_fingerprint_contract,
        "source_candidate_count": str(source.candidate_count),
        "source_image_count": str(report.source_image_count),
        "source_organism_count": str(report.source_organism_count),
        "source_excluded_count": str(report.excluded_source_count),
        "source_declared_experimental_unit_count": str(report.declared_experimental_unit_count),
        "source_date_qc_pass_series_count": str(report.date_qc_pass_series_count),
        "source_excluded_series_count": str(report.excluded_series_count),
        "source_registry_history_sha256": source.source_registry_history_sha256 or "",
        "source_image_evidence_sha256": source.source_image_evidence_sha256 or "",
        "source_annotation_evidence_sha256": source.source_annotation_evidence_sha256 or "",
        "source_calibration_evidence_sha256": source.source_calibration_evidence_sha256 or "",
    }
    # Two source observations describe one organism in one declared tank.
    # They must not become two independent biological replicates in CSV.
    assert source.candidate_count == 2
    assert report.source_image_count == 2
    assert report.source_organism_count == 1
    population = next(row for row in rows if row["row_type"] == "population_stratum")
    assert population["declared_unit_count"] == "1"
    assert population["source_declared_experimental_unit_count"] == "1"
    assert population["source_date_qc_pass_series_count"] == "1"
    assert population["source_excluded_series_count"] == "0"
    for row in rows:
        for field, value in expected.items():
            assert row[field] == value

    tampered = source.model_copy(update={"source_calibration_evidence_sha256": "0" * 64})
    with pytest.raises(ValidationError, match="source input fingerprint"):
        render_ecology_population_csv(tampered)


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
        {"units_missing_parent_colony": []},
        {"units_missing_parent_colony": ["forged-tank-B"]},
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
    # The original fixture genuinely lacks parent lineage. Only a changed
    # missing-parent roster is tampering; its true ["tank-A"] value is valid.
    with pytest.raises(ValidationError, match="Projected population summaries"):
        render_ecology_population_csv(forged)


def test_population_csv_preserves_true_missing_parent_review(client: TestClient) -> None:
    """Unknown parentage is disclosed and never treated as independent evidence."""
    source = _dated_artifact(client)
    summary = source.projected_population_summaries[0]
    assert summary.units_missing_parent_colony == ["tank-A"]
    assert "missing_parent_colony" in summary.design_review_blockers
    row = next(
        row
        for row in _rows(render_ecology_population_csv(source))
        if row["row_type"] == "population_stratum"
    )
    assert json.loads(row["units_missing_parent_colony_json"]) == ["tank-A"]
    assert "missing_parent_colony" in json.loads(row["design_review_blockers_json"])
    assert row["independent_unit_inference_allowed"] == "false"


@pytest.mark.parametrize(
    ("field", "forged_value", "error"),
    [
        ("experimental_unit_ids_json", '["tank-A","tank-B"]', "population unit roster"),
        ("units_missing_parent_colony_json", "[]", "missing-parent review blocker"),
        ("units_missing_parent_colony_json", '["forged-tank-B"]', "missing-parent roster"),
        (
            "design_review_blockers_json",
            '["independence_not_authenticated","single_declared_unit"]',
            "missing-parent review blocker",
        ),
        (
            "design_review_blockers_json",
            '["single_declared_unit","missing_parent_colony"]',
            "independent-unit review blockers",
        ),
    ],
)
def test_population_csv_rejects_serialized_review_roster_drift(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    forged_value: str,
    error: str,
) -> None:
    """A serializer bug must not suppress review or inflate independent units."""
    source = _dated_artifact(client)
    original = exporter._write_checked_row

    def corrupt_population_row(writer: Any, values: tuple[object, ...]) -> None:
        if values[exporter._COLUMNS.index("row_type")] != "population_stratum":
            original(writer, values)
            return
        altered = list(values)
        altered[exporter._COLUMNS.index(field)] = forged_value
        original(writer, tuple(altered))

    monkeypatch.setattr(exporter, "_write_checked_row", corrupt_population_row)
    with pytest.raises(ValidationError, match=error):
        render_ecology_population_csv(source)


@pytest.mark.parametrize(
    ("forged_fields", "error"),
    [
        ({"parent_colony_keys_json": "not-json"}, "parent-colony roster"),
        ({"parent_colony_keys_json": '["parent-A","parent-A"]'}, "parent-colony roster"),
        ({"parent_colony_keys_json": '[""]'}, "parent-colony roster"),
        ({"shared_parent_colony_keys_json": '["unknown-parent"]'}, "parent-colony roster"),
        (
            {
                "parent_colony_keys_json": '["parent-A"]',
                "shared_parent_colony_keys_json": '["parent-A","parent-A"]',
            },
            "parent-colony roster",
        ),
        (
            {
                "design_review_blockers_json": (
                    '["independence_not_authenticated","single_declared_unit",'
                    '"missing_parent_colony","missing_parent_colony"]'
                ),
            },
            "review blockers",
        ),
    ],
)
def test_population_csv_rejects_forged_parent_lineage_at_serialization(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    forged_fields: dict[str, str],
    error: str,
) -> None:
    """A reserialized population row cannot conceal shared-parent review."""
    source = _dated_artifact(client)
    original = exporter._write_checked_row

    def corrupt_population_row(writer: Any, values: tuple[object, ...]) -> None:
        if values[exporter._COLUMNS.index("row_type")] != "population_stratum":
            original(writer, values)
            return
        altered = list(values)
        for field, forged_value in forged_fields.items():
            altered[exporter._COLUMNS.index(field)] = forged_value
        original(writer, tuple(altered))

    monkeypatch.setattr(exporter, "_write_checked_row", corrupt_population_row)
    with pytest.raises(ValidationError, match=error):
        render_ecology_population_csv(source)


@pytest.mark.parametrize(
    ("field", "forged_value", "error"),
    [
        ("experimental_unit_ids_json", '["tank-B"]', "declared-unit roster"),
        ("experimental_unit_ids_json", '["tank-A","tank-B"]', "declared-unit roster"),
        ("design_review_blockers_json", "[]", "declared-unit review gate"),
        ("declared_unit_count", 0, "candidate declared-unit"),
        ("contributing_organism_count", 0, "candidate declared-unit"),
        ("mean_absolute_change", "", "candidate declared-unit"),
        ("unit_status", "incomplete_followup", "excluded declared-unit"),
    ],
)
def test_population_csv_rejects_serialized_declared_unit_drift(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    forged_value: object,
    error: str,
) -> None:
    """CSV rows cannot invent or suppress unit eligibility and scientific review."""
    source = _dated_artifact(client)
    original = exporter._write_checked_row

    def corrupt_unit_row(writer: Any, values: tuple[object, ...]) -> None:
        if values[exporter._COLUMNS.index("row_type")] != "declared_unit":
            original(writer, values)
            return
        altered = list(values)
        altered[exporter._COLUMNS.index(field)] = forged_value
        original(writer, tuple(altered))

    monkeypatch.setattr(exporter, "_write_checked_row", corrupt_unit_row)
    with pytest.raises(ValidationError, match=error):
        render_ecology_population_csv(source)


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

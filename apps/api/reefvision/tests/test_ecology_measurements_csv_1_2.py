"""Source-level ecological CSV export: standalone, saved workflow and QC gates."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaValidationError

from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
)
from reefvision.services.ecology_candidate_report_export import render_ecology_series_qc_csv
from reefvision.services.ecology_candidate_measurements_export import (
    MEASUREMENT_CSV_SCHEMA_VERSION,
    _utc_capture,
    four_layer_source_digests_present,
    render_ecology_measurements_csv,
)
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def _rows(csv_text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(csv_text)))


def test_measurement_csv_preserves_all_source_links_and_saved_workflow_parity(
    client: TestClient,
) -> None:
    project_id, source = _source(client)
    path = f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    standalone = client.get(path)
    assert standalone.status_code == 200, standalone.text
    csv_response = client.get(path + "/measurements.csv")
    assert csv_response.status_code == 200, csv_response.text
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in csv_response.headers["content-disposition"]
    rows = _rows(csv_response.text)
    payload = standalone.json()
    assert len(rows) == payload["candidate_count"] == 2
    assert [row["metric"] for row in rows] == ["box_height", "box_width"]
    for row in rows:
        assert row["export_schema_version"] == MEASUREMENT_CSV_SCHEMA_VERSION
        assert row["project_id"] == project_id
        assert row["source_input_sha256"] == payload["input_sha256"]
        assert row["report_sha256"] == payload["candidate_report"]["report_sha256"]
        assert row["source_fingerprint_rechecked"] == "true"
        assert row["source_fingerprint_contract"] == payload["source_fingerprint_contract"]
        assert row["source_registry_history_sha256"] == payload["source_registry_history_sha256"]
        assert row["source_image_evidence_sha256"] == payload["source_image_evidence_sha256"]
        assert (
            row["source_annotation_evidence_sha256"] == payload["source_annotation_evidence_sha256"]
        )
        assert (
            row["source_calibration_evidence_sha256"]
            == payload["source_calibration_evidence_sha256"]
        )
        assert row["four_layer_source_digests_present"] == "true"
        assert row["independent_unit_inference_allowed"] == "false"
        assert row["organism_key"] == source.organism_key
        assert row["identity_revision"] == str(source.identity_revision)
        assert row["image_id"] == source.image_id
        assert row["image_sha256"] == source.image_sha256
        assert row["annotation_evidence_id"] == source.annotation_evidence_id
        assert row["calibration_evidence_id"] == source.calibration_evidence_id
        assert row["annotation_sha256"] == source.annotation_sha256
        assert row["calibration_sha256"] == source.calibration_sha256
        assert row["capture_timestamp_utc"] == ""
        assert row["capture_time_status"] == "missing"
        assert row["sampling_date_qc_status"] == "missing_timestamps"
        assert row["evidence_level"] == "linked_unverified"
        assert row["review_gate"] == "scientist_review_required"

    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    persisted = EcologyMeasurementCandidatesResponse.model_validate(artifacts[0]["payload_json"])
    assert render_ecology_measurements_csv(persisted) == csv_response.text


def test_measurement_csv_is_stable_under_qc_series_permutation(
    client: TestClient,
) -> None:
    """Equivalent QC ordering must not change a reproducible source CSV."""
    project_id, _ = _source(client)
    path = f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    response = client.get(path)
    assert response.status_code == 200, response.text
    payload = EcologyMeasurementCandidatesResponse.model_validate(response.json())
    assert len(payload.sampling_date_qc) > 1
    original = render_ecology_measurements_csv(payload)
    permuted = payload.model_copy(
        update={"sampling_date_qc": list(reversed(payload.sampling_date_qc))}
    )
    assert render_ecology_measurements_csv(permuted) == original


def test_measurement_csv_rejects_modified_source_even_if_qc_counts_unchanged(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200
    payload = EcologyMeasurementCandidatesResponse.model_validate(response.json())
    candidate = payload.candidates[0]
    altered = payload.model_copy(
        update={
            "candidates": [
                candidate.model_copy(update={"value": candidate.value + 0.25}),
                *payload.candidates[1:],
            ]
        }
    )
    with pytest.raises(ValidationError, match="source input fingerprint"):
        render_ecology_measurements_csv(altered)


def test_measurement_csv_discloses_partial_historical_lineage_without_verification(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200, response.text
    source = EcologyMeasurementCandidatesResponse.model_validate(response.json())
    assert four_layer_source_digests_present(source) is True

    # Legacy artifacts can be exported with a clearly disclosed incomplete
    # lineage; no rechecked source or independent biological unit is invented.
    legacy = source.model_copy(
        update={
            "source_fingerprint_contract": None,
            "source_image_evidence_sha256": None,
            "source_annotation_evidence_sha256": None,
        }
    )
    rows = _rows(render_ecology_measurements_csv(legacy))
    assert rows
    for row in rows:
        assert row["source_fingerprint_rechecked"] == "false"
        assert row["four_layer_source_digests_present"] == "false"
        assert row["independent_unit_inference_allowed"] == "false"
        assert row["review_gate"] == "scientist_review_required"


@pytest.mark.parametrize("invalid_digest", [None, "0" * 63, "z" * 64])
def test_measurement_lineage_presence_requires_four_well_formed_digests(
    client: TestClient, invalid_digest: str | None
) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200, response.text
    source = EcologyMeasurementCandidatesResponse.model_validate(response.json())
    altered = source.model_copy(update={"source_calibration_evidence_sha256": invalid_digest})
    assert four_layer_source_digests_present(altered) is False


def test_measurement_csv_empty_project_has_only_header(client: TestClient) -> None:
    project_id = str(create_project(client, "Empty ecological source export")["id"])
    path = f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    response = client.get(path + "/measurements.csv")
    assert response.status_code == 200, response.text
    assert _rows(response.text) == []
    assert "source_input_sha256" in response.text


@pytest.mark.parametrize(
    ("capture", "status", "error"),
    [
        (datetime(2026, 4, 3, 8), "timezone_aware", "lacks timezone"),
        (None, "timezone_aware", "missing its capture timestamp"),
        (datetime(2026, 4, 3, 8, tzinfo=UTC), "missing", "conflicts"),
    ],
)
def test_measurement_csv_rejects_ambiguous_capture_metadata(
    capture: datetime | None, status: str, error: str
) -> None:
    with pytest.raises(ValidationError, match=error):
        _utc_capture(capture, status)


def test_measurement_csv_normalizes_utc_timestamp() -> None:
    value = _utc_capture(datetime(2026, 4, 3, 8, tzinfo=UTC), "timezone_aware")
    assert value == "2026-04-03T08:00:00Z"


def test_executable_saved_workflow_exports_typed_unverified_csv(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    node_registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert node_registry.status_code == 200
    node = next(
        item
        for item in node_registry.json()
        if item["node_type"] == "ecology_measurement_csv_export"
    )
    assert node["executable"] is True
    assert node["input_ports"][0]["accepted_types"] == ["ecology_measurement_candidates"]
    assert node["output_ports"][0]["accepted_types"] == ["ecology_measurement_csv"]

    graph: dict[str, Any] = {
        "graph_id": "ecology-source-measurements-export-1-2",
        "name": "Traceable projected source measurements",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "identity", "node_type": "ecology_identity_registry_source"},
            {"node_id": "export", "node_type": "ecology_measurement_csv_export"},
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
        row for row in detail.json()["artifacts"] if row["data_type"] == "ecology_measurement_csv"
    ]
    assert len(artifacts) == 1
    payload = artifacts[0]["payload_json"]
    assert payload["schema_version"] == MEASUREMENT_CSV_SCHEMA_VERSION
    assert payload["project_id"] == project_id
    assert payload["source_fingerprint_rechecked"] is True
    assert payload["source_fingerprint_contract"] is not None
    assert payload["four_layer_source_digests_present"] is True
    assert payload["independent_unit_inference_allowed"] is False
    for field in (
        "source_registry_history_sha256",
        "source_image_evidence_sha256",
        "source_annotation_evidence_sha256",
        "source_calibration_evidence_sha256",
    ):
        assert payload[field] is not None
        assert len(payload[field]) == 64
    assert payload["evidence_level"] == "linked_unverified"
    assert payload["review_gate"] == "scientist_review_required"
    standalone = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates/measurements.csv"
    )
    assert standalone.status_code == 200, standalone.text
    assert payload["csv_text"] == standalone.text

    # An exported unverified CSV is not a verified-dataset input.
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
    assert invalid.status_code == 200, invalid.text
    assert invalid.json()["valid"] is False
    assert any(issue["code"] == "incompatible_port_types" for issue in invalid.json()["issues"])


def test_current_lineage_digest_contract_fails_closed_for_api_and_saved_artifacts(
    client: TestClient,
) -> None:
    """Current evidence cannot drop a lineage layer, even after re-signing."""
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_fingerprint_contract"] == "ecology-measurement-candidates-0021"
    assert four_layer_source_digests_present(
        EcologyMeasurementCandidatesResponse.model_validate(payload)
    )

    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    saved = next(
        row["payload_json"]
        for row in workflow["artifacts"]
        if row["data_type"] == "ecology_measurement_candidates"
    )
    assert saved == payload

    for field in (
        "source_registry_history_sha256",
        "source_image_evidence_sha256",
        "source_annotation_evidence_sha256",
        "source_calibration_evidence_sha256",
    ):
        for invalid in (None, "0" * 63, "z" * 64):
            for serialized in (payload, saved):
                tampered = {**serialized, field: invalid}
                with pytest.raises(SchemaValidationError, match="four complete lineage"):
                    EcologyMeasurementCandidatesResponse.model_validate(tampered)
            # The exporter must also reject unchecked model_copy mutations,
            # including an artifact with an otherwise recomputed source hash.
            source = EcologyMeasurementCandidatesResponse.model_validate(payload)
            bypass = source.model_copy(update={field: invalid})
            with pytest.raises(ValidationError, match="four complete lineage"):
                render_ecology_series_qc_csv(bypass)
            with pytest.raises(ValidationError, match="four complete lineage"):
                render_ecology_measurements_csv(bypass)

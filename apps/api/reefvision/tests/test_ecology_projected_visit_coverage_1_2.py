"""Observed-date coverage for source-linked, unverified ecological measurements."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidate,
    EcologyMeasurementCandidatesResponse,
)
from reefvision.services.ecology_measurement_candidates import (
    summarize_projected_endpoint_changes,
    summarize_projected_visit_coverage,
    summarize_sampling_date_qc,
)
from reefvision.tests.test_ecology_calibration_evidence_1_2 import (
    _link_calibration,
    _prepared_annotation,
    _save_calibration,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow


def _source(client: TestClient) -> tuple[str, EcologyMeasurementCandidate]:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    linked = _link_calibration(client, project_id, annotation)
    assert linked.status_code == 201, linked.text
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert response.status_code == 200, response.text
    return project_id, EcologyMeasurementCandidate.model_validate(response.json()["candidates"][0])


def test_visit_coverage_is_typed_in_api_and_persisted_saved_workflow(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    response = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    payload = response.json()
    # Imported image without an authenticated timezone is not a dated visit.
    assert payload["projected_visit_coverage"] == []
    assert payload["review_gate"] == "scientist_review_required"
    assert payload["evidence_level"] == "linked_unverified"
    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200
    source_node = next(
        node for node in registry.json() if node["node_type"] == "ecology_identity_registry_source"
    )
    assert any(
        port["port_id"] == "measurement_candidates"
        and port["accepted_types"] == ["ecology_measurement_candidates"]
        for port in source_node["output_ports"]
    )
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == payload
    # Backward-compatible decoding of previously persisted typed artifacts.
    legacy = dict(payload)
    legacy.pop("projected_visit_coverage")
    parsed = EcologyMeasurementCandidatesResponse.model_validate(legacy)
    assert parsed.projected_visit_coverage == []


def test_visit_coverage_reports_linked_gaps_without_inferring_absence(
    client: TestClient,
) -> None:
    _, source = _source(client)
    first = source.model_copy(
        update={
            "organism_key": "A",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-1",
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    followup = first.model_copy(
        update={
            "image_id": "A-day4",
            "image_sha256": "a" * 64,
            "capture_timestamp_utc": datetime(2026, 4, 4, 9, tzinfo=UTC),
        }
    )
    repeat = first.model_copy(
        update={
            "image_id": "A-repeat",
            "image_sha256": "b" * 64,
            "capture_timestamp_utc": datetime(2026, 4, 3, 4, tzinfo=timezone(-timedelta(hours=4))),
        }
    )
    other = first.model_copy(
        update={"organism_key": "B", "image_id": "B-day3", "image_sha256": "c" * 64}
    )
    undated = other.model_copy(
        update={
            "image_id": "B-undated",
            "image_sha256": "d" * 64,
            "capture_timestamp_utc": None,
            "capture_time_status": "missing",
        }
    )
    last_only = followup.model_copy(
        update={"organism_key": "C", "image_id": "C-day4", "image_sha256": "e" * 64}
    )
    rows = [last_only, undated, repeat, first, followup, other]
    coverage = summarize_projected_visit_coverage(rows)
    assert coverage == summarize_projected_visit_coverage(list(reversed(rows)))
    assert [row.sampling_date_utc for row in coverage] == ["2026-04-03", "2026-04-04"]
    assert [row.linked_measurement_count for row in coverage] == [3, 2]
    assert all(row.series_organism_keys == ["A", "B", "C"] for row in coverage)
    assert [row.measured_organism_keys for row in coverage] == [["A", "B"], ["A", "C"]]
    assert [row.no_linked_measurement_organism_keys for row in coverage] == [
        ["C"],
        ["B"],
    ]
    assert all(row.undated_organism_keys == ["B"] for row in coverage)
    assert [row.same_day_repeat_organism_keys for row in coverage] == [["A"], []]
    assert all(row.evidence_level == "linked_unverified" for row in coverage)
    assert all(row.review_gate == "scientist_review_required" for row in coverage)
    # Missing links never become zero-valued measurements or biological growth.
    assert summarize_projected_endpoint_changes(rows, summarize_sampling_date_qc(rows)) == []


def test_visit_coverage_never_invents_an_independent_sampling_unit(
    client: TestClient,
) -> None:
    _, source = _source(client)
    dated = source.model_copy(
        update={
            "capture_timestamp_utc": datetime(2026, 4, 3, 8, tzinfo=UTC),
            "capture_time_status": "timezone_aware",
        }
    )
    # Unassigned specimens cannot be pooled as if "None" were a real tank.
    assert summarize_projected_visit_coverage([dated]) == []
    technical = dated.model_copy(
        update={"experimental_unit_type": "video_frame", "experimental_unit_id": "frame-1"}
    )
    assert summarize_projected_visit_coverage([technical]) == []

    tank_a = dated.model_copy(
        update={
            "organism_key": "A",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "tank-A",
        }
    )
    tank_b = tank_a.model_copy(
        update={
            "organism_key": "B",
            "experimental_unit_id": "tank-B",
            "image_id": "tank-B-image",
            "image_sha256": "f" * 64,
        }
    )
    coverage = summarize_projected_visit_coverage([tank_b, tank_a])
    assert [row.experimental_unit_id for row in coverage] == ["tank-A", "tank-B"]
    assert [row.series_organism_keys for row in coverage] == [["A"], ["B"]]
    assert all(row.no_linked_measurement_organism_keys == [] for row in coverage)

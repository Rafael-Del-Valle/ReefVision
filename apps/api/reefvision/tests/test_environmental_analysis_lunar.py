"""Persisted lunar analyses use the same deterministic, qualified calculator."""

from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.db.models.environmental_analysis import EnvironmentalAnalysisResult
from reefvision.tests.test_annotations import create_project

# United States Naval Observatory primary-phase reference instants (UTC).
USNO_REFERENCES = [
    ("2024-03-25T07:00:00Z", "full_moon", 1.0),
    ("2024-04-02T03:15:00Z", "last_quarter", 0.5),
    ("2024-04-08T18:21:00Z", "new_moon", 0.0),
    ("2024-04-15T19:13:00Z", "first_quarter", 0.5),
]


def _base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/environment/analyses"


def test_persisted_lunar_batch_is_immutable_listed_and_exportable(client: TestClient) -> None:
    project = create_project(client, "Persisted lunar study")
    response = client.post(
        f"{_base(project['id'])}/lunar-context",
        json={
            "name": "USNO reference batch",
            "observed_at": [reference[0] for reference in USNO_REFERENCES],
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    definition = data["definition"]
    results = data["results"]
    assert definition["analysis_kind"] == "lunar_context"
    assert definition["calculation_version"] == ("reefvision-low-precision-ecliptic-longitude-1")
    assert len(definition["definition_sha256"]) == 64
    assert len(results) == len(USNO_REFERENCES)

    for result, (_, expected_phase, expected_illumination) in zip(
        results, USNO_REFERENCES, strict=True
    ):
        assert result["analysis_kind"] == "lunar_context"
        assert result["payload"]["phase"] == expected_phase
        assert abs(result["payload"]["illuminated_fraction"] - expected_illumination) < 0.15
        assert result["source_record_ids"] == []
        assert result["source_analysis_result_ids"] == []
        assert result["quality_control"]["status"] == "accepted"
        assert result["uncertainty"]["type"] == "methodological"
        assert len(result["content_sha256"]) == 64

    definitions = client.get(f"{_base(project['id'])}/definitions")
    assert definitions.status_code == 200, definitions.text
    assert definitions.json()["items"] == [definition]
    listed = client.get(
        f"{_base(project['id'])}/results", params={"analysis_kind": "lunar_context"}
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 4
    result_id = results[0]["id"]
    assert client.get(f"{_base(project['id'])}/results/{result_id}").json() == results[0]

    export = client.get(f"{_base(project['id'])}/results/{result_id}.csv")
    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith("text/csv")
    assert "full_moon" in export.text
    assert results[0]["content_sha256"] in export.text


def test_lunar_year_boundary_and_timezone_equivalence_persist_identically(
    client: TestClient,
) -> None:
    project = create_project(client, "Lunar year boundary")
    url = f"{_base(project['id'])}/lunar-context"
    utc = client.post(
        url,
        json={
            "name": "UTC identity",
            "observed_at": ["2024-12-31T23:30:00Z"],
        },
    )
    offset = client.post(
        url,
        json={
            "name": "Offset identity",
            "observed_at": ["2025-01-01T00:30:00+01:00"],
        },
    )
    boundary = client.post(
        url,
        json={"name": "New year", "observed_at": ["2025-01-01T00:30:00Z"]},
    )
    assert utc.status_code == offset.status_code == boundary.status_code == 201
    utc_result = utc.json()["results"][0]
    offset_result = offset.json()["results"][0]
    assert utc_result["observed_at"] == offset_result["observed_at"]
    assert utc_result["payload"] == offset_result["payload"]
    assert boundary.json()["results"][0]["observed_at"].startswith("2025-01-01T00:30:00")


def test_tampered_analysis_result_and_cross_project_access_are_rejected(
    client: TestClient,
) -> None:
    project = create_project(client, "Analysis integrity")
    other = create_project(client, "Other analysis project")
    created = client.post(
        f"{_base(project['id'])}/lunar-context",
        json={"name": "One result", "observed_at": ["2024-04-08T18:21:00Z"]},
    )
    assert created.status_code == 201, created.text
    result_id = created.json()["results"][0]["id"]
    assert client.get(f"{_base(other['id'])}/results/{result_id}").status_code == 404

    with client.app.state.session_factory() as session:
        row = session.get(EnvironmentalAnalysisResult, result_id)
        assert row is not None
        row.payload_json = {**row.payload_json, "phase": "full_moon"}
        session.commit()
    tampered = client.get(f"{_base(project['id'])}/results/{result_id}")
    assert tampered.status_code == 409, tampered.text


def test_lunar_batch_rejects_duplicates_and_is_atomic(client: TestClient) -> None:
    project = create_project(client, "Atomic lunar batch")
    base = _base(project["id"])
    rejected = client.post(
        f"{base}/lunar-context",
        json={
            "name": "Duplicate instants",
            "observed_at": ["2024-04-08T18:21:00Z", "2024-04-08T14:21:00-04:00"],
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert client.get(f"{base}/definitions").json()["total"] == 0
    assert client.get(f"{base}/results").json()["total"] == 0

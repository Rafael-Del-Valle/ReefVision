from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models.scientific_record import ScientificRecord
from reefvision.services.scientific_data import content_hash
from reefvision.tests.test_annotations import create_project, import_one


def scientific_record(
    variable: str,
    value: float,
    unit: str,
    **overrides: object,
) -> dict[str, object]:
    return {
        "variable": variable,
        "value": value,
        "unit": unit,
        "observed_at": "2026-04-03T13:00:00Z",
        "source_kind": "observed",
        "provenance": {
            "source": "Reef survey",
            "dataset_id": "survey-2026",
            "acquired_at": "2026-04-03T13:05:00Z",
        },
        **overrides,
    }


def add_records(
    client: TestClient, project_id: str, records: list[dict[str, object]]
) -> list[dict]:
    response = client.post(
        f"/api/v1/projects/{project_id}/scientific-records", json={"records": records}
    )
    assert response.status_code == 201, response.text
    return response.json()["items"]


def create_density_definition(client: TestClient, project_id: str) -> dict:
    response = client.post(
        f"/api/v1/projects/{project_id}/computed-metric-definitions",
        json={
            "name": "Organism density",
            "expression": "organisms / surveyed_area",
            "inputs": [
                {"symbol": "organisms", "dimension": "count"},
                {"symbol": "surveyed_area", "dimension": "area"},
            ],
            "output_unit": "count/m2",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_definition_calculation_listing_and_csv_preserve_scientific_snapshot(
    client: TestClient,
) -> None:
    project = create_project(client, "Metric project")
    organisms, area = add_records(
        client,
        project["id"],
        [
            scientific_record(
                "organism_count",
                20,
                "count",
                uncertainty={"value": 2, "kind": "standard_deviation"},
            ),
            scientific_record(
                "surveyed_area",
                100,
                "cm2",
                uncertainty={"value": 5, "kind": "standard_deviation"},
            ),
        ],
    )
    definition = create_density_definition(client, project["id"])
    assert definition["formula_version"] == "reefvision-safe-arithmetic-1"
    assert len(definition["definition_sha256"]) == 64

    calculated = client.post(
        f"/api/v1/projects/{project['id']}/computed-metric-definitions/"
        f"{definition['id']}/calculate",
        json={"inputs": {"organisms": organisms["id"], "surveyed_area": area["id"]}},
    )
    assert calculated.status_code == 201, calculated.text
    result = calculated.json()
    assert result["value"] == pytest.approx(2000)
    assert result["unit"] == "count/m2"
    assert result["normalized_value"] == pytest.approx(2000)
    assert result["uncertainty"] == pytest.approx(223.60679775)
    assert result["observed_at"] == "2026-04-03T13:00:00Z"
    assert result["subject"] == {}
    assert result["input_record_ids"] == {
        "organisms": organisms["id"],
        "surveyed_area": area["id"],
    }
    assert result["input_snapshot"]["surveyed_area"]["unit"] == "cm2"
    assert result["input_snapshot"]["surveyed_area"]["normalized_unit"] == "m2"
    assert result["provenance"]["definition_sha256"] == definition["definition_sha256"]
    assert len(result["content_sha256"]) == 64

    definitions = client.get(
        f"/api/v1/projects/{project['id']}/computed-metric-definitions?limit=1"
    ).json()
    results = client.get(f"/api/v1/projects/{project['id']}/computed-metric-results?limit=1").json()
    assert definitions == {"items": [definition], "total": 1}
    assert results == {"items": [result], "total": 1}

    exported = client.get(f"/api/v1/projects/{project['id']}/computed-metric-results.csv")
    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    assert definition["definition_sha256"] in exported.text
    assert organisms["id"] in exported.text
    assert "reefvision-safe-arithmetic-1" in exported.text


@pytest.mark.parametrize(
    ("expression", "output_unit", "message"),
    [
        ("count + area", "count", "compatible dimensions"),
        ("count / area", "m", "output unit"),
        ("__import__('os')", "count", "not allowed"),
    ],
)
def test_definition_rejects_invalid_formula_before_persistence(
    client: TestClient, expression: str, output_unit: str, message: str
) -> None:
    project = create_project(client, "Invalid formula")
    response = client.post(
        f"/api/v1/projects/{project['id']}/computed-metric-definitions",
        json={
            "name": "Invalid",
            "expression": expression,
            "inputs": [
                {"symbol": "count", "dimension": "count"},
                {"symbol": "area", "dimension": "area"},
            ],
            "output_unit": output_unit,
        },
    )
    assert response.status_code == 400, response.text
    assert message in response.json()["detail"]
    assert (
        client.get(f"/api/v1/projects/{project['id']}/computed-metric-definitions").json()["total"]
        == 0
    )


def test_calculation_rejects_foreign_mismatched_and_corrupt_inputs_atomically(
    client: TestClient,
) -> None:
    project = create_project(client, "Strict metric")
    other = create_project(client, "Foreign metric")
    definition = create_density_definition(client, project["id"])
    organism = add_records(
        client, project["id"], [scientific_record("organism_count", 2, "count")]
    )[0]
    foreign_area = add_records(client, other["id"], [scientific_record("surveyed_area", 1, "m2")])[
        0
    ]
    calculate_url = (
        f"/api/v1/projects/{project['id']}/computed-metric-definitions/{definition['id']}/calculate"
    )
    response = client.post(
        calculate_url,
        json={"inputs": {"organisms": organism["id"], "surveyed_area": foreign_area["id"]}},
    )
    assert response.status_code == 400, response.text

    mismatched_area = add_records(
        client,
        project["id"],
        [scientific_record("surveyed_area", 1, "m2", observed_at="2026-04-03T14:00:00Z")],
    )[0]
    response = client.post(
        calculate_url,
        json={"inputs": {"organisms": organism["id"], "surveyed_area": mismatched_area["id"]}},
    )
    assert response.status_code == 400
    assert "observation time" in response.json()["detail"]

    with client.app.state.session_factory() as session:
        row = session.get(ScientificRecord, organism["id"])
        row.payload_json = {**row.payload_json, "value": 200}
        session.commit()
    response = client.post(
        calculate_url,
        json={"inputs": {"organisms": organism["id"], "surveyed_area": mismatched_area["id"]}},
    )
    assert response.status_code == 409
    assert (
        client.get(f"/api/v1/projects/{project['id']}/computed-metric-results").json()["total"] == 0
    )


def _raw_scientific_record(
    project_id: str, subject: dict[str, str], variable: str
) -> ScientificRecord:
    payload = scientific_record(variable, 1, "count", subject=subject)
    payload.update(
        schema_version="1.1.0",
        normalized_value=1,
        normalized_unit="count",
        normalized_uncertainty=None,
        calibration_snapshot=None,
        calibration_sha256=None,
        environmental_cache_key=None,
        qc="accepted",
        qc_flags=[],
        location=None,
        pixel=None,
        depth_m=None,
        depth_reference=None,
        uncertainty=None,
    )
    return ScientificRecord(
        id=str(uuid4()),
        project_id=project_id,
        variable=variable,
        source_kind="observed",
        observed_at=datetime(2026, 4, 3, 13, tzinfo=UTC),
        payload_json=payload,
        content_sha256=content_hash(payload),
        created_at=datetime(2026, 4, 3, 13, 5, tzinfo=UTC),
    )


def test_calculation_never_combines_verified_and_prediction_evidence(
    client: TestClient,
) -> None:
    project = create_project(client, "Evidence separation")
    with client.app.state.session_factory() as session:
        verified = _raw_scientific_record(
            project["id"], {"image_id": str(uuid4()), "annotation_id": str(uuid4())}, "a"
        )
        predicted = _raw_scientific_record(
            project["id"], {"image_id": str(uuid4()), "prediction_id": str(uuid4())}, "b"
        )
        session.add_all([verified, predicted])
        session.commit()
        verified_id, predicted_id = verified.id, predicted.id
    definition_response = client.post(
        f"/api/v1/projects/{project['id']}/computed-metric-definitions",
        json={
            "name": "Separated evidence",
            "expression": "a + b",
            "inputs": [
                {"symbol": "a", "dimension": "count"},
                {"symbol": "b", "dimension": "count"},
            ],
            "output_unit": "count",
        },
    )
    assert definition_response.status_code == 201, definition_response.text
    response = client.post(
        f"/api/v1/projects/{project['id']}/computed-metric-definitions/"
        f"{definition_response.json()['id']}/calculate",
        json={"inputs": {"a": verified_id, "b": predicted_id}},
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"].lower()
    assert "verified" in detail
    assert "prediction" in detail


def test_physical_image_metric_requires_current_calibration(client: TestClient) -> None:
    project = create_project(client, "Calibrated metric")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    calibration_url = f"/api/v1/images/{image_id}/measurement-calibration"
    assert (
        client.put(calibration_url, json={"distance_per_pixel": 0.1, "unit": "mm"}).status_code
        == 200
    )
    lengths = add_records(
        client,
        project["id"],
        [
            scientific_record("length_a", 2, "cm", subject={"image_id": image_id}),
            scientific_record("length_b", 3, "cm", subject={"image_id": image_id}),
        ],
    )
    definition = client.post(
        f"/api/v1/projects/{project['id']}/computed-metric-definitions",
        json={
            "name": "Total length",
            "expression": "a + b",
            "inputs": [
                {"symbol": "a", "dimension": "length"},
                {"symbol": "b", "dimension": "length"},
            ],
            "output_unit": "cm",
        },
    ).json()
    assert (
        client.put(calibration_url, json={"distance_per_pixel": 0.2, "unit": "mm"}).status_code
        == 200
    )
    response = client.post(
        f"/api/v1/projects/{project['id']}/computed-metric-definitions/"
        f"{definition['id']}/calculate",
        json={"inputs": {"a": lengths[0]["id"], "b": lengths[1]["id"]}},
    )
    assert response.status_code == 400, response.text
    assert "current calibration" in response.json()["detail"]


def test_tampered_definition_or_result_is_never_returned_as_valid(client: TestClient) -> None:
    from reefvision.db.models.computed_metric import ComputedMetricDefinition, ComputedMetricResult

    project = create_project(client, "Tamper metric")
    definition = create_density_definition(client, project["id"])
    records = add_records(
        client,
        project["id"],
        [scientific_record("organism_count", 2, "count"), scientific_record("area", 1, "m2")],
    )
    with client.app.state.session_factory() as session:
        row = session.get(ComputedMetricDefinition, definition["id"])
        row.expression = "organisms * surveyed_area"
        session.commit()
    assert (
        client.get(f"/api/v1/projects/{project['id']}/computed-metric-definitions").status_code
        == 409
    )

    with client.app.state.session_factory() as session:
        row = session.get(ComputedMetricDefinition, definition["id"])
        row.expression = "organisms / surveyed_area"
        row.definition_sha256 = content_hash(
            {
                "name": row.name,
                "expression": row.expression,
                "formula_version": row.formula_version,
                "inputs": row.input_spec_json,
                "output_unit": row.output_unit,
            }
        )
        session.commit()
    result = client.post(
        f"/api/v1/projects/{project['id']}/computed-metric-definitions/{definition['id']}/calculate",
        json={"inputs": {"organisms": records[0]["id"], "surveyed_area": records[1]["id"]}},
    )
    assert result.status_code == 201, result.text
    with client.app.state.session_factory() as session:
        row = session.get(ComputedMetricResult, result.json()["id"])
        payload = deepcopy(row.payload_json)
        payload["value"] = 999
        row.payload_json = payload
        session.commit()
    assert (
        client.get(f"/api/v1/projects/{project['id']}/computed-metric-results").status_code == 409
    )

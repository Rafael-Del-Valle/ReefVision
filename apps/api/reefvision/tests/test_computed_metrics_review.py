"""Regression coverage for the computed-metrics scientific review."""

import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from reefvision.db.models import ComputedMetricDefinition
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.services.computed_metrics import ComputedMetricService
from reefvision.services.scientific_data import content_hash
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_computed_metrics import add_records, scientific_record


def definition(client, project_id, expression="a + b", symbols=("a", "b"), unit="m"):
    return client.post(
        f"/api/v1/projects/{project_id}/computed-metric-definitions",
        json={
            "name": "Reviewed metric",
            "expression": expression,
            "inputs": [{"symbol": symbol, "dimension": "length"} for symbol in symbols],
            "output_unit": unit,
        },
    )


def calculate(client, project_id, definition_id, bindings):
    return client.post(
        f"/api/v1/projects/{project_id}/computed-metric-definitions/{definition_id}/calculate",
        json={"inputs": bindings},
    )


def observation(variable="length", value=1, **overrides):
    return scientific_record(
        variable,
        value,
        "m",
        **{
            "location": {"latitude": 25, "longitude": -80},
            "depth_m": 10,
            "depth_reference": "sea_surface",
            **overrides,
        },
    )


def test_definition_checks_dimensions_without_evaluating_dummy_values(client: TestClient):
    project_id = create_project(client, "Symbolic dimensions")["id"]
    response = definition(client, project_id, "x / (a - b)", ("x", "a", "b"), "1")
    assert response.status_code == 201, response.text
    rows = add_records(
        client, project_id, [observation("x", 8), observation("a", 5), observation("b", 1)]
    )
    result = calculate(
        client,
        project_id,
        response.json()["id"],
        dict(zip(("x", "a", "b"), [r["id"] for r in rows], strict=True)),
    )
    assert result.status_code == 201, result.text
    assert result.json()["value"] == 2
    zero = add_records(client, project_id, [observation("b", 5)])[0]
    invalid = calculate(
        client,
        project_id,
        response.json()["id"],
        {"x": rows[0]["id"], "a": rows[1]["id"], "b": zero["id"]},
    )
    assert invalid.status_code == 400
    assert "zero" in invalid.json()["detail"]


@pytest.mark.parametrize(
    "kinds",
    [("bound", "bound"), ("bound", "standard_deviation"), ("standard_error", "standard_deviation")],
)
def test_unsupported_uncertainty_kinds_are_rejected(client, kinds):
    project_id = create_project(client, "Uncertainty kinds")["id"]
    saved = definition(client, project_id).json()
    rows = add_records(
        client,
        project_id,
        [
            observation(f"length_{i}", uncertainty={"value": 0.1, "kind": kind})
            for i, kind in enumerate(kinds)
        ],
    )
    response = calculate(client, project_id, saved["id"], {"a": rows[0]["id"], "b": rows[1]["id"]})
    assert response.status_code == 400, response.text
    assert "uncertainty kind" in response.json()["detail"]
    assert client.get(f"/api/v1/projects/{project_id}/computed-metric-results").json()["total"] == 0


@pytest.mark.parametrize("kind", ["standard_deviation", "standard_error"])
def test_supported_uncertainty_kind_is_preserved(client, kind):
    project_id = create_project(client, "Preserve uncertainty")["id"]
    saved = definition(client, project_id).json()
    rows = add_records(
        client,
        project_id,
        [observation(f"length_{i}", uncertainty={"value": 0.1, "kind": kind}) for i in range(2)],
    )
    response = calculate(client, project_id, saved["id"], {"a": rows[0]["id"], "b": rows[1]["id"]})
    assert response.status_code == 201, response.text
    assert response.json()["provenance"]["uncertainty_kind"] == kind


def test_duplicate_record_bindings_are_rejected(client):
    project_id = create_project(client, "Correlated bindings")["id"]
    saved = definition(client, project_id).json()
    row = add_records(client, project_id, [observation()])[0]
    response = calculate(client, project_id, saved["id"], {"a": row["id"], "b": row["id"]})
    assert response.status_code == 400, response.text
    assert "distinct scientific record" in response.json()["detail"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"location": {"latitude": 26, "longitude": -80}},
        {"depth_m": 20},
        {"depth_m": None, "depth_reference": None},
        {"location": None},
        {
            "provenance": {
                "source": "Other station",
                "dataset_id": "survey-2026",
                "acquired_at": "2026-04-03T13:05:00Z",
            }
        },
        {
            "provenance": {
                "source": "Reef survey",
                "dataset_id": "survey-2026",
                "acquired_at": "2026-04-03T13:05:00Z",
                "source_url": "https://example.test/station-b",
            }
        },
        {
            "provenance": {
                "source": "Reef survey",
                "dataset_id": "survey-2026",
                "acquired_at": "2026-04-03T13:05:00Z",
                "source_metadata": {"station_id": "station-b"},
            }
        },
    ],
)
def test_empty_subject_requires_matching_context(client, overrides):
    project_id = create_project(client, "Context identity")["id"]
    saved = definition(client, project_id).json()
    rows = add_records(client, project_id, [observation("a"), observation("b", **overrides)])
    response = calculate(client, project_id, saved["id"], {"a": rows[0]["id"], "b": rows[1]["id"]})
    assert response.status_code == 400, response.text
    assert "contextual identity" in response.json()["detail"]


def test_empty_subject_and_unknown_context_are_not_identity(client):
    project_id = create_project(client, "Unknown identity")["id"]
    saved = definition(client, project_id).json()
    rows = add_records(
        client,
        project_id,
        [
            scientific_record("a", 1, "m", location=None, depth_m=None, depth_reference=None),
            scientific_record("b", 2, "m", location=None, depth_m=None, depth_reference=None),
        ],
    )
    response = calculate(client, project_id, saved["id"], {"a": rows[0]["id"], "b": rows[1]["id"]})
    assert response.status_code == 400, response.text
    assert "contextual identity" in response.json()["detail"]


@pytest.mark.parametrize("rehash", [False, True])
def test_definition_version_is_checksummed_and_unsupported_versions_never_execute(client, rehash):
    project_id = create_project(client, "Formula version")["id"]
    saved = definition(client, project_id, "a", ("a",)).json()
    row = add_records(client, project_id, [observation()])[0]
    with client.app.state.session_factory() as session:
        stored = session.get(ComputedMetricDefinition, saved["id"])
        stored.formula_version = "future-engine-2"
        if rehash:
            stored.definition_sha256 = content_hash(
                {
                    "name": stored.name,
                    "expression": stored.expression,
                    "formula_version": stored.formula_version,
                    "inputs": stored.input_spec_json,
                    "output_unit": stored.output_unit,
                }
            )
        session.commit()
    response = calculate(client, project_id, saved["id"], {"a": row["id"]})
    assert response.status_code == (400 if rehash else 409), response.text
    assert ("Unsupported formula version" if rehash else "checksum mismatch") in response.json()[
        "detail"
    ]


def test_huge_formula_constant_returns_structured_validation_error(client):
    project_id = create_project(client, "Numeric limit")["id"]
    response = definition(client, project_id, "a * " + "9" * 400, ("a",))
    assert response.status_code == 400, response.text
    assert "finite" in response.json()["detail"]


@pytest.mark.parametrize("late_definition", [False, True])
def test_exchange_refuses_to_silently_drop_computed_metrics(client, test_settings, late_definition):
    project_id = create_project(client, "Exchange metric guard")["id"]
    if not late_definition:
        assert definition(client, project_id).status_code == 201
    queued = client.post(f"/api/v1/projects/{project_id}/exchange-packages", json={})
    if not late_definition:
        assert queued.status_code == 400, queued.text
        assert "computed metric" in queued.json()["detail"]
        return
    assert queued.status_code == 202, queued.text
    saved = definition(client, project_id)
    assert saved.status_code == 201
    rows = add_records(client, project_id, [observation("a"), observation("b")])
    assert (
        calculate(
            client, project_id, saved.json()["id"], {"a": rows[0]["id"], "b": rows[1]["id"]}
        ).status_code
        == 201
    )
    assert not process_project_exchange_export_job(
        test_settings, client.app.state.session_factory, queued.json()["job_id"]
    )
    package = client.get(f"/api/v1/exchange-packages/{queued.json()['package']['id']}").json()
    assert package["status"] != "complete"
    assert client.get(f"/api/v1/exchange-packages/{package['id']}/download").status_code == 400


def test_csv_queries_all_results_and_contains_normalized_workflow_provenance(client):
    project_id = create_project(client, "Complete CSV")["id"]
    saved = definition(client, project_id, "a", ("a",)).json()
    row = add_records(
        client, project_id, [observation(uncertainty={"value": 0.1, "kind": "standard_error"})]
    )[0]
    response = calculate(client, project_id, saved["id"], {"a": row["id"]})
    assert response.status_code == 201
    with client.app.state.session_factory() as session:
        service = ComputedMetricService(session)
        statements = []
        engine = session.get_bind()

        def capture(connection, cursor, statement, parameters, context, many):
            if "computed_metric_results" in statement:
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            exported = service.export_csv(project_id)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
    assert statements and all("LIMIT" not in sql.upper() for sql in statements)
    rows = list(csv.DictReader(io.StringIO(exported)))
    assert len(rows) == 1
    assert rows[0]["normalized_value"] == "1.0"
    assert rows[0]["normalized_unit"] == "m"
    assert rows[0]["normalized_uncertainty"] == "0.1"
    assert rows[0]["workflow_run_id"] == ""
    assert rows[0]["workflow_node_run_id"] == ""


def test_csv_escapes_spreadsheet_formulas_in_user_text(client):
    project_id = create_project(client, "CSV safety")["id"]
    saved = client.post(
        f"/api/v1/projects/{project_id}/computed-metric-definitions",
        json={
            "name": "=1+1",
            "expression": "+a",
            "inputs": [{"symbol": "a", "dimension": "length"}],
            "output_unit": "m",
        },
    ).json()
    row = add_records(client, project_id, [observation()])[0]
    assert calculate(client, project_id, saved["id"], {"a": row["id"]}).status_code == 201
    exported = client.get(f"/api/v1/projects/{project_id}/computed-metric-results.csv")
    row = next(csv.DictReader(io.StringIO(exported.text)))
    assert row["definition_name"] == "'=1+1"
    assert row["expression"] == "'+a"


@pytest.mark.parametrize(
    ("expression", "values", "uncertainty", "status"),
    [
        ("a / b", [1e-200, 1e-200], 1e-201, 201),
        ("a + b", [1, 1], 1e200, 201),
        ("a * 2", [1], 1e308, 400),
    ],
)
def test_api_numeric_stability_and_structured_overflow(
    client, expression, values, uncertainty, status
):
    project_id = create_project(client, "API numeric stability")["id"]
    symbols = tuple("ab"[: len(values)])
    saved = definition(
        client, project_id, expression, symbols, "1" if "/" in expression else "m"
    ).json()
    rows = add_records(
        client,
        project_id,
        [
            observation(
                symbol, value, uncertainty={"value": uncertainty, "kind": "standard_deviation"}
            )
            for symbol, value in zip(symbols, values, strict=True)
        ],
    )
    response = calculate(
        client,
        project_id,
        saved["id"],
        dict(zip(symbols, [row["id"] for row in rows], strict=True)),
    )
    assert response.status_code == status, response.text
    if status == 400:
        assert "finite" in response.json()["detail"]

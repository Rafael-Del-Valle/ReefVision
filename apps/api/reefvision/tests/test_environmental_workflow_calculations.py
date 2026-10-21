from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import EnvironmentalCacheEntry
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.scientific_data import content_hash
from reefvision.tests.test_annotations import create_project, import_one


def _grid() -> dict[str, object]:
    return {
        "dataset_id": "researcher-adcp-2026-10",
        "dataset_version": "deployment-1",
        "source": "Research vessel ADCP",
        "source_kind": "observed",
        "acquired_at": "2026-10-21T15:00:00Z",
        "samples": [
            {
                "observed_at": "2026-10-21T14:00:00Z",
                "latitude": 24.5,
                "longitude": -81.8,
                "depth_m": 5,
                "eastward_velocity_m_s": 3,
                "northward_velocity_m_s": 4,
            },
            {
                "observed_at": "2026-10-21T14:00:00Z",
                "latitude": 24.6,
                "longitude": -81.7,
                "depth_m": 5,
                "eastward_velocity_m_s": None,
                "northward_velocity_m_s": None,
            },
        ],
    }


def test_local_grid_import_preserves_observed_provenance_and_builds_vectors(
    client: TestClient,
) -> None:
    project = create_project(client, "Current grid")
    imported = client.post(
        f"/api/v1/projects/{project['id']}/environment/local-current-grid", json=_grid()
    )
    assert imported.status_code == 201, imported.text
    payload = imported.json()
    assert payload["cache_status"] == "imported"
    assert payload["skipped_missing"] == 2
    assert {item["variable"] for item in payload["items"]} == {
        "current_eastward_velocity",
        "current_northward_velocity",
    }
    assert {item["source_kind"] for item in payload["items"]} == {"observed"}
    assert {item["location"]["crs"] for item in payload["items"]} == {"EPSG:4326"}

    cache_key = payload["items"][0]["environmental_cache_key"]
    vectors = client.get(
        f"/api/v1/projects/{project['id']}/environment/datasets/{cache_key}/current-vectors"
    )
    assert vectors.status_code == 200, vectors.text
    assert vectors.json()["items"] == [
        {
            "eastward_velocity_m_s": 3.0,
            "northward_velocity_m_s": 4.0,
            "speed_m_s": 5.0,
            "direction_deg_true": pytest.approx(36.8698976458),
            "observed_at": "2026-10-21T14:00:00Z",
            "depth_m": 5.0,
            "depth_reference": "sea_surface",
            "location": {
                "crs": "EPSG:4326",
                "latitude": 24.5,
                "longitude": -81.8,
                "horizontal_uncertainty_m": None,
            },
            "source_kind": "observed",
            "source": "Research vessel ADCP",
            "dataset_id": "researcher-adcp-2026-10",
            "dataset_version": "deployment-1",
            "component_record_ids": [payload["items"][0]["id"], payload["items"][1]["id"]],
        }
    ]
    assert vectors.json()["input_record_count"] == 2
    assert vectors.json()["exclusions"] == {
        "unsupported_record": 0,
        "invalid_metadata_or_unit": 0,
        "qc_rejected": 0,
        "superseded_snapshot": 0,
        "incomplete_pair": 0,
        "duplicate_component": 0,
    }


def test_local_grid_version_identity_cannot_be_rewritten_with_new_provenance(
    client: TestClient,
) -> None:
    project = create_project(client, "Immutable current grid")
    url = f"/api/v1/projects/{project['id']}/environment/local-current-grid"
    first = client.post(url, json=_grid())
    assert first.status_code == 201, first.text

    changed = client.post(
        url,
        json={
            **_grid(),
            "source": "A different source claim",
            "source_kind": "modeled",
        },
    )
    assert changed.status_code == 400, changed.text
    page = client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()
    assert page["total"] == 2


def test_local_grid_requires_explicit_missing_component_values(client: TestClient) -> None:
    project = create_project(client, "Explicit current missingness")
    sample = cast(dict[str, object], cast(list[object], _grid()["samples"])[0]).copy()
    sample.pop("northward_velocity_m_s")
    response = client.post(
        f"/api/v1/projects/{project['id']}/environment/local-current-grid",
        json={**_grid(), "samples": [sample]},
    )
    assert response.status_code == 422, response.text


def test_current_vectors_report_incomplete_pairs(client: TestClient) -> None:
    project = create_project(client, "Incomplete current vectors")
    sample = cast(dict[str, object], cast(list[object], _grid()["samples"])[0]).copy()
    sample["northward_velocity_m_s"] = None
    imported = client.post(
        f"/api/v1/projects/{project['id']}/environment/local-current-grid",
        json={**_grid(), "samples": [sample]},
    )
    assert imported.status_code == 201, imported.text
    cache_key = imported.json()["items"][0]["environmental_cache_key"]
    vectors = client.get(
        f"/api/v1/projects/{project['id']}/environment/datasets/{cache_key}/current-vectors"
    )
    assert vectors.status_code == 200, vectors.text
    assert vectors.json()["items"] == []
    assert vectors.json()["input_record_count"] == 1
    assert vectors.json()["exclusions"]["incomplete_pair"] == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"source_kind": "derived"},
        {"samples": []},
        {"samples": [{**cast(dict[str, object], _grid()["samples"])[0], "depth_m": -1}]},
    ],
)
def test_local_grid_rejects_invalid_data_without_persisting(
    client: TestClient, patch: dict[str, object]
) -> None:
    project = create_project(client, "Invalid grid")
    response = client.post(
        f"/api/v1/projects/{project['id']}/environment/local-current-grid",
        json={**_grid(), **patch},
    )
    assert response.status_code == 422, response.text
    assert client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()["total"] == 0


def _record(variable: str, value: float, unit: str) -> dict[str, object]:
    return {
        "variable": variable,
        "value": value,
        "unit": unit,
        "observed_at": "2026-10-21T14:00:00Z",
        "source_kind": "observed",
        "provenance": {"source": "calibrated transect", "acquired_at": "2026-10-21T15:00:00Z"},
    }


def test_versioned_calculations_persist_reproducible_area_and_density(client: TestClient) -> None:
    project = create_project(client, "Calculations")
    records_url = f"/api/v1/projects/{project['id']}/scientific-records"
    inputs = client.post(
        records_url,
        json={
            "records": [_record("transect_width", 200, "cm"), _record("transect_length", 3, "m")]
        },
    ).json()["items"]
    area = client.post(
        f"/api/v1/projects/{project['id']}/scientific-calculations",
        json={
            "formula_id": "rectangular_area",
            "formula_version": "1.0.0",
            "input_record_ids": [row["id"] for row in inputs],
        },
    )
    assert area.status_code == 201, area.text
    result = area.json()
    assert result["variable"] == "calculated_area"
    assert result["normalized_value"] == pytest.approx(6)
    assert result["normalized_unit"] == "m2"
    assert result["source_kind"] == "derived"
    assert result["provenance"]["method"] == "rectangular_area@1.0.0"
    assert result["provenance"]["processing_parameters"]["input_record_ids"] == [
        row["id"] for row in inputs
    ]

    count = client.post(
        f"/api/v1/projects/{project['id']}/scientific-calculations",
        json={
            "formula_id": "count_records",
            "formula_version": "1.0.0",
            "input_record_ids": [row["id"] for row in inputs],
        },
    ).json()
    density = client.post(
        f"/api/v1/projects/{project['id']}/scientific-calculations",
        json={
            "formula_id": "density",
            "formula_version": "1.0.0",
            "input_record_ids": [count["id"], result["id"]],
        },
    )
    assert density.status_code == 201, density.text
    assert density.json()["normalized_value"] == pytest.approx(2 / 6)
    assert density.json()["normalized_unit"] == "count/m2"


@pytest.mark.parametrize(
    ("formula_id", "records", "message"),
    [
        (
            "rectangular_area",
            [_record("width", -2, "m"), _record("length", 3, "m")],
            "positive",
        ),
        (
            "density",
            [_record("count", 1.5, "count"), _record("area", 3, "m2")],
            "nonnegative integer",
        ),
        (
            "rectangular_area",
            [
                {**_record("width", 2, "m"), "qc": "rejected"},
                _record("length", 3, "m"),
            ],
            "QC",
        ),
    ],
)
def test_calculations_reject_physically_invalid_inputs(
    client: TestClient,
    formula_id: str,
    records: list[dict[str, object]],
    message: str,
) -> None:
    project = create_project(client, "Invalid calculation")
    inputs = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records", json={"records": records}
    ).json()["items"]
    response = client.post(
        f"/api/v1/projects/{project['id']}/scientific-calculations",
        json={
            "formula_id": formula_id,
            "formula_version": "1.0.0",
            "input_record_ids": [row["id"] for row in inputs],
        },
    )
    assert response.status_code == 400, response.text
    assert message in response.json()["detail"]


def test_calculations_require_inputs_from_the_same_observation_scope(client: TestClient) -> None:
    project = create_project(client, "Calculation scope")
    first = _record("width", 2, "m")
    second = _record("length", 3, "m")
    second["observed_at"] = "2026-10-21T15:00:00Z"
    inputs = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records",
        json={"records": [first, second]},
    ).json()["items"]
    response = client.post(
        f"/api/v1/projects/{project['id']}/scientific-calculations",
        json={
            "formula_id": "rectangular_area",
            "formula_version": "1.0.0",
            "input_record_ids": [row["id"] for row in inputs],
        },
    )
    assert response.status_code == 400, response.text
    assert "observation scope" in response.json()["detail"]


def test_calculations_inherit_calibration_snapshot_and_reject_stale_inputs(
    client: TestClient,
) -> None:
    project = create_project(client, "Calculation calibration")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    calibration_url = f"/api/v1/images/{image_id}/measurement-calibration"
    assert (
        client.put(calibration_url, json={"distance_per_pixel": 0.1, "unit": "mm"}).status_code
        == 200
    )
    records = [
        {**_record("width", 2, "m"), "subject": {"image_id": image_id}},
        {**_record("length", 3, "m"), "subject": {"image_id": image_id}},
    ]
    inputs = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records",
        json={"records": records},
    ).json()["items"]
    calculated = client.post(
        f"/api/v1/projects/{project['id']}/scientific-calculations",
        json={
            "formula_id": "rectangular_area",
            "formula_version": "1.0.0",
            "input_record_ids": [row["id"] for row in inputs],
        },
    )
    assert calculated.status_code == 201, calculated.text
    assert calculated.json()["calibration_snapshot"] == inputs[0]["calibration_snapshot"]
    assert calculated.json()["calibration_sha256"] == inputs[0]["calibration_sha256"]

    assert (
        client.put(calibration_url, json={"distance_per_pixel": 0.2, "unit": "mm"}).status_code
        == 200
    )
    stale = client.post(
        f"/api/v1/projects/{project['id']}/scientific-calculations",
        json={
            "formula_id": "rectangular_area",
            "formula_version": "1.0.0",
            "input_record_ids": [row["id"] for row in inputs],
        },
    )
    assert stale.status_code == 400, stale.text
    assert "calibration" in stale.json()["detail"]


def test_calculations_reject_superseded_environmental_inputs(client: TestClient) -> None:
    project = create_project(client, "Superseded calculation inputs")
    imported = client.post(
        f"/api/v1/projects/{project['id']}/environment/local-current-grid", json=_grid()
    ).json()
    cache_key = imported["items"][0]["environmental_cache_key"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        entry = session.scalar(
            select(EnvironmentalCacheEntry).where(
                EnvironmentalCacheEntry.project_id == project["id"],
                EnvironmentalCacheEntry.cache_key == cache_key,
            )
        )
        assert entry is not None
        entry.payload_json = {**entry.payload_json, "record_ids": []}
        entry.content_sha256 = content_hash(entry.payload_json)
        session.commit()
    response = client.post(
        f"/api/v1/projects/{project['id']}/scientific-calculations",
        json={
            "formula_id": "count_records",
            "formula_version": "1.0.0",
            "input_record_ids": [row["id"] for row in imported["items"]],
        },
    )
    assert response.status_code == 400, response.text
    assert "superseded environmental" in response.json()["detail"]


def test_scientific_workflow_nodes_roundtrip_and_execute(client: TestClient) -> None:
    project = create_project(client, "Scientific workflow")
    records = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records",
        json={"records": [_record("transect_width", 2, "m"), _record("transect_length", 3, "m")]},
    ).json()["items"]
    graph = {
        "graph_id": "scientific-area",
        "name": "Scientific area",
        "nodes": [
            {
                "node_id": "records",
                "node_type": "scientific_records_source",
                "parameters": {"record_ids": [row["id"] for row in records]},
            },
            {
                "node_id": "calculate",
                "node_type": "scientific_calculation",
                "parameters": {"formula_id": "rectangular_area", "formula_version": "1.0.0"},
            },
        ],
        "edges": [
            {
                "edge_id": "records-calculate",
                "source_node_id": "records",
                "source_port_id": "records",
                "target_node_id": "calculate",
                "target_port_id": "records",
            }
        ],
    }
    saved = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    saved_graph = saved.json()["graph_json"]
    assert saved_graph["schema_version"] == "workflow-graph-0001"
    assert [node["node_type"] for node in saved_graph["nodes"]] == [
        "scientific_records_source",
        "scientific_calculation",
    ]
    run = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    ).json()
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, run["job_id"])
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}").json()
    artifacts = {item["data_type"]: item["payload_json"] for item in detail["artifacts"]}
    assert artifacts["scientific_records"]["record_ids"] == [row["id"] for row in records]
    assert artifacts["scientific_calculation"]["record"]["normalized_value"] == pytest.approx(6)


def test_cached_current_vector_workflow_executes_offline(client: TestClient) -> None:
    project = create_project(client, "Current vector workflow")
    imported = client.post(
        f"/api/v1/projects/{project['id']}/environment/local-current-grid", json=_grid()
    ).json()
    cache_key = imported["items"][0]["environmental_cache_key"]
    graph = {
        "graph_id": "cached-current-vectors",
        "name": "Cached current vectors",
        "nodes": [
            {
                "node_id": "dataset",
                "node_type": "environmental_dataset_source",
                "parameters": {"cache_key": cache_key},
            },
            {"node_id": "vectors", "node_type": "current_vectors"},
        ],
        "edges": [
            {
                "edge_id": "dataset-vectors",
                "source_node_id": "dataset",
                "source_port_id": "dataset",
                "target_node_id": "vectors",
                "target_port_id": "dataset",
            }
        ],
    }
    saved = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    ).json()
    run = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": saved["id"]},
    ).json()
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, run["job_id"])
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}").json()
    artifact = next(item for item in detail["artifacts"] if item["data_type"] == "current_vectors")
    assert artifact["payload_json"]["count"] == 1
    assert artifact["payload_json"]["items"][0]["source_kind"] == "observed"
    assert artifact["payload_json"]["items"][0]["speed_m_s"] == 5
    assert artifact["payload_json"]["exclusions"]["incomplete_pair"] == 0


def test_workflow_validation_rejects_invalid_science_and_environment_parameters(
    client: TestClient,
) -> None:
    project = create_project(client, "Workflow parameter validation")
    graph = {
        "graph_id": "invalid-science-parameters",
        "name": "Invalid science parameters",
        "nodes": [
            {
                "node_id": "records",
                "node_type": "scientific_records_source",
                "parameters": {"record_ids": ["not-a-uuid"]},
            },
            {
                "node_id": "calculate",
                "node_type": "scientific_calculation",
                "parameters": {"formula_id": "unknown", "formula_version": "9"},
            },
            {
                "node_id": "dataset",
                "node_type": "environmental_dataset_source",
                "parameters": {"cache_key": "0" * 64},
            },
        ],
        "edges": [
            {
                "edge_id": "records-calculate",
                "source_node_id": "records",
                "source_port_id": "records",
                "target_node_id": "calculate",
                "target_port_id": "records",
            }
        ],
    }
    response = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/validate", json=graph)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is False
    assert {issue["code"] for issue in payload["issues"]} >= {
        "scientific_record_parameters_invalid",
        "scientific_calculation_parameters_invalid",
        "environmental_cache_missing",
    }


def test_workflow_validation_rejects_foreign_scientific_records(client: TestClient) -> None:
    owner = create_project(client, "Record owner")
    target = create_project(client, "Workflow target")
    record = client.post(
        f"/api/v1/projects/{owner['id']}/scientific-records",
        json={"records": [_record("length", 2, "m")]},
    ).json()["items"][0]
    graph = {
        "graph_id": "foreign-scientific-record",
        "name": "Foreign scientific record",
        "nodes": [
            {
                "node_id": "records",
                "node_type": "scientific_records_source",
                "parameters": {"record_ids": [record["id"]]},
            }
        ],
        "edges": [],
    }
    response = client.post(f"/api/v1/projects/{target['id']}/workflow-graphs/validate", json=graph)
    assert response.status_code == 200, response.text
    assert response.json()["valid"] is False
    assert {issue["code"] for issue in response.json()["issues"]} >= {
        "scientific_record_scope_mismatch"
    }


def test_workflow_validation_rejects_corrupt_environmental_cache(client: TestClient) -> None:
    project = create_project(client, "Corrupt cache workflow")
    imported = client.post(
        f"/api/v1/projects/{project['id']}/environment/local-current-grid", json=_grid()
    ).json()
    cache_key = imported["items"][0]["environmental_cache_key"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        entry = session.scalar(
            select(EnvironmentalCacheEntry).where(
                EnvironmentalCacheEntry.project_id == project["id"],
                EnvironmentalCacheEntry.cache_key == cache_key,
            )
        )
        assert entry is not None
        entry.payload_json = {**entry.payload_json, "skipped_missing": 999}
        session.commit()
    graph = {
        "graph_id": "corrupt-environment-cache",
        "name": "Corrupt environmental cache",
        "nodes": [
            {
                "node_id": "dataset",
                "node_type": "environmental_dataset_source",
                "parameters": {"cache_key": cache_key},
            }
        ],
        "edges": [],
    }
    response = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/validate", json=graph)
    assert response.status_code == 200, response.text
    assert response.json()["valid"] is False
    assert {issue["code"] for issue in response.json()["issues"]} >= {"environmental_cache_invalid"}

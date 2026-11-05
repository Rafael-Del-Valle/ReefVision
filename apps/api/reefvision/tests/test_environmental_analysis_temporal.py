"""Event windows, bounded joins, and lags preserve descriptive scientific evidence."""

from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_scientific_data import observation
from reefvision.tests.test_workflow_environmental_threshold import threshold_query


def _records(client: TestClient, project_id: str, records: list[dict]) -> list[dict]:
    response = client.post(
        f"/api/v1/projects/{project_id}/scientific-records", json={"records": records}
    )
    assert response.status_code == 201, response.text
    return response.json()["items"]


def _base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/environment/analyses"


def test_event_window_boundary_policy_and_overlap_are_deterministic(
    client: TestClient,
) -> None:
    project = create_project(client, "Environmental windows")
    saved = _records(
        client,
        project["id"],
        [
            observation(value=72, observed_at="2026-04-03T13:00:00Z", unit="degF"),
            observation(value=73, observed_at="2026-04-03T13:10:00Z", unit="degF"),
            observation(value=65, observed_at="2026-04-03T13:20:00Z", unit="degF"),
        ],
    )
    query = threshold_query()
    query.update(
        {
            "observed_at": "2026-04-03T13:05:00Z",
            "max_time_delta_s": 900,
            "threshold_value": 20,
            "threshold_unit": "degC",
            "direction": "above",
        }
    )
    definition = client.post(
        f"/api/v1/projects/{project['id']}/environment/events/definitions",
        json={"name": "Warm samples", "query": query},
    )
    assert definition.status_code == 201, definition.text
    event_definition_id = definition.json()["id"]
    request = {
        "name": "Ten-minute context",
        "event_definition_id": event_definition_id,
        "before_s": 300,
        "after_s": 300,
    }
    inclusive = client.post(
        f"{_base(project['id'])}/event-window",
        json={**request, "boundary_policy": "inclusive"},
    )
    assert inclusive.status_code == 201, inclusive.text
    inclusive_result = inclusive.json()["result"]
    assert len(inclusive_result["payload"]["windows"]) == 1
    window = inclusive_result["payload"]["windows"][0]
    assert window["start_at"] == "2026-04-03T12:55:00Z"
    assert window["end_at"] == "2026-04-03T13:15:00Z"
    assert window["start_inclusive"] is True and window["end_inclusive"] is True
    assert set(window["event_record_ids"]) == {saved[0]["id"], saved[1]["id"]}

    exclusive = client.post(
        f"{_base(project['id'])}/event-window",
        json={**request, "name": "Exclusive windows", "boundary_policy": "exclusive"},
    )
    assert exclusive.status_code == 201, exclusive.text
    windows = exclusive.json()["result"]["payload"]["windows"]
    assert len(windows) == 2
    assert windows[0]["end_at"] == windows[1]["start_at"]
    assert not windows[0]["end_inclusive"] and not windows[1]["start_inclusive"]
    assert saved[2]["id"] not in inclusive_result["source_record_ids"]


def test_observation_join_enforces_time_location_depth_and_uses_explicit_observation_time(
    client: TestClient,
) -> None:
    project = create_project(client, "Bounded joins")
    records = _records(
        client,
        project["id"],
        [
            observation(
                variable="coral_count",
                value=4,
                unit="count",
                observed_at="2026-04-03T13:00:00Z",
                depth_m=5,
                depth_reference="sea_surface",
            ),
            observation(
                value=68,
                unit="degF",
                observed_at="2026-04-03T12:59:30Z",
                depth_m=5.4,
                depth_reference="sea_surface",
            ),
            observation(
                value=90,
                unit="degF",
                observed_at="2026-04-03T13:00:00Z",
                location={"latitude": 0, "longitude": 0},
                depth_m=5,
                depth_reference="sea_surface",
            ),
        ],
    )
    response = client.post(
        f"{_base(project['id'])}/observation-environment-join",
        json={
            "name": "Coral-temperature join",
            "observation_record_ids": [records[0]["id"]],
            "environmental_variable": "water_temperature",
            "max_time_delta_s": 60,
            "max_distance_m": 1000,
            "require_depth_match": True,
            "max_depth_delta_m": 0.5,
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()["result"]
    pair = result["payload"]["pairs"][0]
    assert pair["observation_record_id"] == records[0]["id"]
    assert pair["environmental_record_id"] == records[1]["id"]
    assert pair["time_delta_s"] == -30
    assert pair["depth_delta_m"] == 0.4
    assert pair["independent_unit_id"] == f"record:{records[0]['id']}"
    assert result["payload"]["matching_policy"]["observation_time_source"] == (
        "scientific_record.observed_at"
    )
    assert result["payload"]["interpretation"] == "descriptive_context_only"

    rejected = client.post(
        f"{_base(project['id'])}/observation-environment-join",
        json={
            "name": "Too strict",
            "observation_record_ids": [records[0]["id"]],
            "environmental_variable": "water_temperature",
            "max_time_delta_s": 10,
            "max_distance_m": 1000,
            "require_depth_match": True,
            "max_depth_delta_m": 0.1,
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert "No bounded environmental match" in rejected.json()["detail"]


def test_lagged_comparison_reports_reused_samples_and_never_claims_inference(
    client: TestClient,
) -> None:
    project = create_project(client, "Lagged context")
    records = _records(
        client,
        project["id"],
        [
            observation(
                variable="coral_count",
                value=4,
                unit="count",
                observed_at="2026-04-03T13:00:00Z",
            ),
            observation(
                variable="coral_count",
                value=6,
                unit="count",
                observed_at="2026-04-03T13:10:00Z",
            ),
            observation(value=66, unit="degF", observed_at="2026-04-03T12:55:00Z"),
            observation(value=68, unit="degF", observed_at="2026-04-03T13:05:00Z"),
            observation(value=70, unit="degF", observed_at="2026-04-03T13:15:00Z"),
        ],
    )
    join = client.post(
        f"{_base(project['id'])}/observation-environment-join",
        json={
            "name": "Base join",
            "observation_record_ids": [records[0]["id"], records[1]["id"]],
            "environmental_variable": "water_temperature",
            "max_time_delta_s": 300,
            "max_distance_m": 1000,
            "require_depth_match": False,
        },
    )
    assert join.status_code == 201, join.text
    join_result_id = join.json()["result"]["id"]
    lagged = client.post(
        f"{_base(project['id'])}/lagged-comparison",
        json={
            "name": "Five-minute lags",
            "join_result_id": join_result_id,
            "lags_s": [-300, 300],
        },
    )
    assert lagged.status_code == 201, lagged.text
    result = lagged.json()["result"]
    assert result["source_analysis_result_ids"] == [join_result_id]
    assert len(result["payload"]["pairs"]) == 4
    reused = result["payload"]["reuse_diagnostics"]["environmental_record_reuse_counts"]
    assert reused[records[3]["id"]] == 2
    assert result["payload"]["reuse_diagnostics"]["pseudoreplication_warning"] is True
    assert result["payload"]["interpretation"] == "descriptive_context_only"
    assert result["payload"]["inferential_statistics"] is None


def test_join_rejects_foreign_or_tampered_source_records_atomically(client: TestClient) -> None:
    project = create_project(client, "Join owner")
    other = create_project(client, "Foreign join source")
    foreign = _records(
        client,
        other["id"],
        [observation(variable="coral_count", value=1, unit="count")],
    )[0]
    base = _base(project["id"])
    rejected = client.post(
        f"{base}/observation-environment-join",
        json={
            "name": "Foreign",
            "observation_record_ids": [foreign["id"]],
            "environmental_variable": "water_temperature",
            "max_time_delta_s": 60,
            "max_distance_m": 1000,
            "require_depth_match": False,
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert client.get(f"{base}/definitions").json()["total"] == 0
    assert client.get(f"{base}/results").json()["total"] == 0

from __future__ import annotations

import csv
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import GeoReferencedObservation as GeoReferencedObservationRecord
from reefvision.db.models.computed_metric import ComputedMetricResult
from reefvision.domain.errors import ConflictError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.geographic_pairwise import GeographicPairwiseCalculateRequest
from reefvision.schemas.georeferenced_observation import GeoReferencedObservation
from reefvision.services.geographic_pairwise import GeographicPairwiseService
from reefvision.services.georeferenced_observations import GeoReferencedObservationService
from reefvision.services.scientific_data import content_hash
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_georeferenced_observation_api import _import_video, _payload
from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive
from reefvision.tests.test_workflow_computed_metrics import save_and_queue


def _persist_pair(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    end_longitude: float = 0.001,
    end_group: str = "fix-b",
):
    project = create_project(client, "Pairwise geography")
    video = _import_video(client, project["id"], monkeypatch)
    track = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": project["label_classes"][0]["id"],
            "keyframes": [
                {"frame": 1, "bbox": [11, 12, 20, 8]},
                {"frame": 2, "bbox": [12, 12, 20, 8]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert track.status_code == 201, track.text
    observations: list[GeoReferencedObservation] = []
    for frame_index, longitude, sigma, group in (
        (1, 0.0, 3.0, "fix-a"),
        (2, end_longitude, 4.0, end_group),
    ):
        raw = _payload(
            project_id=project["id"],
            video_id=video["id"],
            track_id=track.json()["id"],
            frame_index=frame_index,
        ).model_dump(mode="json")
        raw["id"] = str(uuid4())
        raw["location"] = {
            "latitude_deg": 0.0,
            "longitude_deg": longitude,
            "crs": "EPSG:4326",
        }
        raw["uncertainty"] = {
            "available": True,
            "method": "propagated_1sigma",
            "horizontal_sigma_m": sigma,
            "correlation_group_id": group,
        }
        observations.append(GeoReferencedObservation.model_validate(raw))
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        service = GeoReferencedObservationService(session)
        for observation in observations:
            service.persist(observation, configuration_hash="a" * 64)
        session.commit()
    return project, observations


def test_pairwise_geography_persists_complete_snapshots_currentness_and_csv(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, test_settings
) -> None:
    project, observations = _persist_pair(client, monkeypatch)
    request = {
        "name": "Endpoint displacement",
        "start_observation_id": str(observations[0].id),
        "end_observation_id": str(observations[1].id),
    }

    response = client.post(
        f"/api/v1/projects/{project['id']}/geographic-pairwise/calculate", json=request
    )

    assert response.status_code == 201, response.text
    saved = response.json()
    measurement = saved["measurement"]
    assert measurement["algorithm"] == "reefvision.wgs84-pairwise-geodesic.v1"
    assert measurement["distance_m"] == pytest.approx(111.319490793, rel=1e-9)
    assert measurement["initial_bearing_deg"] == pytest.approx(90.0)
    assert measurement["distance_standard_uncertainty_m"] == 5
    assert measurement["bearing_standard_uncertainty_deg"] == pytest.approx(
        5 / measurement["distance_m"] * 180 / 3.141592653589793
    )
    assert measurement["time_basis"] == "same_video_frame_time"
    assert measurement["signed_time_delta_s"] == pytest.approx(0.1)
    assert measurement["start_snapshot"]["configuration_hash"] == "a" * 64
    assert (
        measurement["start_snapshot"]["observation"]["calibration"]["checksum_sha256"] == "b" * 64
    )
    assert len(measurement["start_snapshot_sha256"]) == 64

    result_id = saved["result_id"]
    fetched = client.get(f"/api/v1/projects/{project['id']}/geographic-pairwise/{result_id}")
    assert fetched.status_code == 200, fetched.text
    current = client.get(
        f"/api/v1/projects/{project['id']}/geographic-pairwise/{result_id}/validation"
    )
    assert current.status_code == 200, current.text
    assert current.json()["is_current"] is True
    exported = client.get(
        f"/api/v1/projects/{project['id']}/geographic-pairwise/{result_id}/export.csv"
    )
    assert exported.status_code == 200, exported.text
    assert "initial_bearing_deg_true_north" in exported.text
    assert measurement["content_sha256"] in exported.text
    row = next(csv.DictReader(exported.text.splitlines()))
    assert row["coordinate_reference_system"] == "EPSG:4326"
    assert float(row["absolute_time_delta_s"]) == pytest.approx(0.1)
    assert row["bearing_unavailable_reason"] == ""
    assert row["time_unavailable_reason"] == ""
    assert row["uncertainty_unavailable_reason"] == ""
    assert row["start_snapshot_sha256"] == measurement["start_snapshot_sha256"]
    assert row["end_snapshot_sha256"] == measurement["end_snapshot_sha256"]
    assert row["definition_sha256"] == saved["definition_sha256"]
    assert row["result_sha256"] == saved["result_sha256"]

    archive = export_archive(client, test_settings, project["id"])
    imported = import_archive(client, archive)
    assert imported.status_code == 201, imported.text
    imported_project_id = imported.json()["project_id"]
    with client.app.state.session_factory() as session:
        imported_result = session.scalar(
            select(ComputedMetricResult).where(
                ComputedMetricResult.project_id == imported_project_id,
                ComputedMetricResult.result_kind == "geographic_pairwise",
            )
        )
        assert imported_result is not None
        imported_result_id = imported_result.id
    imported_saved = client.get(
        f"/api/v1/projects/{imported_project_id}/geographic-pairwise/{imported_result_id}"
    )
    assert imported_saved.status_code == 200, imported_saved.text
    imported_measurement = imported_saved.json()["measurement"]
    assert imported_measurement["start_observation_id"] != str(observations[0].id)
    assert imported_measurement["start_snapshot"]["observation"]["calibration"][
        "calibration_id"
    ] == "sha256:" + ("b" * 64)
    assert (
        imported_measurement["start_snapshot"]["observation"]["telemetry"]["source_id"]
        == "test.srt"
    )
    imported_current = client.get(
        f"/api/v1/projects/{imported_project_id}/geographic-pairwise/"
        f"{imported_result_id}/validation"
    )
    assert imported_current.status_code == 200, imported_current.text
    assert imported_current.json()["is_current"] is False
    assert imported_current.json()["reasons"] == ["endpoint_unavailable_or_stale"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        endpoint = session.get(GeoReferencedObservationRecord, str(observations[0].id))
        assert endpoint is not None
        endpoint.is_stale = True
        endpoint.stale_reason = "configuration_changed"
        session.commit()
    stale = client.get(
        f"/api/v1/projects/{project['id']}/geographic-pairwise/{result_id}/validation"
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["is_current"] is False
    assert stale.json()["reasons"] == ["endpoint_unavailable_or_stale"]


def test_pairwise_geography_is_project_scoped_and_rejects_self_pairs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, observations = _persist_pair(client, monkeypatch)
    other = create_project(client, "Other geography")
    foreign = client.post(
        f"/api/v1/projects/{other['id']}/geographic-pairwise/calculate",
        json={
            "name": "Foreign endpoints",
            "start_observation_id": str(observations[0].id),
            "end_observation_id": str(observations[1].id),
        },
    )
    assert foreign.status_code == 404
    self_pair = client.post(
        f"/api/v1/projects/{project['id']}/geographic-pairwise/calculate",
        json={
            "name": "Self pair",
            "start_observation_id": str(observations[0].id),
            "end_observation_id": str(observations[0].id),
        },
    )
    assert self_pair.status_code == 422


def test_pairwise_geography_executes_and_replays_in_workflow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, observations = _persist_pair(client, monkeypatch)
    parameters = {
        "name": "Workflow endpoint displacement",
        "start_observation_id": str(observations[0].id),
        "end_observation_id": str(observations[1].id),
    }
    graph = {
        "graph_id": "geographic-pairwise",
        "name": "Pairwise geography",
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "pairwise",
                "node_type": "geographic_pairwise",
                "parameters": parameters,
            },
        ],
        "edges": [
            {
                "edge_id": "project-pairwise",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "pairwise",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    queued = save_and_queue(client, project["id"], graph)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued['id']}").json()
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "computed_metric_result"
    )
    assert artifact["payload_json"]["result_kind"] == "geographic_pairwise"
    assert artifact["payload_json"]["distance_m"] == pytest.approx(111.319490793, rel=1e-9)
    node = next(item for item in detail["nodes"] if item["node_type"] == "geographic_pairwise")
    with app.state.session_factory() as session:
        replay = GeographicPairwiseService(session).calculate(
            project["id"],
            GeographicPairwiseCalculateRequest.model_validate(parameters),
            workflow_run_id=queued["id"],
            workflow_node_run_id=node["id"],
        )
        assert str(replay.result_id) == artifact["payload_json"]["result_id"]
        assert str(replay.workflow_run_id) == queued["id"]
        assert str(replay.workflow_node_run_id) == node["id"]
        for wrong_run_id in (str(uuid4()), None):
            with pytest.raises(ConflictError, match="Workflow node replay conflicts"):
                GeographicPairwiseService(session).calculate(
                    project["id"],
                    GeographicPairwiseCalculateRequest.model_validate(parameters),
                    workflow_run_id=wrong_run_id,
                    workflow_node_run_id=node["id"],
                )
        repeated = GeographicPairwiseService(session).calculate(
            project["id"],
            GeographicPairwiseCalculateRequest.model_validate(parameters),
            workflow_run_id=queued["id"],
            workflow_node_run_id=node["id"],
        )
        assert repeated.result_id == replay.result_id
        assert repeated.result_sha256 == replay.result_sha256


def test_pairwise_saved_result_rejects_valid_but_unrelated_definition_and_measurement(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, observations = _persist_pair(client, monkeypatch)
    start_id, end_id = (str(observation.id) for observation in observations)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        service = GeographicPairwiseService(session)
        first = service.calculate(
            project["id"],
            GeographicPairwiseCalculateRequest(
                name="Forward", start_observation_id=start_id, end_observation_id=end_id
            ),
        )
        reverse = service.calculate(
            project["id"],
            GeographicPairwiseCalculateRequest(
                name="Reverse", start_observation_id=end_id, end_observation_id=start_id
            ),
        )
        row = session.get(ComputedMetricResult, str(first.result_id))
        assert row is not None
        original_payload = dict(row.payload_json)
        original_hash = row.content_sha256

        # Both definitions have valid checksums; their identities are not interchangeable.
        row.definition_id = str(reverse.definition_id)
        session.flush()
        with pytest.raises(ConflictError, match="result definition mismatch"):
            service.get_result(project["id"], str(first.result_id))
        row.definition_id = str(first.definition_id)
        session.flush()

        # Even a separately valid measurement cannot be attached to reversed endpoints.
        row.payload_json = {
            **original_payload,
            "measurement": reverse.measurement.model_dump(mode="json"),
        }
        row.content_sha256 = content_hash(row.payload_json)
        session.flush()
        with pytest.raises(ConflictError, match="result endpoint mismatch"):
            service.get_result(project["id"], str(first.result_id))

        row.payload_json = original_payload
        row.content_sha256 = original_hash
        session.flush()
        restored = service.get_result(project["id"], str(first.result_id))
        assert restored == first
        assert service.get_result(project["id"], str(reverse.result_id)) == reverse


@pytest.mark.parametrize(
    ("end_longitude", "end_group", "expected_distance", "expected_sigma", "reason"),
    [
        (0.001, "fix-a", 111.319490793, None, "unknown_or_shared_endpoint_correlation"),
        (0.0001, "fix-b", 11.1319490793, 5.0, "bearing_geometry_ill_conditioned"),
        (0.0, "fix-b", 0.0, 5.0, "coincident_locations"),
    ],
)
def test_pairwise_geography_preserves_uncertainty_limits(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    end_longitude: float,
    end_group: str,
    expected_distance: float,
    expected_sigma: float | None,
    reason: str,
) -> None:
    project, observations = _persist_pair(
        client, monkeypatch, end_longitude=end_longitude, end_group=end_group
    )
    request = {
        "name": "Uncertainty-limited displacement",
        "start_observation_id": str(observations[0].id),
        "end_observation_id": str(observations[1].id),
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/geographic-pairwise/calculate", json=request
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    measurement = saved["measurement"]
    assert measurement["distance_m"] == pytest.approx(expected_distance, rel=1e-9)
    assert measurement["distance_standard_uncertainty_m"] == expected_sigma
    assert measurement["bearing_standard_uncertainty_deg"] is None
    assert measurement["uncertainty_unavailable_reason"] == reason
    if expected_distance == 0.0:
        assert measurement["initial_bearing_deg"] is None
        assert measurement["bearing_unavailable_reason"] == "coincident_locations"
    else:
        assert measurement["initial_bearing_deg"] == pytest.approx(90.0)
        assert measurement["bearing_unavailable_reason"] is None

    fetched = client.get(
        f"/api/v1/projects/{project['id']}/geographic-pairwise/{saved['result_id']}"
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == saved
    exported = client.get(
        f"/api/v1/projects/{project['id']}/geographic-pairwise/{saved['result_id']}/export.csv"
    )
    assert exported.status_code == 200, exported.text
    row = next(csv.DictReader(exported.text.splitlines()))
    assert row["uncertainty_unavailable_reason"] == reason
    assert row["bearing_standard_uncertainty_deg"] == ""
    assert row["bearing_unavailable_reason"] == (measurement["bearing_unavailable_reason"] or "")
    assert row["measurement_sha256"] == measurement["content_sha256"]
    if expected_sigma is None:
        assert row["distance_standard_uncertainty_m"] == ""
    else:
        assert float(row["distance_standard_uncertainty_m"]) == expected_sigma
    validation = client.get(
        f"/api/v1/projects/{project['id']}/geographic-pairwise/{saved['result_id']}/validation"
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["is_current"] is True

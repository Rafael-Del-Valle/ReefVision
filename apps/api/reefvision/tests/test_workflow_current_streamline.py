"""Current streamlines execute as replay-safe, provenance-complete workflow nodes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from reefvision.db.models.environmental_analysis import (
    EnvironmentalAnalysisDefinition,
    EnvironmentalAnalysisResult,
)
from reefvision.db.models.scientific_record import EnvironmentalCacheEntry, ScientificRecord
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.current_field import CurrentFieldAnalysisRequest
from reefvision.services.current_field import CurrentFieldService
from reefvision.services.environmental_analysis import EnvironmentalAnalysisService
from reefvision.services.scientific_data import content_hash
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_computed_metrics import save_and_queue


def _current_records(client: TestClient, project_id: str) -> list[str]:
    records = []
    for latitude in (-1.0, 1.0):
        for longitude in (-1.0, 1.0):
            for variable, value in (
                ("current_eastward_velocity", 1.0),
                ("current_northward_velocity", 0.0),
            ):
                records.append(
                    {
                        "variable": variable,
                        "value": value,
                        "unit": "m/s",
                        "observed_at": "2026-01-01T00:00:00Z",
                        "source_kind": "modeled",
                        "location": {
                            "crs": "EPSG:4326",
                            "latitude": latitude,
                            "longitude": longitude,
                        },
                        "depth_m": 0,
                        "depth_reference": "sea_surface",
                        "qc": "accepted",
                        "provenance": {
                            "source": "synthetic current fixture",
                            "dataset_id": "fixture-v1",
                            "model_version": "fixture-model-v1",
                            "acquired_at": "2026-01-02T00:00:00Z",
                            "method": "test",
                        },
                    }
                )
    response = client.post(
        f"/api/v1/projects/{project_id}/scientific-records", json={"records": records}
    )
    assert response.status_code == 201, response.text
    return [item["id"] for item in response.json()["items"]]


def _parameters(record_ids: list[str]) -> dict:
    return {
        "name": "Workflow surface flow",
        "scientific_record_ids": record_ids,
        "seeds": [{"latitude": 0, "longitude": 0}],
        "step_seconds": 60,
        "max_steps": 2,
        "max_length_m": 1000,
        "stagnation_m_s": 1e-9,
    }


def _graph(parameters: dict) -> dict:
    return {
        "graph_id": "current-streamline-analysis",
        "name": "Current streamline analysis",
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "streamline",
                "node_type": "current_streamline_analysis",
                "parameters": parameters,
            },
        ],
        "edges": [
            {
                "edge_id": "project-streamline",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "streamline",
                "target_port_id": "project",
            }
        ],
    }


def test_current_streamline_workflow_executes_with_lineage_and_replays(
    client: TestClient,
) -> None:
    project = create_project(client, "Current streamline workflow")
    parameters = _parameters(_current_records(client, project["id"]))
    graph = _graph(parameters)

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    definition = next(
        item for item in registry.json() if item["node_type"] == "current_streamline_analysis"
    )
    assert definition["executable"] is True
    assert definition["input_ports"][0]["accepted_types"] == ["project_reference"]
    assert definition["output_ports"][0]["accepted_types"] == ["environmental_analysis_result"]

    plan = client.post(f"/api/v1/projects/{project['id']}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True

    queued = save_and_queue(client, project["id"], graph)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued["job_id"])
    )
    detail_response = client.get(f"/api/v1/workflow-runs/{queued['id']}")
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "environmental_analysis_result"
    )
    payload = artifact["payload_json"]
    node = next(
        item for item in detail["nodes"] if item["node_type"] == "current_streamline_analysis"
    )
    assert payload["analysis_kind"] == "current_streamline"
    assert payload["payload"]["algorithm_version"] == "wgs84-stationary-bilinear-rk4-v1"
    assert payload["payload"]["streamlines"][0]["termination"] == "max_steps"
    assert payload["workflow_run_id"] == queued["id"]
    assert payload["workflow_node_run_id"] == node["id"]
    assert len(payload["content_sha256"]) == 64

    with app.state.session_factory() as session:
        replay = EnvironmentalAnalysisService(session).create_current_streamline(
            project["id"],
            CurrentFieldAnalysisRequest.model_validate(parameters),
            workflow_run_id=queued["id"],
            workflow_node_run_id=node["id"],
        )
        assert str(replay.result.id) == payload["result_id"]
        assert replay.result.content_sha256 == payload["content_sha256"]

        conflicting = {**parameters, "max_steps": 3}
        with pytest.raises(ConflictError, match="replay conflicts"):
            EnvironmentalAnalysisService(session).create_current_streamline(
                project["id"],
                CurrentFieldAnalysisRequest.model_validate(conflicting),
                workflow_run_id=queued["id"],
                workflow_node_run_id=node["id"],
            )


def test_failed_current_streamline_workflow_is_atomic(client: TestClient) -> None:
    project = create_project(client, "Incomplete workflow current")
    incomplete_ids = _current_records(client, project["id"])[:1]
    queued = save_and_queue(client, project["id"], _graph(_parameters(incomplete_ids)))
    app = cast(FastAPI, client.app)

    assert not process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued['id']}").json()
    assert detail["run"]["status"] == "failed"
    assert not any(
        item["data_type"] == "environmental_analysis_result" for item in detail["artifacts"]
    )
    with app.state.session_factory() as session:
        definition_count = session.scalar(
            select(func.count())
            .select_from(EnvironmentalAnalysisDefinition)
            .where(EnvironmentalAnalysisDefinition.project_id == project["id"])
        )
        result_count = session.scalar(
            select(func.count())
            .select_from(EnvironmentalAnalysisResult)
            .where(EnvironmentalAnalysisResult.project_id == project["id"])
        )
        assert definition_count == 0
        assert result_count == 0


def test_current_streamline_rejects_obsolete_environmental_snapshot(
    client: TestClient,
) -> None:
    project = create_project(client, "Obsolete current snapshot")
    record_ids = _current_records(client, project["id"])
    app = cast(FastAPI, client.app)
    cache_key = "a" * 64
    cache_payload = {
        "provider": "synthetic",
        "record_ids": [],
        "raw_response": {"fixture": True},
    }
    with app.state.session_factory() as session:
        session.add(
            EnvironmentalCacheEntry(
                project_id=project["id"],
                cache_key=cache_key,
                source_url="https://example.invalid/current-fixture",
                payload_json=cache_payload,
                content_sha256=content_hash(cache_payload),
                fetched_at=datetime(2026, 1, 2, tzinfo=UTC),
                expires_at=datetime(2026, 1, 3, tzinfo=UTC) + timedelta(days=1),
            )
        )
        for record_id in record_ids:
            row = session.get(ScientificRecord, record_id)
            assert row is not None
            row.payload_json = {**row.payload_json, "environmental_cache_key": cache_key}
            row.content_sha256 = content_hash(row.payload_json)
        session.commit()

        request = CurrentFieldAnalysisRequest.model_validate(_parameters(record_ids))
        with pytest.raises(ValidationError, match="environmental snapshot"):
            CurrentFieldService(session).preview(project["id"], request)

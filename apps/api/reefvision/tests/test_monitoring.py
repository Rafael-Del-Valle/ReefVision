"""Monitoring boundary and provenance checks through the project API."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models.scientific_record import ScientificRecord
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project

_START = datetime(2026, 11, 19, 13, tzinfo=UTC)
_END = _START + timedelta(minutes=5)
_PROTOCOL = "example-minute-temperature-v1"


def _root(client: TestClient, name: str = "Synthetic monitoring") -> str:
    return f"/api/v1/projects/{create_project(client, name)['id']}"


def _sample(
    minute: int,
    value: float = 20,
    unit: str = "degC",
    *,
    qc: str = "accepted",
    delay: int = 0,
    protocol: str | None = _PROTOCOL,
    source: str = "Synthetic logger",
) -> dict[str, Any]:
    observed = _START + timedelta(minutes=minute)
    metadata = {} if protocol is None else {"protocol": protocol}
    return {
        "variable": "water_temperature",
        "value": value,
        "unit": unit,
        "observed_at": observed.isoformat(),
        "source_kind": "observed",
        "qc": qc,
        "provenance": {
            "source": source,
            "acquired_at": (observed + timedelta(seconds=delay)).isoformat(),
            "source_metadata": metadata,
        },
    }


def _import(client: TestClient, root: str, *records: dict[str, Any]) -> list[dict[str, Any]]:
    response = client.post(root + "/scientific-records", json={"records": records})
    assert response.status_code == 201, response.text
    return response.json()["items"]


def _rule(client: TestClient, root: str, **overrides: Any) -> dict[str, Any]:
    rule = client.post(
        root + "/monitoring/rules",
        json={
            "label": "Minute temperatures",
            "kind": "environmental",
            "protocol": _PROTOCOL,
            "metric": "water_temperature",
            "unit": "degC",
            "parameters": {
                "cadence_seconds": 60,
                "lower_limit": 19,
                "upper_limit": 21,
                "max_drift": 1,
                "max_delay_seconds": 5,
            },
            **overrides,
        },
    )
    assert rule.status_code == 201, rule.text
    return rule.json()


def _assessment_body(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": rule["id"],
        "rule_sha256": rule["rule_sha256"],
        "window_start": _START.isoformat(),
        "window_end": _END.isoformat(),
    }


def _assess(client: TestClient, root: str, rule: dict[str, Any]) -> dict[str, Any]:
    response = client.post(root + "/monitoring/assessments", json=_assessment_body(rule))
    assert response.status_code == 201, response.text
    return response.json()


def _alerts(client: TestClient, root: str, assessment: dict[str, Any]) -> list[dict[str, Any]]:
    response = client.get(root + "/monitoring/alerts", params={"assessment_id": assessment["id"]})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_monitoring_uses_source_qc_canonical_units_and_human_review(client: TestClient) -> None:
    site_a = _root(client, "Synthetic site A")
    site_b = _root(client, "Synthetic site B")
    rules = {root: _rule(client, root) for root in (site_a, site_b)}
    a = _import(
        client, site_a, _sample(0), _sample(1), _sample(3, 71.6, "degF", delay=7), _sample(4)
    )
    _import(client, site_b, *(_sample(minute) for minute in range(5)))

    assessment = _assess(client, site_a, rules[site_a])
    result = assessment["result"]
    assert result["estimate"] == pytest.approx(20.5)
    assert result["effort"]["expected_slots"] == 5
    assert result["effort"]["observed_slots"] == 4
    assert result["effort"]["accepted_observations"] == 4
    assert result["effort"]["coverage_fraction"] == pytest.approx(0.8)
    assert [row["id"] for row in result["source_refs"]] == [row["id"] for row in a]
    assert canonical_json_sha256(result) == assessment["result_sha256"]
    assert assessment["source_status"] == "current"
    assert _assess(client, site_a, rules[site_a])["id"] == assessment["id"]
    findings = _alerts(client, site_a, assessment)
    assert {row["kind"] for row in findings} == {"drop", "delay", "drift", "upper_limit"}
    upper = next(row for row in findings if row["kind"] == "upper_limit")
    assert upper["status"] == "proposed"
    assert upper["proposal"]["value"] == pytest.approx(22)
    assert upper["proposal"]["source_ids"] == [a[2]["id"]]
    control = _assess(client, site_b, rules[site_b])
    assert control["result"]["estimate"] == 20
    assert control["result"]["effort"]["coverage_fraction"] == 1
    assert not _alerts(client, site_b, control)

    alert_root = site_a + "/monitoring/alerts/" + upper["id"]
    assert client.get(site_b + "/monitoring/alerts/" + upper["id"]).status_code == 404
    reviewed = client.post(
        alert_root + "/reviews",
        json={"expected_revision": 0, "decision": "confirmed", "reason": "Checked QC source"},
    )
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["reviewer"].startswith("local-user:")
    assert reviewed.json()["revision"] == 1
    after = client.get(alert_root).json()
    assert after["status"] == "confirmed"
    assert after["proposal_sha256"] == upper["proposal_sha256"]
    assert after["proposal"] == upper["proposal"]
    conflict = client.post(
        alert_root + "/reviews",
        json={"expected_revision": 0, "decision": "dismissed", "reason": "Outdated review"},
    )
    assert conflict.status_code == 409
    assert client.get(alert_root + "/reviews").json()["total"] == 1

    _import(client, site_a, _sample(2))
    stale_detail = client.get(site_a + "/monitoring/assessments/" + assessment["id"]).json()
    assert stale_detail["source_status"] == "stale"
    assert stale_detail["result_sha256"] == assessment["result_sha256"]
    assert stale_detail["result"] == result
    assert client.get(alert_root).json()["status"] == "confirmed"
    assert client.get(alert_root).json()["source_status"] == "stale"
    assert (
        client.post(
            alert_root + "/reviews",
            json={"expected_revision": 1, "decision": "dismissed", "reason": "Source changed"},
        ).status_code
        == 409
    )
    fresh = _assess(client, site_a, rules[site_a])
    assert fresh["id"] != assessment["id"]
    assert fresh["result"]["effort"]["observed_slots"] == 5
    assert all(row["kind"] != "drop" for row in _alerts(client, site_a, fresh))


def test_bad_unknown_protocol_and_duplicate_observations_have_no_numeric_weight(
    client: TestClient,
) -> None:
    project = _root(client)
    rule = _rule(client, project)
    records = _import(
        client,
        project,
        _sample(0, 30, qc="unassessed"),
        _sample(1, 30, qc="rejected"),
        _sample(2, 30, protocol=None),
        _sample(3, 30),
        _sample(3, 31),
        _sample(4, 30, qc="suspect"),
        _sample(5, 22),
    )
    assessment = _assess(client, project, rule)
    result = assessment["result"]
    assert result["estimate"] is None
    assert result["effort"]["observed_slots"] == 4
    assert result["effort"]["accepted_observations"] == 0
    assert result["effort"]["coverage_fraction"] == pytest.approx(0.8)
    assert {row["reason"] for row in result["exclusions"]} == {
        "qc_unassessed",
        "qc_rejected",
        "missing_protocol",
        "duplicate_slot",
        "qc_suspect",
    }
    assert {row["kind"] for row in result["findings"]} == {"drop"}
    assert all(row["id"] != records[-1]["id"] for row in result["source_refs"])


def test_monitoring_scope_utc_and_checksum_validation(client: TestClient) -> None:
    root = _root(client)
    other = _root(client, "Unrelated site")
    rule = _rule(client, root)
    body = _assessment_body(rule)
    assert client.post(other + "/monitoring/assessments", json=body).status_code == 404
    assert (
        client.post(
            root + "/monitoring/assessments", json={**body, "rule_sha256": "0" * 64}
        ).status_code
        == 409
    )
    assert (
        client.post(
            root + "/monitoring/assessments", json={**body, "window_end": "2026-11-19T13:05:00"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            root + "/monitoring/assessments",
            json={**body, "window_end": (_START + timedelta(days=32)).isoformat()},
        ).status_code
        == 422
    )

    (source,) = _import(client, root, _sample(0))
    saved = _assess(client, root, rule)
    app = cast(FastAPI, client.app)
    with app.state.session_factory.begin() as session:
        record = session.scalar(select(ScientificRecord).where(ScientificRecord.id == source["id"]))
        assert record is not None
        record.payload_json = {**record.payload_json, "normalized_value": 99}
    read = client.get(root + "/monitoring/assessments/" + saved["id"])
    assert read.status_code == 200, read.text
    assert read.json()["source_status"] == "stale"
    assert read.json()["result"]["estimate"] == 20
    current = _assess(client, root, rule)["result"]
    assert current["estimate"] is None
    assert "source_integrity" in {row["reason"] for row in current["exclusions"]}


def test_monitoring_decisions_are_serialized_and_preserve_full_history(client: TestClient) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    root = _root(client)
    rule = _rule(client, root)
    _import(client, root, _sample(0, 22))
    saved = _assess(client, root, rule)
    alert = next(row for row in _alerts(client, root, saved) if row["kind"] == "upper_limit")
    path = root + "/monitoring/alerts/" + alert["id"] + "/reviews"
    barrier = Barrier(2)

    def review(decision: str) -> int:
        barrier.wait(timeout=5)
        return client.post(
            path,
            json={"expected_revision": 0, "decision": decision, "reason": "Independent check"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(review, ["confirmed", "dismissed"])) == [201, 409]
    (first,) = client.get(path).json()["items"]
    assert first["revision"] == 1
    _second = client.post(
        path,
        json={"expected_revision": 1, "decision": "dismissed", "reason": "New local disposition"},
    )
    assert _second.status_code == 201, _second.text
    page = client.get(path, params={"limit": 1, "offset": 1}).json()
    assert page == {"items": [first], "total": 2, "limit": 1, "offset": 1}


def test_replayed_monitoring_receipt_and_atomic_scheduled_occurrence(client: TestClient) -> None:
    from reefvision.jobs.workflow import process_workflow_run_job
    from reefvision.jobs.workflow_schedules import dispatch_due_schedules
    from reefvision.tests.test_workflow_execution_phase10 import _queue_run, _save_graph

    root = _root(client)
    project = root.split("/")[-1]
    rule = _rule(client, root)
    _import(client, root, _sample(0), _sample(1), _sample(2, 22), _sample(3), _sample(4))
    initial = _assess(client, root, rule)

    def make_graph(name: str, **parameters: Any) -> dict[str, object]:
        return {
            "graph_id": name,
            "name": name,
            "nodes": [
                {"node_id": "project", "node_type": "project_source"},
                {
                    "node_id": "monitor",
                    "node_type": "monitoring_assessment",
                    "parameters": {
                        "rule_id": rule["id"],
                        "rule_sha256": rule["rule_sha256"],
                        **parameters,
                    },
                },
            ],
            "edges": [
                {
                    "edge_id": "project-monitor",
                    "source_node_id": "project",
                    "source_port_id": "project",
                    "target_node_id": "monitor",
                    "target_port_id": "project",
                }
            ],
        }

    app = cast(FastAPI, client.app)
    settings, factory = app.state.settings, app.state.session_factory

    def receipt(job_id: str, run_id: str) -> dict[str, Any]:
        assert process_workflow_run_job(settings, factory, job_id)
        detail = client.get("/api/v1/workflow-runs/" + run_id).json()
        assert detail["run"]["status"] == "succeeded"
        (artifact,) = [
            row for row in detail["artifacts"] if row["data_type"] == "monitoring_assessment"
        ]
        assert canonical_json_sha256(artifact["payload_json"]) == artifact["payload_sha256"]
        return artifact

    saved = _save_graph(client, project, make_graph("scheduled-monitoring", window_seconds=300))
    schedule = client.post(
        root + "/workflow-schedules",
        json={
            "name": "Monitoring once",
            "purpose": "report",
            "workflow_graph_record_id": saved["id"],
            "interval_seconds": 86400,
            "next_due_at": _END.isoformat(),
        },
    )
    assert schedule.status_code == 201, schedule.text
    schedule_body = schedule.json()
    assert any(
        pin["id"] == rule["id"] and pin["sha256"] == rule["rule_sha256"]
        for pin in schedule_body["inputs"]["references"]
    )
    assert dispatch_due_schedules(settings, factory, now=_END + timedelta(seconds=2)) == 1
    path = root + "/workflow-schedules/" + schedule_body["id"]
    (queued,) = client.get(path + "/occurrences").json()["items"]
    scheduled = receipt(queued["job_id"], queued["workflow_run_id"])
    assert scheduled["payload_json"]["assessment_id"] == initial["id"]
    assert scheduled["payload_json"]["result_sha256"] == initial["result_sha256"]

    replay = _save_graph(
        client,
        project,
        make_graph(
            "sealed-monitoring",
            assessment_id=initial["id"],
            assessment_sha256=initial["result_sha256"],
        ),
    )
    invalid_schedule = client.post(
        root + "/workflow-schedules",
        json={
            "name": "Pinned history can be opened manually",
            "purpose": "report",
            "workflow_graph_record_id": replay["id"],
            "interval_seconds": 86400,
            "next_due_at": _END.isoformat(),
        },
    )
    assert invalid_schedule.status_code == 400
    _import(client, root, _sample(2))
    assert (
        client.get(root + "/monitoring/assessments/" + initial["id"]).json()["source_status"]
        == "stale"
    )
    for _ in range(2):
        replay_run = _queue_run(client, project, replay["id"])
        repeated = receipt(str(replay_run["job_id"]), str(replay_run["id"]))
        assert repeated["payload_json"] == scheduled["payload_json"]
        assert repeated["payload_sha256"] == scheduled["payload_sha256"]
    assert client.get(root + "/monitoring/assessments").json()["total"] == 1

    invalid_pin = _save_graph(
        client,
        project,
        make_graph("wrong-monitoring-pin", window_seconds=300, rule_sha256="0" * 64),
    )
    wrong = client.post(
        root + "/workflow-schedules",
        json={
            "name": "Wrong rule pin",
            "purpose": "report",
            "workflow_graph_record_id": invalid_pin["id"],
            "interval_seconds": 86400,
            "next_due_at": _END.isoformat(),
        },
    )
    assert wrong.status_code == 400

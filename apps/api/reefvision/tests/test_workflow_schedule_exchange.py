"""A copied project retains scheduled results and waits for the local researcher to resume."""

import json
from datetime import UTC, datetime
from io import BytesIO
from typing import cast
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    WorkflowRun,
    WorkflowSchedule,
    WorkflowScheduleOccurrence,
)
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.jobs.workflow_schedules import dispatch_due_schedules
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_dataset_versions import create_version
from reefvision.tests.test_paired_growth_contrast import _run_graph
from reefvision.tests.test_scientific_project_exchange import (
    MANIFEST,
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
    _frozen_graph,
    _study,
)


def test_exchange_preserves_scheduled_qc_and_disarms_the_copy(
    client: TestClient, test_settings: Settings
) -> None:
    project, _, _, _ = _study(client)
    version = create_version(client, project, name="Frozen QC originals")["id"]
    saved = client.post(
        f"/api/v1/projects/{project}/workflow-graphs", json={"graph": _frozen_graph(version)}
    )
    assert saved.is_success, saved.text
    graph = saved.json()
    factory = cast(FastAPI, client.app).state.session_factory
    schedules_url = f"/api/v1/projects/{project}/workflow-schedules"
    created = client.post(
        schedules_url,
        json={
            "name": version,
            "purpose": "qc",
            "workflow_graph_record_id": graph["id"],
            "interval_seconds": 60,
            "next_due_at": "2026-05-08T10:00:00Z",
        },
    )
    assert created.is_success, created.text
    schedule_id = created.json()["id"]
    assert (
        dispatch_due_schedules(test_settings, factory, now=datetime(2026, 5, 8, 10, 2, tzinfo=UTC))
        == 1
    )
    [dispatched] = client.get(f"{schedules_url}/{schedule_id}/occurrences").json()["items"]
    occurrence_id, run = dispatched["id"], dispatched["workflow_run_id"]
    assert dispatched["missed_intervals"] == 2
    assert process_workflow_run_job(test_settings, factory, dispatched["job_id"])
    endpoint = f"/api/v1/projects/{project}/workflow-schedule-occurrences/{occurrence_id}/receipt"
    response = client.get(endpoint)
    assert response.is_success, response.text
    evidence = response.json()
    assert evidence["receipt_sha256"] == canonical_json_sha256(evidence["receipt"])
    assert evidence["receipt"]["workflow_run_id"] == run
    assert any(a["data_type"] == "review_queue_reference" for a in evidence["receipt"]["artifacts"])
    receipt_graph = {
        "graph_id": "inspect-slot",
        "name": "Inspect completed scheduled QC",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "receipt",
                "node_type": "workflow_schedule_receipt",
                "parameters": {
                    "occurrence_id": occurrence_id,
                    "scheduled_at": evidence["receipt"]["scheduled_at"],
                },
            },
        ],
        "edges": [
            {
                "edge_id": "input",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "receipt",
                "target_port_id": "project",
            }
        ],
    }
    saved_receipt = client.post(
        f"/api/v1/projects/{project}/workflow-graphs", json={"graph": receipt_graph}
    )
    assert saved_receipt.is_success, saved_receipt.text
    receipt_graph_id = saved_receipt.json()["id"]
    for _ in range(2):
        result = _run_graph(client, project, receipt_graph_id)
        assert result["run"]["status"] == "succeeded", result
        [artifact] = [
            a for a in result["artifacts"] if a["data_type"] == "workflow_schedule_receipt"
        ]
        assert artifact["payload_json"] == evidence
    raw = export_archive(client, test_settings, project)
    with ZipFile(BytesIO(raw)) as archive:
        assert json.loads(archive.read(MANIFEST))["format_version"] == "1.7"

    def damage(_, sections):
        sections["workflow_schedule_occurrences"][0]["inputs_sha256"] = "a" * 64

    def reassign_input(_, sections):
        record = sections["workflow_schedules"][0]
        record["inputs_json"]["references"][0]["id"] = project
        record["inputs_sha256"] = canonical_json_sha256(record["inputs_json"])
        sections["workflow_schedule_occurrences"][0]["inputs_sha256"] = record["inputs_sha256"]
        next(r for r in sections["workflow_runs"] if r["id"] == run)["input_json"] = record[
            "inputs_json"
        ]

    counts = database_counts(client)
    for corrupt in (damage, reassign_input):
        refused = import_archive(client, rewrite(raw, corrupt))
        assert refused.status_code == 400, refused.text
        assert database_counts(client) == counts
    for _ in range(2):
        restored = import_archive(client, raw)
        assert restored.is_success, restored.text
        origin = restored.json()["package"]["options_json"]["origin_id_map"]
        with factory() as session:
            copied = session.get(WorkflowSchedule, origin[schedule_id])
            slot = session.get(WorkflowScheduleOccurrence, origin[occurrence_id])
            dataset = session.get(DatasetVersion, origin[version])
            assert copied is not None and slot is not None and dataset is not None
            assert copied.name == version and not copied.enabled
            assert slot.workflow_run_id == origin[run] and slot.missed_intervals == 2
            assert copied.workflow_graph_record_id == origin[graph["id"]]
            assert copied.graph_sha256 == slot.graph_sha256
            assert (
                copied.inputs_sha256
                == slot.inputs_sha256
                == canonical_json_sha256(copied.inputs_json)
            )
            [pin] = copied.inputs_json["references"]
            assert pin["id"] == dataset.id and pin["sha256"] == dataset.manifest_sha256
            copied_run = session.get(WorkflowRun, origin[run])
            assert copied_run is not None and copied_run.input_json == copied.inputs_json
        detail = _run_graph(client, origin[project], origin[receipt_graph_id])
        assert detail["run"]["status"] == "succeeded", detail
        [artifact] = [
            a for a in detail["artifacts"] if a["data_type"] == "workflow_schedule_receipt"
        ]
        assert artifact["payload_json"]["receipt"]["workflow_run_id"] == origin[run]
        raw = export_archive(client, test_settings, origin[project])

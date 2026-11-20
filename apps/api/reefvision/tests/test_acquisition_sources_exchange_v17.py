"""Trusted local pins, receipts, and explicit approval across two Exchange generations."""

from datetime import UTC, datetime
from json import dumps
from uuid import uuid4

from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.jobs.workflow_schedules import dispatch_due_schedules
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_acquisition_sources_v17 import (
    _acquisition_graph,
    capture,
    check,
    png,
    project,
    source_create,
)
from reefvision.tests.test_paired_growth_contrast import _run_graph
from reefvision.tests.test_scientific_project_exchange import (
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)


def test_exchange_preserves_field_observation_and_scheduled_receipt_replays(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project_id = project(client)
    project_route = f"/api/v1/projects/{project_id}"
    acquisition_root = f"{project_route}/acquisition-sources"
    field_root = f"{project_route}/field-capture/batches"
    batch = check(client.post(field_root, json={"label": project_id}), 201)
    snapshot = check(
        client.post(
            f"{field_root}/{batch['id']}/observations",
            data={
                "metadata": dumps(
                    {
                        "observer": "Generated observer",
                        "clock": {
                            "state": "known_offset",
                            "wall_time": "2025-07-22T08:03:00",
                            "utc_offset_minutes": -240,
                            "evidence": project_id,
                        },
                    }
                )
            },
            files={"file": (f"{project_id}.png", png(), "image/png")},
        ),
        201,
    )
    sealed = check(client.post(f"{field_root}/{batch['id']}/seal"), 200)
    recorded = check(
        client.post(
            acquisition_root,
            json={
                "label": project_id,
                "configuration": {
                    "kind": "recorded",
                    "batch_id": sealed["id"],
                    "manifest_sha256": sealed["manifest_sha256"],
                },
            },
        ),
        201,
    )
    manual = check(
        capture(client, f"{acquisition_root}/{recorded['id']}", recorded, str(uuid4())), 200
    )
    manual_replay = _acquisition_graph(
        client,
        project_id,
        "acquisition_capture_replay",
        {
            "capture_id": manual["receipt"]["id"],
            "content_sha256": manual["content_sha256"],
        },
    )
    assert _run_graph(client, project_id, manual_replay["id"])["run"]["status"] == "succeeded"

    _, camera = source_create(client, project_id, {"kind": "camera", "camera_index": 15})
    camera_state = check(
        client.patch(
            f"{acquisition_root}/{camera['id']}/state",
            json={
                "action": "approve_camera",
                "revision": camera["revision"],
            },
        ),
        200,
    )
    assert camera_state["local_consent_until"] is not None

    _, simulator = source_create(
        client,
        project_id,
        {
            "kind": "simulated",
            "seed": 17,
            "start_at_utc": "2026-01-01T00:00:00Z",
            "period_seconds": 300,
        },
    )
    graph = _acquisition_graph(
        client,
        project_id,
        "acquisition_source_capture",
        {
            "source_id": simulator["id"],
            "source_sha256": simulator["source_sha256"],
        },
    )
    schedule_route = f"{project_route}/workflow-schedules"
    due = datetime(2026, 1, 1, 1, tzinfo=UTC)
    schedule = check(
        client.post(
            schedule_route,
            json={
                "name": "Generated simulated source",
                "purpose": "acquisition",
                "workflow_graph_record_id": graph["id"],
                "interval_seconds": 300,
                "next_due_at": due.isoformat(),
            },
        ),
        201,
    )
    factory = client.app.state.session_factory
    assert dispatch_due_schedules(test_settings, factory, now=due) == 1
    [occurrence] = check(client.get(f"{schedule_route}/{schedule['id']}/occurrences"), 200)["items"]
    assert process_workflow_run_job(test_settings, factory, occurrence["job_id"])
    run_endpoint = "/api/v1/workflow-runs/"
    detail = check(client.get(run_endpoint + occurrence["workflow_run_id"]), 200)
    original_simulation = next(
        artifact["payload_json"]
        for artifact in detail["artifacts"]
        if artifact["data_type"] == "acquisition_capture_receipt"
    )
    archive = export_archive(client, test_settings, project_id)

    def corrupt_field_clock(_, rows):
        body = next(
            row for row in rows["acquisition_captures"] if row["source_id"] == recorded["id"]
        )
        body["receipt_json"]["time"]["clock"]["evidence"] = "Forged clock attribution"
        body["content_sha256"] = canonical_json_sha256(body["receipt_json"])

    def corrupt_scheduled_slot(_, rows):
        body = next(
            row for row in rows["acquisition_captures"] if row["source_id"] == simulator["id"]
        )
        dispatch = body["receipt_json"]["dispatch"]
        dispatch["occurrence_id"] = str(uuid4())
        body["capture_key"] = f"schedule:{dispatch['occurrence_id']}:{dispatch['node_id']}"
        body["content_sha256"] = canonical_json_sha256(body["receipt_json"])

    before = database_counts(client)
    for corrupt in (corrupt_field_clock, corrupt_scheduled_slot):
        result = import_archive(client, rewrite(archive, corrupt))
        assert result.status_code == 400, result.text
        assert "Acquisition Exchange evidence is invalid" in result.text
        assert database_counts(client) == before

    last_project = project_id
    for _ in range(2):
        copied = check(import_archive(client, archive), 201)
        aliases = copied["package"]["options_json"]["origin_id_map"]
        local_project = aliases[project_id]
        assert local_project == copied["project_id"] != last_project
        local_root = f"/api/v1/projects/{local_project}/acquisition-sources"
        for original_source, cursor in ((recorded, 1), (simulator, 1), (camera, 0)):
            local_source = check(client.get(f"{local_root}/{aliases[original_source['id']]}"), 200)
            assert local_source["state"] == "paused"
            assert local_source["local_consent_until"] is None
            assert local_source["cursor"] == cursor
            assert local_source["source_sha256"] != original_source["source_sha256"]

        recorded_id = aliases[recorded["id"]]
        rebound = check(client.get(f"{local_root}/{recorded_id}"), 200)
        assert rebound["label"] == project_id
        assert rebound["configuration"]["batch_id"] == aliases[sealed["id"]]
        result = _run_graph(client, local_project, aliases[manual_replay["id"]])
        assert result["run"]["status"] == "succeeded", result
        [rewound] = [
            item["payload_json"]
            for item in result["artifacts"]
            if item["data_type"] == "acquisition_capture_receipt"
        ]
        local_record = rewound["receipt"]
        assert local_record["id"] == aliases[manual["receipt"]["id"]]
        assert local_record["project_id"] == local_project
        assert local_record["media"]["field_observation_id"] == aliases[snapshot["id"]]
        assert local_record["media"]["original_observation_id"] == snapshot["source_observation_id"]
        assert local_record["media"]["filename"] == f"{project_id}.png"
        assert local_record["media"]["sha256"] == snapshot["sha256"]
        assert local_record["time"] == manual["receipt"]["time"]
        assert rewound["content_sha256"] == canonical_json_sha256(local_record)

        history = check(client.get(run_endpoint + aliases[occurrence["workflow_run_id"]]), 200)
        [retained] = [
            item["payload_json"]
            for item in history["artifacts"]
            if item["data_type"] == "acquisition_capture_receipt"
        ]
        assert retained == original_simulation
        local_sim_id = aliases[simulator["id"]]
        [current] = check(client.get(f"{local_root}/{local_sim_id}/captures"), 200)["items"]
        assert current["receipt"]["dispatch"]["occurrence_id"] == aliases[occurrence["id"]]
        assert (
            current["receipt"]["dispatch"]["workflow_run_id"]
            == aliases[occurrence["workflow_run_id"]]
        )
        assert (
            current["receipt"]["synthetic_reading"]
            == original_simulation["receipt"]["synthetic_reading"]
        )
        archive = export_archive(client, test_settings, local_project)
        last_project = local_project

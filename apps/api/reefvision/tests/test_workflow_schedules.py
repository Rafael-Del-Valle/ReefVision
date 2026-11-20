"""Durable project schedule contracts through the normal workflow API."""

import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from multiprocessing.connection import Connection
from pathlib import Path
from threading import Barrier, Event
from time import monotonic, sleep
from typing import Any, Literal, cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration, WorkflowGraphRecord, WorkflowRun
from reefvision.db.session import create_database_engine, create_session_factory
from reefvision.jobs.worker import recover_interrupted_jobs
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.jobs.workflow_schedules import dispatch_due_schedules
from reefvision.services.workflow_execution import WorkflowExecutionService
from reefvision.services.workflow_graphs import WorkflowGraphService
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_workflow_execution_phase10 import _project_images_graph, _save_graph
from reefvision.tests.test_workflow_review_queue_16 import _graph as qc_graph


def _project_fixture(client: TestClient, name: str = "Schedule QC") -> tuple[str, str, str]:
    project_id = str(create_project(client, name)["id"])
    imported = import_one(client, project_id, filename="schedule-qc.png", relative_path="qc.png")
    assert len(imported["successful"]) == 1
    graph = _save_graph(client, project_id, qc_graph())
    return project_id, str(graph["id"]), str(graph["graph_sha256"])


def _schedule_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/workflow-schedules"


def _settings(graph_id: str, due_at: datetime, **overrides: Any) -> dict[str, Any]:
    return {
        "name": "Recurring proposal triage",
        "purpose": "qc",
        "workflow_graph_record_id": graph_id,
        "interval_seconds": 60,
        "next_due_at": due_at.isoformat(),
        **overrides,
    }


def test_create_list_and_edit_schedule_with_pinned_revision(client: TestClient) -> None:
    project_id, graph_id, graph_hash = _project_fixture(client)
    root = _schedule_url(project_id)
    due_at = datetime(2026, 2, 5, 12, tzinfo=UTC)
    response = client.post(root, json=_settings(graph_id, due_at))
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["workflow_graph_record_id"] == graph_id
    assert saved["graph_sha256"] == graph_hash
    assert datetime.fromisoformat(saved["next_due_at"]) == due_at
    assert saved["inputs"] == {}
    assert len(saved["inputs_sha256"]) == 64
    assert saved["enabled"] is True
    assert saved["revision"] == 1
    assert client.get(root).json() == {"items": [saved], "total": 1}
    assert client.get(root, params={"limit": 1, "offset": 1}).json() == {"items": [], "total": 1}

    endpoint = f"{root}/{saved['id']}"
    paused = client.patch(endpoint, json={"expected_revision": 1, "enabled": False})
    assert paused.status_code == 200, paused.text
    assert paused.json()["last_status"] == "paused"
    assert paused.json()["enabled"] is False
    assert paused.json()["revision"] == 2
    assert client.patch(endpoint, json={"expected_revision": 1, "enabled": True}).status_code == 409

    other_project = create_project(client, "Unrelated project")["id"]
    assert (
        client.patch(
            f"{_schedule_url(str(other_project))}/{saved['id']}",
            json={"expected_revision": 2, "enabled": True},
        ).status_code
        == 404
    )


def test_schedule_rejects_wrong_scope_purpose_and_unpinned_override(client: TestClient) -> None:
    project_id, graph_id, _ = _project_fixture(client)
    due_at = datetime(2026, 2, 5, 12, tzinfo=UTC) + timedelta(seconds=1)
    root = _schedule_url(project_id)
    other_project = str(create_project(client, "Foreign graph owner")["id"])
    foreign_record = str(_save_graph(client, other_project, qc_graph())["id"])
    source_only = str(_save_graph(client, project_id, _project_images_graph())["id"])
    for payload, expected in (
        (_settings(foreign_record, due_at), 400),
        (_settings(source_only, due_at), 400),
        (_settings(graph_id, due_at, purpose="inference"), 400),
        (_settings(graph_id, due_at, next_due_at="2026-02-05T12:00:00"), 422),
        (_settings(graph_id, due_at, next_due_at=1_780_000_000), 422),
        (_settings(graph_id, due_at, next_due_at="1780000000"), 422),
        (_settings(graph_id, due_at, interval_seconds=0), 422),
        (_settings(graph_id, due_at, inputs={"model_id": "not a graph pin"}), 400),
        (_settings(graph_id, due_at, now="2030-01-01T00:00:00Z"), 422),
    ):
        response = client.post(root, json=payload)
        assert response.status_code == expected, response.text
    assert client.get(root).json() == {"items": [], "total": 0}


_DUE = datetime(2026, 2, 5, 12, tzinfo=UTC)


def _create(client: TestClient, **overrides: Any) -> tuple[str, dict[str, Any]]:
    project_id, graph_id, _ = _project_fixture(client)
    response = client.post(_schedule_url(project_id), json=_settings(graph_id, _DUE, **overrides))
    assert response.status_code == 201, response.text
    value = response.json()
    return f"{_schedule_url(project_id)}/{value['id']}", value


def test_due_slot_stages_and_runs_the_known_qc_graph(client: TestClient) -> None:
    endpoint, saved = _create(client)
    app = cast(FastAPI, client.app)
    settings, factory = app.state.settings, app.state.session_factory
    now = _DUE + timedelta(seconds=125)
    assert dispatch_due_schedules(settings, factory, now=now) == 1
    assert dispatch_due_schedules(settings, factory, now=now) == 0

    history = endpoint + "/occurrences"
    occurrences = client.get(history).json()
    assert occurrences["total"] == 1
    item = occurrences["items"][0]
    assert datetime.fromisoformat(item["scheduled_at"]) == _DUE + timedelta(seconds=120)
    assert item["missed_intervals"] == 2
    assert item["status"] == "queued"
    assert item["graph_sha256"] == saved["graph_sha256"]
    assert item["inputs_sha256"] == saved["inputs_sha256"]
    current = client.get(_schedule_url(saved["project_id"])).json()["items"][0]
    assert datetime.fromisoformat(current["next_due_at"]) == _DUE + timedelta(seconds=180)
    assert current["revision"] == 1

    assert process_workflow_run_job(settings, factory, item["job_id"])
    assert not process_workflow_run_job(settings, factory, item["job_id"])
    finished = client.get(history).json()["items"][0]
    assert finished["status"] == "succeeded"
    assert finished["workflow_run_id"] == item["workflow_run_id"]
    result = client.get("/api/v1/workflow-runs/" + item["workflow_run_id"]).json()
    assert result["run"]["workflow_graph_record_id"] == saved["workflow_graph_record_id"]
    queue = next(row for row in result["artifacts"] if row["data_type"] == "review_queue_reference")
    assert queue["payload_json"]["item_count"] == 1
    assert client.get(history, params={"limit": 1, "offset": 1}).json()["items"] == []
    assert client.post(history + "/" + item["id"] + "/cancel").status_code == 409


def test_parallel_poll_and_retry_keep_one_durable_occurrence(client: TestClient) -> None:
    endpoint, saved = _create(client)
    app = cast(FastAPI, client.app)
    settings, factory = app.state.settings, app.state.session_factory
    barrier = Barrier(2)

    def poll() -> int:
        barrier.wait(timeout=5)
        return dispatch_due_schedules(settings, factory, now=_DUE)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: poll(), range(2))) == [0, 1]
    history = endpoint + "/occurrences"
    item = client.get(history).json()["items"][0]
    with factory.begin() as session:
        assert len(list(session.scalars(select(WorkflowRun)))) == 1
        session.get_one(Job, item["job_id"]).status = "running"
        session.get_one(WorkflowRun, item["workflow_run_id"]).status = "running"
    assert recover_interrupted_jobs(factory, settings) >= 1
    assert client.get(history).json()["items"][0]["status"] == "queued"

    assert dispatch_due_schedules(settings, factory, now=_DUE + timedelta(minutes=1)) == 0
    state = client.get(_schedule_url(saved["project_id"])).json()["items"][0]
    assert state["last_status"] == "waiting_previous_run"
    cancel = history + "/" + item["id"] + "/cancel"
    assert client.post(cancel).json()["status"] == "cancelled"
    assert client.post(cancel).json()["status"] == "cancelled"
    assert not process_workflow_run_job(settings, factory, item["job_id"])
    pause = client.patch(endpoint, json={"enabled": False, "expected_revision": 1})
    assert pause.status_code == 200, pause.text
    assert dispatch_due_schedules(settings, factory, now=_DUE + timedelta(minutes=2)) == 0
    # An explicit rewind to the already committed slot is deduplicated after restart.
    resume = client.patch(
        endpoint, json={"enabled": True, "expected_revision": 2, "next_due_at": _DUE.isoformat()}
    )
    assert resume.status_code == 200, resume.text
    assert dispatch_due_schedules(settings, factory, now=_DUE) == 0
    assert client.get(history).json()["total"] == 1


def test_storage_block_and_changed_saved_graph_are_visible(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint, saved = _create(client, minimum_free_bytes=2_000)
    app = cast(FastAPI, client.app)
    settings, factory = app.state.settings, app.state.session_factory
    monkeypatch.setattr(
        "reefvision.services.workflow_schedules.available_storage_bytes", lambda _: 1_999
    )
    assert dispatch_due_schedules(settings, factory, now=_DUE) == 0
    state = client.get(_schedule_url(saved["project_id"])).json()["items"][0]
    assert state["last_status"] == "blocked_storage"
    assert "2000" in state["last_message"]
    assert datetime.fromisoformat(state["next_due_at"]) == _DUE
    assert client.get(endpoint + "/occurrences").json()["total"] == 0

    monkeypatch.setattr(
        "reefvision.services.workflow_schedules.available_storage_bytes", lambda _: 3_000
    )
    with factory.begin() as session:
        graph = session.get_one(WorkflowGraphRecord, saved["workflow_graph_record_id"])
        graph.graph_json = {**graph.graph_json, "name": "Changed after schedule approval"}
    assert dispatch_due_schedules(settings, factory, now=_DUE) == 1
    failed = client.get(endpoint + "/occurrences").json()["items"][0]
    assert failed["status"] == "failed"
    assert "checksum" in failed["detail"]
    assert failed["workflow_run_id"] is None
    assert failed["job_id"] is None


@pytest.mark.parametrize("unavailable_after", ["schedule", "queue", "other_project"])
def test_unavailable_model_names_the_node_without_starting_inference(
    client: TestClient,
    unavailable_after: str,
) -> None:
    project_id = str(create_project(client, "Scheduled detector")["id"])
    app = cast(FastAPI, client.app)
    settings, factory = app.state.settings, app.state.session_factory
    with factory.begin() as session:
        model = ModelRegistration(
            project_id=project_id,
            purpose="detector",
            display_name="Private fixture model",
            source_filename="detector.pt",
            managed_path=f"projects/{project_id}/models/detector.pt",
            sha256="d" * 64,
            file_size_bytes=10,
            framework="test",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={},
            input_size_json={"width": 640, "height": 640},
            metadata_json={},
        )
        session.add(model)
        session.flush()
        model_id = model.id

    graph = {
        "graph_id": "scheduled-detector",
        "name": "Scheduled detector",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "images", "node_type": "project_images"},
            {
                "node_id": "detector-source",
                "node_type": "registered_model_source",
                "parameters": {"model_id": model_id},
            },
            {"node_id": "detect", "node_type": "detection_inference"},
        ],
        "edges": [
            {
                "edge_id": f"{source}-{target}",
                "source_node_id": source,
                "source_port_id": port,
                "target_node_id": target,
                "target_port_id": port,
            }
            for source, target, port in (
                ("project", "images", "project"),
                ("project", "detector-source", "project"),
                ("images", "detect", "images"),
                ("detector-source", "detect", "model"),
            )
        ],
    }
    saved = _save_graph(client, project_id, graph)
    schedule = client.post(
        _schedule_url(project_id),
        json=_settings(str(saved["id"]), _DUE, purpose="inference"),
    )
    assert schedule.status_code == 201, schedule.text
    endpoint = f"{_schedule_url(project_id)}/{schedule.json()['id']}/occurrences"
    if unavailable_after == "queue":
        assert dispatch_due_schedules(settings, factory, now=_DUE) == 1
        queued = client.get(endpoint).json()["items"][0]
        assert queued["status"] == "queued"

    if unavailable_after == "other_project":
        other = create_project(client, "Unrelated private project")
        with factory.begin() as session:
            session.get_one(ModelRegistration, model_id).project_id = other["id"]
    else:
        removed = client.delete(f"/api/v1/models/{model_id}")
        assert removed.status_code == 204, removed.text

    workflows = f"/api/v1/projects/{project_id}/workflow-runs"
    manual = client.post(workflows, json={"graph_record_id": saved["id"]})
    reason = (
        "Registered Model (detector-source) — The selected model is unavailable in this project"
    )
    assert manual.status_code == 400, manual.text
    assert manual.json()["detail"] == f"Workflow graph is no longer valid. {reason}"
    if unavailable_after == "queue":
        assert not process_workflow_run_job(settings, factory, queued["job_id"])
        detail = client.get(f"/api/v1/workflow-runs/{queued['workflow_run_id']}").json()
        assert detail["run"]["status"] == "failed"
        assert detail["artifacts"] == []
        expected = f"Workflow graph no longer validates. {reason}"
        assert detail["run"]["error_message"] == expected
    else:
        assert dispatch_due_schedules(settings, factory, now=_DUE) == 1
        expected = manual.json()["detail"]

    history = client.get(endpoint).json()
    assert history["total"] == 1
    failed = history["items"][0]
    assert failed["status"] == "failed"
    assert failed["detail"] == expected
    assert failed["graph_sha256"] == saved["graph_sha256"]
    with factory() as session:
        record = session.get_one(WorkflowGraphRecord, saved["id"])
        assert record.graph_sha256 == saved["graph_sha256"]
        assert record.graph_json == saved["graph_json"]
        assert list(session.scalars(select(Job).where(Job.job_type == "inference"))) == []
        run_ids = list(session.scalars(select(WorkflowRun.id)))
        job_ids = list(session.scalars(select(Job.id).where(Job.job_type == "workflow_run")))
        if unavailable_after == "queue":
            assert run_ids == [failed["workflow_run_id"]] == [queued["workflow_run_id"]]
            assert job_ids == [failed["job_id"]] == [queued["job_id"]]
        else:
            assert failed["workflow_run_id"] is None
            assert failed["job_id"] is None
            assert run_ids == []
            assert job_ids == []


def test_failed_dispatch_rolls_back_workflow_and_reuses_the_slot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint, saved = _create(client)
    app = cast(FastAPI, client.app)
    settings, factory = app.state.settings, app.state.session_factory
    original = WorkflowExecutionService.stage_run

    def fail_after_staging(*args: Any, **kwargs: Any) -> Any:
        original(*args, **kwargs)
        raise RuntimeError("Injected failure after staging before outer commit")

    with monkeypatch.context() as patch:
        patch.setattr(WorkflowExecutionService, "stage_run", fail_after_staging)
        assert dispatch_due_schedules(settings, factory, now=_DUE) == 0
    state = client.get(_schedule_url(saved["project_id"])).json()["items"][0]
    assert state["last_status"] == "dispatch_failed"
    assert datetime.fromisoformat(state["next_due_at"]) == _DUE
    assert client.get(endpoint + "/occurrences").json()["total"] == 0
    with factory() as session:
        assert list(session.scalars(select(WorkflowRun))) == []
        assert list(session.scalars(select(Job).where(Job.job_type == "workflow_run"))) == []
    assert dispatch_due_schedules(settings, factory, now=_DUE) == 1
    assert client.get(endpoint + "/occurrences").json()["total"] == 1


def test_two_workers_cannot_claim_one_scheduled_workflow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint, _ = _create(client)
    app = cast(FastAPI, client.app)
    settings, factory = app.state.settings, app.state.session_factory
    assert dispatch_due_schedules(settings, factory, now=_DUE) == 1
    item = client.get(endpoint + "/occurrences").json()["items"][0]
    original = WorkflowGraphService.plan
    barrier = Barrier(2)

    def synchronize(*args: Any, **kwargs: Any) -> Any:
        plan = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return plan

    monkeypatch.setattr(WorkflowGraphService, "plan", synchronize)
    execute_node = WorkflowExecutionService.execute_node
    release_first = Event()
    source_calls: list[str] = []

    def witness_execution(service: WorkflowExecutionService, **kwargs: Any) -> Any:
        if kwargs["step"].node_id == "project":
            source_calls.append(kwargs["step"].node_id)
            if len(source_calls) == 1:
                release_first.wait(timeout=0.8)
            else:
                release_first.set()
        return execute_node(service, **kwargs)

    monkeypatch.setattr(WorkflowExecutionService, "execute_node", witness_execution)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: process_workflow_run_job(settings, factory, item["job_id"]), range(2)
            )
        )
    assert source_calls == ["project"]
    assert sorted(results) == [False, True]
    assert client.get(endpoint + "/occurrences").json()["items"][0]["status"] == "succeeded"


def test_worker_refuses_changed_pins_before_executing_nodes(client: TestClient) -> None:
    endpoint, _ = _create(client)
    app = cast(FastAPI, client.app)
    settings, factory = app.state.settings, app.state.session_factory
    assert dispatch_due_schedules(settings, factory, now=_DUE) == 1
    item = client.get(endpoint + "/occurrences").json()["items"][0]
    with factory.begin() as session:
        run = session.get_one(WorkflowRun, item["workflow_run_id"])
        run.input_json = {"new_source": "altered while queued"}
    assert not process_workflow_run_job(settings, factory, item["job_id"])
    result = client.get("/api/v1/workflow-runs/" + item["workflow_run_id"]).json()
    assert result["artifacts"] == []
    failed = client.get(endpoint + "/occurrences").json()["items"][0]
    assert failed["status"] == "failed"
    assert "pinned inputs changed" in failed["detail"]


def test_app_lifespan_dispatches_a_persisted_schedule_after_reopen(
    client: TestClient, test_settings: Settings
) -> None:
    from reefvision.main import create_app

    project_id, graph_id, _ = _project_fixture(client)
    schedule = client.post(
        _schedule_url(project_id),
        json=_settings(
            graph_id,
            datetime.now(UTC) - timedelta(seconds=5),
            interval_seconds=60,
        ),
    )
    assert schedule.status_code == 201, schedule.text
    history = f"{_schedule_url(project_id)}/{schedule.json()['id']}/occurrences"
    assert client.get(history).json()["items"] == []
    # The HTTP client supplies neither a clock nor a special dispatch endpoint.
    reopened = create_app(
        test_settings.model_copy(
            update={"background_worker_enabled": True, "worker_poll_seconds": 0.03}
        )
    )
    with TestClient(reopened) as fresh:
        until = monotonic() + 12
        while monotonic() < until:
            items = fresh.get(history).json()["items"]
            if items and items[0]["status"] == "succeeded":
                assert len(items) == 1
                detail = fresh.get("/api/v1/workflow-runs/" + items[0]["workflow_run_id"]).json()
                assert any(
                    row["data_type"] == "review_queue_reference" for row in detail["artifacts"]
                )
                break
            sleep(0.06)
        else:
            pytest.fail("Local scheduler and workflow worker did not finish the persisted QC slot")


def _blocked_dispatch_process(
    root: Path,
    database_url: str,
    clock: datetime,
    edge: Literal["before_commit", "after_commit"],
    control: Connection,
) -> None:
    """Stop at a real transaction boundary so the parent can hard-kill this test process."""
    from reefvision.services.workflow_v1_install import install_workflow_v1_extensions

    assert (root / ".reefvision-schedule-crash-fixture").is_file()
    install_workflow_v1_extensions()
    settings = Settings(
        env="test", data_dir=root, database_url=database_url, background_worker_enabled=False
    )
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    original = WorkflowExecutionService.stage_run
    staged: tuple[str, str] | None = None

    def await_termination() -> None:
        assert staged is not None
        control.send(staged)
        # Only the parent owns this process. It kills the child here rather than sending an ack.
        control.recv()
        raise AssertionError("The parent should hard-stop the process at the selected boundary")

    def witness_stage(executor: WorkflowExecutionService, *args: Any, **kwargs: Any) -> WorkflowRun:
        nonlocal staged
        run = original(executor, *args, **kwargs)
        assert run.job_id is not None
        staged = (run.id, run.job_id)
        if edge == "before_commit":
            await_termination()
        return run

    def witness_commit(_session: Session) -> None:
        if staged is not None:
            await_termination()

    if edge == "after_commit":
        event.listen(factory, "after_commit", witness_commit)
    with patch.object(WorkflowExecutionService, "stage_run", witness_stage):
        dispatch_due_schedules(settings, factory, now=clock)
    raise AssertionError("The dispatcher returned without an interruption checkpoint")


@pytest.mark.parametrize("edge", ["before_commit", "after_commit"])
def test_killed_dispatcher_recovers_one_run_and_one_output_set(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    edge: Literal["before_commit", "after_commit"],
) -> None:
    from reefvision.main import create_app

    endpoint, saved = _create(client)
    root = test_settings.resolved_data_dir
    (root / ".reefvision-schedule-crash-fixture").touch()
    monkeypatch.setenv("REEFVISION_ENV", "test")
    monkeypatch.setenv("REEFVISION_DATA_DIR", str(root))
    monkeypatch.setenv("REEFVISION_BACKGROUND_WORKER_ENABLED", "false")
    due = _DUE + timedelta(seconds=125)
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(
        target=_blocked_dispatch_process,
        args=(root, test_settings.resolved_database_url, due, edge, child),
    )
    process.start()
    child.close()
    try:
        assert parent.poll(30), "The isolated dispatcher did not reach the transaction boundary"
        try:
            staged_run, staged_job = parent.recv()
        except EOFError:
            pytest.fail("The isolated dispatcher exited before reporting its checkpoint")
        assert process.is_alive()
    finally:
        if process.is_alive():
            process.kill()
        process.join(15)
        parent.close()
        assert not process.is_alive()
    assert process.exitcode not in (None, 0)

    # Reopen the real profile through a separate application and its ordinary API.
    reopened = create_app(test_settings)
    with TestClient(reopened) as fresh:
        factory = reopened.state.session_factory
        history = endpoint + "/occurrences"
        before = fresh.get(history).json()["items"]
        with factory() as session:
            job_and_run_committed = edge == "after_commit"
            assert (session.get(Job, staged_job) is not None) == job_and_run_committed
            assert (session.get(WorkflowRun, staged_run) is not None) == job_and_run_committed
        if edge == "before_commit":
            assert before == []
            assert dispatch_due_schedules(test_settings, factory, now=due) == 1
        else:
            assert len(before) == 1
            assert before[0]["workflow_run_id"] == staged_run
            assert before[0]["job_id"] == staged_job
        assert dispatch_due_schedules(test_settings, factory, now=due) == 0
        items = fresh.get(history).json()["items"]
        assert len(items) == 1
        item = items[0]
        assert datetime.fromisoformat(item["scheduled_at"]) == _DUE + timedelta(seconds=120)
        assert item["missed_intervals"] == 2
        assert item["graph_sha256"] == saved["graph_sha256"]
        if edge == "before_commit":
            assert item["workflow_run_id"] != staged_run
            assert item["job_id"] != staged_job
        assert process_workflow_run_job(test_settings, factory, item["job_id"])
        assert not process_workflow_run_job(test_settings, factory, item["job_id"])
        detail = fresh.get("/api/v1/workflow-runs/" + item["workflow_run_id"]).json()
        assert detail["run"]["workflow_graph_record_id"] == saved["workflow_graph_record_id"]
        assert detail["run"]["status"] == "succeeded"
        assert sorted(artifact["data_type"] for artifact in detail["artifacts"]) == [
            "project_reference",
            "review_queue_reference",
        ]
        assert len({artifact["id"] for artifact in detail["artifacts"]}) == 2
        report = next(x for x in detail["artifacts"] if x["data_type"] == "review_queue_reference")
        assert report["payload_json"]["item_count"] == 1
        with factory() as session:
            assert list(session.scalars(select(WorkflowRun.id))) == [item["workflow_run_id"]]
            assert list(session.scalars(select(Job.id).where(Job.job_type == "workflow_run"))) == [
                item["job_id"]
            ]

        paused = fresh.patch(endpoint, json={"expected_revision": 1, "enabled": False})
        assert paused.status_code == 200, paused.text
        assert paused.json()["last_status"] == "paused"
        assert dispatch_due_schedules(test_settings, factory, now=due + timedelta(minutes=3)) == 0
        assert fresh.get(history).json()["total"] == 1

        # Expected graph admission failures remain visible, with no orphaned workflow or job.
        project = saved["project_id"]
        graph = qc_graph()
        graph["name"] = "Alternative saved revision"
        other_graph = _save_graph(fresh, project, graph)
        broken = (
            fresh.post(_schedule_url(project), json=_settings(str(other_graph["id"]), due))
            .raise_for_status()
            .json()
        )
        with factory.begin() as session:
            graph_row = session.get_one(WorkflowGraphRecord, str(other_graph["id"]))
            graph_row.graph_json = {**graph_row.graph_json, "name": "Changed without its checksum"}
        assert dispatch_due_schedules(test_settings, factory, now=due) == 1
        broken_history = f"{_schedule_url(project)}/{broken['id']}/occurrences"
        failure = fresh.get(broken_history).json()["items"][0]
        assert failure["status"] == "failed"
        assert failure["workflow_run_id"] is None and failure["job_id"] is None
        assert "checksum" in failure["detail"]

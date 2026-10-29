"""Real separate-process SQLite race for an executable saved QC workflow.

This regression uses local user-generated data and no network or pretrained model.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ReviewQueue, WorkflowArtifact, WorkflowNodeRun
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact
from reefvision.tests.test_annotations import create_project, import_one


# Each worker independently opens the real application's SQLAlchemy engine.
# The filesystem gate starts both workers only after their imports complete.
_WORKER = """
import sys
import time
from pathlib import Path
from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact, WorkflowNodeRun
from reefvision.db.session import create_database_engine, create_session_factory
from reefvision.domain.errors import ValidationError
from reefvision.services.workflow_review_queue import create_review_queue_workflow_artifact

database, project_id, run_id, node_id, source_id, ready, gate = sys.argv[1:]
settings = Settings(
    env="test",
    data_dir=Path(database).parent,
    database_url="sqlite:///" + Path(database).as_posix(),
    background_worker_enabled=False,
)
engine = create_database_engine(settings)
try:
    Path(ready).write_text("ready", encoding="utf-8")
    deadline = time.monotonic() + 25
    while not Path(gate).exists():
        if time.monotonic() > deadline:
            raise RuntimeError("Timed out waiting for workflow race gate")
        time.sleep(0.02)
    with create_session_factory(engine)() as session:
        node = session.get(WorkflowNodeRun, node_id)
        source = session.get(WorkflowArtifact, source_id)
        assert node is not None and source is not None
        params = {
            **dict(node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": node_id,
        }
        try:
            outputs = create_review_queue_workflow_artifact(
                session, settings, project_id, params, {"project": [source]}
            )
        except ValidationError as exc:
            if "retry" not in str(exc).lower():
                raise
            print("retry", flush=True)
        else:
            assert outputs[0]["data_type"] == "review_queue_reference"
            assert outputs[0]["payload"]["priority_score_unit"] == "dimensionless"
            assert outputs[0]["payload"]["review_status"] == "requires_researcher_review"
            print("ok:" + outputs[0]["payload"]["queue_id"], flush=True)
finally:
    engine.dispose()
"""


def test_two_processes_cannot_duplicate_saved_workflow_qc_queue(
    client: TestClient, tmp_path: Path
) -> None:
    project_id = create_project(client, "Multi-process saved QC race")["id"]
    imported = import_one(
        client,
        project_id,
        filename="multiprocess-swiftia.png",
        relative_path="qc/multiprocess-swiftia.png",
    )
    assert len(imported["successful"]) == 1

    graph = {
        "graph_id": "qc-multiprocess-16",
        "name": "Local QC process collision",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "qc", "node_type": "qc_review_queue"},
        ],
        "edges": [
            {
                "edge_id": "project-qc",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "qc",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["id"]
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )

    # Reproduce an interrupted initial node: the graph and project-source
    # artifact are persisted, but no QC queue/output binding remains.
    with app.state.session_factory() as session:
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_type == "qc_review_queue",
            )
        )
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run_id,
                WorkflowArtifact.data_type == "project_reference",
            )
        )
        assert node is not None and source is not None
        owner = f"workflow:{run_id}:{node.id}"
        queue = session.scalar(
            select(ReviewQueue).where(
                ReviewQueue.project_id == project_id,
                ReviewQueue.created_by == owner,
            )
        )
        assert queue is not None
        expected_id = str(
            uuid5(NAMESPACE_URL, f"reefvision:qc-queue:v1:{project_id}:{owner}")
        )
        assert queue.id == expected_id
        node_id, source_id = node.id, source.id
        node.output_artifact_ids_json = []
        session.delete(queue)
        session.commit()

    database = app.state.engine.url.database
    assert database is not None
    gate = tmp_path / "go"
    ready = [tmp_path / f"ready-{index}" for index in range(2)]
    workers: list[subprocess.Popen[str]] = []
    try:
        for marker in ready:
            workers.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        _WORKER,
                        database,
                        project_id,
                        run_id,
                        node_id,
                        source_id,
                        str(marker),
                        str(gate),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        deadline = time.monotonic() + 25
        while not all(marker.exists() for marker in ready):
            if any(worker.poll() is not None for worker in workers):
                raise AssertionError("A QC worker exited before the race gate")
            assert time.monotonic() < deadline, "QC workers did not reach the race gate"
            time.sleep(0.025)
        gate.touch()
        outcomes = [worker.communicate(timeout=45) for worker in workers]
        for worker, (stdout, stderr) in zip(workers, outcomes, strict=True):
            assert worker.returncode == 0, stderr
            assert stdout.strip() in {"retry", f"ok:{expected_id}"}, stdout
        assert any(stdout.strip() == f"ok:{expected_id}" for stdout, _ in outcomes)
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.communicate()

    with app.state.session_factory() as session:
        owned = session.scalars(
            select(ReviewQueue).where(
                ReviewQueue.project_id == project_id,
                ReviewQueue.created_by == owner,
            )
        ).all()
        assert len(owned) == 1
        assert owned[0].id == expected_id
        node = session.get(WorkflowNodeRun, node_id)
        source = session.get(WorkflowArtifact, source_id)
        assert node is not None and source is not None
        replay = create_review_queue_workflow_artifact(
            session,
            app.state.settings,
            project_id,
            {
                **dict(node.parameters_json or {}),
                "__workflow_run_id": run_id,
                "__workflow_node_run_id": node_id,
            },
            {"project": [source]},
        )
        assert replay[0]["payload"]["queue_id"] == expected_id
        assert replay[0]["payload"]["priority_score_unit"] == "dimensionless"
        assert replay[0]["payload"]["review_status"] == "requires_researcher_review"

    annotations = client.get(
        f"/api/v1/images/{imported['successful'][0]['image_id']}/annotations"
    )
    assert annotations.status_code == 200, annotations.text
    assert annotations.json()["annotations"] == []

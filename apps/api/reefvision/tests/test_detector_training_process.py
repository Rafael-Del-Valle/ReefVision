from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.db.models.job import LocalComputeLease
from reefvision.desktop import parse_args
from reefvision.jobs import worker
from reefvision.jobs.detector_training_process import _start_child
from reefvision.services.compute_resources import Claim
from reefvision.tests.test_training_workspace import (
    _patch_training_foundation,
    _seed_training_dataset,
)


def test_scheduled_detector_child_launch_failure_finalizes_run_and_releases_lease(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_training_foundation(monkeypatch)
    project, version = _seed_training_dataset(client)
    prefix = f"/api/v1/projects/{project['id']}"
    draft = client.post(
        f"{prefix}/training-drafts",
        json={
            "name": "Detector",
            "architecture": "yolo11n.yaml",
            "dataset_version_id": version["id"],
            "task": "detect",
        },
    ).json()
    run = client.post(f"{prefix}/training-runs", json={"draft_id": draft["id"]}).json()
    app = cast(FastAPI, client.app)
    claim = Claim(run["job_id"], "training", "cpu", "lease-token")
    with app.state.session_factory() as session:
        now = datetime.now(UTC)
        session.add(
            LocalComputeLease(
                job_id=claim.job_id,
                token=claim.token,
                pool=claim.pool,
                claimed_at=now,
                heartbeat_at=now,
            )
        )
        session.commit()

    def start(*args: object) -> None:
        raise OSError("test child startup failure")

    monkeypatch.setattr("reefvision.jobs.detector_training_process._start_child", start)
    asyncio.run(
        worker._run_claim(app.state.settings, app.state.session_factory, asyncio.Event(), claim)
    )
    result = client.get(f"/api/v1/training-runs/{run['id']}").json()
    assert result["status"] == "failed" and "test child startup failure" in result["error_message"]
    with app.state.session_factory() as session:
        assert session.get(Job, claim.job_id).status == "failed"
        assert session.get(LocalComputeLease, claim.job_id) is None


@pytest.mark.parametrize("frozen", [False, True])
def test_detector_child_dispatches_the_profile_and_keeps_the_parent_gpu_mask(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    frozen: bool,
) -> None:
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    settings = Settings(data_dir=tmp_path, database_url="sqlite:///alternate.db")
    with patch("reefvision.jobs.detector_training_process.subprocess.Popen") as launch:
        _start_child(settings, "job-id")
    argv = launch.call_args.args[0]
    prefix = [sys.executable] if frozen else [sys.executable, "-m", "reefvision.desktop"]
    assert argv[: len(prefix)] == prefix
    child = parse_args(argv[len(prefix) :])
    assert child.detector_training_job == "job-id" and child.worker_parent == os.getpid()
    assert child.data_dir == tmp_path and not child.run_migrations
    assert launch.call_args.kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert launch.call_args.kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "1"
    assert launch.call_args.kwargs["env"]["REEFVISION_DATABASE_URL"] == settings.database_url


def test_terminated_descendant_wait_is_bounded_when_another_parent_must_reap_it() -> None:
    from unittest.mock import Mock

    from reefvision.jobs.detector_training_process import _terminate_child

    process = Mock(pid=4321)
    descendant = Mock()
    with (
        patch("psutil.Process") as parent,
        patch("psutil.wait_procs", side_effect=[([], [descendant]), ([], [descendant])]) as wait,
    ):
        parent.return_value.children.return_value = [descendant]
        _terminate_child(process)
    descendant.terminate.assert_called_once()
    descendant.kill.assert_called_once()
    assert all(call.kwargs.get("timeout") is not None for call in wait.call_args_list)

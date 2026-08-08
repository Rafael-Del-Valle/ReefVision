from __future__ import annotations

from contextlib import AbstractContextManager
from types import SimpleNamespace
from typing import Any, cast

import pytest

import reefvision.jobs.training_dispatch as dispatch_module
from reefvision.db.models import Job, TrainingRun


class FakeSession(AbstractContextManager["FakeSession"]):
    def __init__(self, task: str) -> None:
        self.job = SimpleNamespace(
            job_type="training",
            status="queued",
            request_json={"training_run_id": "run-1"},
        )
        self.run = SimpleNamespace(task=task)

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def get(self, model_type: type[Any], object_id: str) -> Any:
        if model_type is Job:
            return self.job
        if model_type is TrainingRun:
            return self.run
        return None


class FakeFactory:
    def __init__(self, task: str) -> None:
        self.task = task

    def __call__(self) -> FakeSession:
        return FakeSession(self.task)


def test_training_dispatch_routes_semantic_segmentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        dispatch_module,
        "process_semantic_training_job",
        lambda settings, factory, job_id: calls.append("semantic") or True,
    )

    assert dispatch_module.process_task_aware_training_job(
        cast(Any, object()),
        cast(Any, FakeFactory("semantic_segment")),
        "job-semantic",
    )
    assert calls == ["semantic"]

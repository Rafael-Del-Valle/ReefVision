"""Process boundary for scheduled Ultralytics detector fits."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psutil

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import TrainingRun
from reefvision.jobs.training import process_training_job, recover_training_run
from reefvision.repositories.jobs import JobRepository

LOGGER = logging.getLogger("reefvision.detector_training")


def is_detector_fit(factory: sessionmaker[Session], job_id: str) -> bool:
    with factory() as session:
        run = session.scalar(select(TrainingRun).where(TrainingRun.job_id == job_id))
        return bool(
            run is not None
            and run.task == "detect"
            and run.provider_id == "ultralytics"
            and run.tuning_config_json.get("mode", "disabled") == "disabled"
        )


def _exit_with_parent(parent: psutil.Process) -> None:
    parent.wait()
    os._exit(1)


def run_child(settings: Settings, job_id: str, parent_pid: int) -> int:
    import psutil

    from reefvision.db.session import create_database_engine, create_session_factory
    from reefvision.ml.dependencies import configure_provider_runtime

    try:
        parent = psutil.Process(parent_pid)
        if parent_pid not in {ancestor.pid for ancestor in psutil.Process().parents()}:
            return 1
    except psutil.NoSuchProcess:
        return 1
    # An abrupt desktop exit must also stop a fit before another scheduler recovers its job.
    threading.Thread(target=_exit_with_parent, args=(parent,), daemon=True).start()
    configure_provider_runtime(settings)
    engine = create_database_engine(settings)
    try:
        factory = create_session_factory(engine)
        if not is_detector_fit(factory, job_id):
            return 1
        LOGGER.info("Starting isolated detector training for job %s", job_id)
        processed = process_training_job(settings, factory, job_id)
        LOGGER.info("Isolated detector training exited for job %s, processed=%s", job_id, processed)
        return 0 if processed else 1
    finally:
        engine.dispose()


def _start_child(settings: Settings, job_id: str) -> subprocess.Popen[bytes]:
    argv = [sys.executable]
    if not getattr(sys, "frozen", False):
        argv.extend(["-m", "reefvision.desktop"])
    argv.extend(
        [
            "--data-dir",
            str(settings.resolved_data_dir),
            "--skip-migrations",
            "--log-file",
            str(settings.resolved_data_dir / "logs" / f"detector-training-{job_id}.log"),
            "--detector-training-job",
            job_id,
            "--worker-parent",
            str(os.getpid()),
        ]
    )
    env = {**os.environ, "REEFVISION_DATABASE_URL": settings.resolved_database_url}
    if settings.allow_unsafe_pickled_models is not None:
        env["REEFVISION_ALLOW_UNSAFE_PICKLED_MODELS"] = str(
            settings.allow_unsafe_pickled_models
        ).lower()
    return subprocess.Popen(
        argv,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _finalize_interruption(
    settings: Settings, factory: sessionmaker[Session], job_id: str, reason: str, stopping: bool
) -> None:
    with factory() as session:
        job = JobRepository(session).get_for_update(job_id)
        if job is None or job.status in {"succeeded", "failed", "cancelled"}:
            return
        if stopping and job.status == "queued":
            return  # A shutdown before the child claimed the run leaves it available at restart.
        recover_training_run(session, settings, job, interruption_reason=reason)
        session.commit()


def _terminate_child(process: subprocess.Popen[bytes]) -> None:
    # A Windows virtual environment can insert a launcher between the scheduler and Python.
    import psutil

    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    for child in reversed(descendants):
        with suppress(psutil.NoSuchProcess):
            child.terminate()
    process.terminate()
    _, remaining = psutil.wait_procs(descendants, timeout=3)
    for child in remaining:
        with suppress(psutil.NoSuchProcess):
            child.kill()
    if remaining:
        psutil.wait_procs(remaining)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


async def run_scheduled_detector(
    settings: Settings, factory: sessionmaker[Session], job_id: str, stop: asyncio.Event
) -> None:
    if stop.is_set():
        return
    try:
        process = _start_child(settings, job_id)
    except Exception as exc:
        await asyncio.to_thread(
            _finalize_interruption,
            settings,
            factory,
            job_id,
            f"Could not start the detector training process: {exc}",
            False,
        )
        return
    try:
        while process.poll() is None and not stop.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=0.25)
    finally:
        if process.poll() is None:
            await asyncio.to_thread(_terminate_child, process)
        reason = (
            "The desktop shut down during detector training."
            if stop.is_set()
            else f"The detector process exited with code {process.returncode} before finalization."
        )
        await asyncio.to_thread(
            _finalize_interruption, settings, factory, job_id, reason, stop.is_set()
        )

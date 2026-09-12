"""Restart recovery must never execute training or remove its evidence."""

from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ExperimentRecord, Job, TrainingRun
from reefvision.jobs.worker import recover_interrupted_jobs
from reefvision.tests.test_annotations import create_project


def seed_interrupted_run(client: TestClient, *, epoch: int = 50) -> tuple[str, str, Path]:
    project = create_project(client)
    with client.app.state.session_factory() as session:
        job = Job(project_id=project["id"], job_type="training", status="running")
        session.add(job)
        session.flush()
        run = TrainingRun(
            project_id=project["id"],
            job_id=job.id,
            run_name="restart regression",
            dataset_manifest_sha256="a" * 64,
            split_manifest_sha256="b" * 64,
            task="detect",
            provider_id="ultralytics",
            architecture="yolo11n.yaml",
            initial_checkpoint_source="architecture",
            device="cpu",
            precision="fp32",
            status="training",
            stage="training",
            training_config_json={"epochs": 50},
            progress_epoch=epoch,
            progress_total_epochs=50,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        job.request_json = {"training_run_id": run.id}
        job.progress_current = epoch
        job.progress_total = 50
        root = client.app.state.settings.resolved_data_dir
        output = root / project["storage_root"] / "training" / run.id / "runs" / "detect"
        output.mkdir(parents=True)
        (output / "weights").mkdir()
        # The recovery check validates a PyTorch ZIP container without unpickling it.
        for name in ("best.pt", "last.pt"):
            with ZipFile(output / "weights" / name, "w") as archive:
                archive.writestr("archive/data.pkl", b"checkpoint metadata")
                archive.writestr("archive/data/0", b"tensor storage")
        (output / "results.csv").write_text(
            "epoch,train/box_loss,metrics/mAP50(B)\n"
            + "".join(f"{i},0.25,0.75\n" for i in range(1, epoch + 1)),
            encoding="utf-8",
        )
        (output / "results.png").write_bytes(b"retained plot")
        run.logs_path = (output / "training.log").relative_to(root).as_posix()
        (output / "training.log").write_text("training evidence\n", encoding="utf-8")
        session.commit()
        return run.id, job.id, output


@pytest.mark.parametrize(
    ("epoch", "previous_status", "expected_run", "expected_job"),
    [
        (49, "running", "failed", "failed"),
        (50, "running", "completed", "succeeded"),
        (49, "cancel_requested", "cancelled", "cancelled"),
        (50, "cancel_requested", "cancelled", "cancelled"),
    ],
)
def test_restart_finalizes_without_rerunning_or_losing_artifacts(
    client: TestClient,
    epoch: int,
    previous_status: str,
    expected_run: str,
    expected_job: str,
) -> None:
    run_id, job_id, output = seed_interrupted_run(client, epoch=epoch)
    files = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    mtimes = {p.relative_to(output): p.stat().st_mtime_ns for p in output.rglob("*") if p.is_file()}
    factory = client.app.state.session_factory
    with factory() as session:
        session.get(Job, job_id).status = previous_status
        session.commit()

    assert recover_interrupted_jobs(factory, client.app.state.settings) == 1
    with factory() as session:
        run, job = session.get(TrainingRun, run_id), session.get(Job, job_id)
        assert (run.status, run.stage, job.status) == (expected_run, expected_run, expected_job)
        assert run.completed_at and job.completed_at and run.started_at
        completed_at = run.completed_at
        experiments = list(session.scalars(select(ExperimentRecord)))
        assert len(experiments) == (1 if expected_run == "completed" else 0)
        if expected_run == "completed":
            assert run.metrics_json["metrics/mAP50(B)"] == 0.75
            assert run.metrics_history_json["epoch"] == list(range(1, 51))
            assert run.result_checkpoint_path.endswith("/weights/best.pt")
            assert run.artifact_manifest_json["results_csv"].endswith("/results.csv")
            assert len(run.artifact_manifest_json["native_results_rows"]) == 50
            assert experiments[0].artifact_manifest_json == run.artifact_manifest_json
            assert (job.progress_current, job.progress_total) == (50, 50)
            assert job.error_message is None and run.error_message is None
        else:
            assert "restart" in run.error_message.lower()

    assert recover_interrupted_jobs(factory, client.app.state.settings) == 0
    with factory() as session:
        assert session.get(TrainingRun, run_id).completed_at == completed_at
        assert len(list(session.scalars(select(ExperimentRecord)))) == len(experiments)
    assert {p: (output / p).read_bytes() for p in files} == files
    assert {
        p.relative_to(output): p.stat().st_mtime_ns for p in output.rglob("*") if p.is_file()
    } == mtimes


@pytest.mark.parametrize("job_status", ["running", "cancel_requested", "succeeded"])
def test_completed_run_remains_completed(client: TestClient, job_status: str) -> None:
    run_id, job_id, _ = seed_interrupted_run(client)
    factory = client.app.state.session_factory
    with factory() as session:
        run = session.get(TrainingRun, run_id)
        run.status = run.stage = "completed"
        run.completed_at = datetime(2026, 9, 10, tzinfo=UTC)
        run.metrics_json = {"final_metric": 0.9}
        session.get(Job, job_id).status = job_status
        session.commit()
    recover_interrupted_jobs(factory, client.app.state.settings)
    with factory() as session:
        run = session.get(TrainingRun, run_id)
        assert run.status == "completed"
        assert run.metrics_json == {"final_metric": 0.9}
        assert run.completed_at.year == 2026 and run.completed_at.day == 10
        assert session.get(Job, job_id).status == "succeeded"


@pytest.mark.parametrize(
    "damage",
    [
        "missing_csv",
        "truncated_csv",
        "nonfinite",
        "no_metrics",
        "duplicate_epoch",
        "missing_weights",
        "corrupt_weights",
    ],
)
def test_progress_alone_cannot_prove_completion(client: TestClient, damage: str) -> None:
    run_id, job_id, output = seed_interrupted_run(client)
    csv_path = output / "results.csv"
    if damage == "missing_csv":
        csv_path.unlink()
    elif damage == "truncated_csv":
        csv_path.write_text("epoch,metrics/mAP50(B)\n49,0.7\n50,", encoding="utf-8")
    elif damage == "nonfinite":
        csv_path.write_text(csv_path.read_text().replace("50,0.25,0.75", "50,0.25,nan"))
    elif damage == "no_metrics":
        csv_path.write_text("epoch,time\n50,999\n", encoding="utf-8")
    elif damage == "duplicate_epoch":
        csv_path.write_text(csv_path.read_text() + "50,0.25,0.9\n", encoding="utf-8")
    else:
        for checkpoint in (output / "weights").iterdir():
            if damage == "missing_weights":
                checkpoint.unlink()
            else:
                checkpoint.write_bytes(b"truncated checkpoint")
    recover_interrupted_jobs(client.app.state.session_factory, client.app.state.settings)
    with client.app.state.session_factory() as session:
        assert session.get(TrainingRun, run_id).status == "failed"
        assert session.get(Job, job_id).status == "failed"
        assert not list(session.scalars(select(ExperimentRecord)))


def test_csv_can_prove_completion_when_progress_write_was_interrupted(client: TestClient) -> None:
    run_id, _, _ = seed_interrupted_run(client)
    with client.app.state.session_factory() as session:
        session.get(TrainingRun, run_id).progress_epoch = 49
        session.commit()
    recover_interrupted_jobs(client.app.state.session_factory, client.app.state.settings)
    with client.app.state.session_factory() as session:
        run = session.get(TrainingRun, run_id)
        assert run.status == "completed" and run.progress_epoch == 50


@pytest.mark.parametrize("callback_epoch", [49, 50, 51])
def test_late_callbacks_do_not_rewrite_final_epoch_or_completed_state(
    client: TestClient,
    callback_epoch: int,
) -> None:
    from types import SimpleNamespace

    from sqlalchemy import event

    from reefvision.jobs.training import _on_fit_epoch_end, _on_train_end

    run_id, job_id, output = seed_interrupted_run(client)
    factory = client.app.state.session_factory
    trainer = SimpleNamespace(csv=output / "results.csv", epoch=callback_epoch, epochs=50)
    writes = []

    def track_writes(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE "):
            writes.append(statement)

    event.listen(client.app.state.engine, "before_cursor_execute", track_writes)
    try:
        _on_fit_epoch_end(client.app.state.settings, factory, job_id, run_id, trainer, {})
        assert writes == []
    finally:
        event.remove(client.app.state.engine, "before_cursor_execute", track_writes)
    recover_interrupted_jobs(factory, client.app.state.settings)
    _on_train_end(client.app.state.settings, factory, job_id, run_id, trainer)
    _on_fit_epoch_end(client.app.state.settings, factory, job_id, run_id, trainer, {})
    with factory() as session:
        run = session.get(TrainingRun, run_id)
        assert (run.status, run.stage, run.progress_epoch) == ("completed", "completed", 50)


def test_corrupt_best_falls_back_to_intact_last_checkpoint(client: TestClient) -> None:
    run_id, _, output = seed_interrupted_run(client)
    (output / "weights" / "best.pt").write_bytes(b"torn write")
    recover_interrupted_jobs(client.app.state.session_factory, client.app.state.settings)
    with client.app.state.session_factory() as session:
        run = session.get(TrainingRun, run_id)
        assert run.status == "completed"
        assert run.result_checkpoint_path.endswith("/weights/last.pt")


def test_decompression_failure_does_not_abort_other_recoveries(client: TestClient) -> None:
    failed_id, _, output = seed_interrupted_run(client)
    completed_id, _, _ = seed_interrupted_run(client)
    for path in (output / "weights").iterdir():
        data = bytearray(path.read_bytes())
        offset = data.index(b"PK\x01\x02")
        # Lie about ZIP_STORED content to provoke an invalid deflate stream.
        data[offset + 10 : offset + 12] = b"\x08\x00"
        path.write_bytes(data)
    assert (
        recover_interrupted_jobs(client.app.state.session_factory, client.app.state.settings) == 2
    )
    with client.app.state.session_factory() as session:
        assert session.get(TrainingRun, failed_id).status == "failed"
        assert session.get(TrainingRun, completed_id).status == "completed"

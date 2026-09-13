"""Real YOLO11 Nano lifecycle acceptance in a new, isolated data directory.

Runs real PyTorch training through the normal worker's asyncio.to_thread path.
Fault injection exits a child process at a durable epoch or final commit boundary;
no provider final_eval patches and no user data/checkpoints are touched.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import event, select

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import ExperimentRecord, Job
from reefvision.jobs.training import process_training_job
from reefvision.jobs.worker import recover_interrupted_jobs
from reefvision.main import create_app


def validate_acceptance_output_root(output: Path) -> None:
    """Fail early when Windows acceptance evidence would exceed safe path lengths."""
    if sys.platform != "win32":
        return
    probe = (
        output
        / "data"
        / "projects"
        / ("p" * 36)
        / "training"
        / ("r" * 36)
        / "dataset"
        / "images"
        / "validation"
        / (("i" * 36) + "_region-3.png")
    )
    if len(str(probe)) >= 240:
        raise RuntimeError(
            "Acceptance output root is too deep for reliable Windows filesystem "
            "operations. Use a short path such as %TEMP%\\rv101-<commit>."
        )

def settings_for(output: Path) -> Settings:
    data = output / "data"
    return Settings(
        env="acceptance",
        data_dir=data,
        database_url=f"sqlite:///{(data / 'reefvision.db').as_posix()}",
        background_worker_enabled=False,
        web_origin="http://testserver",
    )


def require(response: Any, status: int = 200) -> Any:
    if response.status_code != status:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
    return response.json()


def seed_dataset(client: TestClient) -> tuple[str, str]:
    project = require(
        client.post(
            "/api/v1/projects",
            json={
                "name": "Isolated YOLO lifecycle acceptance",
                "template": "blank",
            },
        ),
        201,
    )
    project_id = project["id"]
    label = require(
        client.post(
            f"/api/v1/projects/{project_id}/classes",
            json={
                "class_index": 0,
                "display_order": 0,
                "name": "Synthetic region",
                "display_color": "#CA962C",
            },
        ),
        201,
    )
    assignments = []
    for i, split in enumerate(("train", "train", "validation", "test")):
        image = Image.new("RGB", (64, 64), (20 + i * 15, 60, 100))
        ImageDraw.Draw(image).rectangle((12, 12, 40, 40), fill=(230, 190 - i * 5, 80))
        stream = BytesIO()
        image.save(stream, format="PNG")
        imported = require(
            client.post(
                f"/api/v1/projects/{project_id}/imports/images",
                files=[("files", (f"region-{i}.png", stream.getvalue(), "image/png"))],
                data={"relative_paths": f"synthetic/region-{i}.png"},
            )
        )
        image_id = imported["successful"][0]["image_id"]
        require(
            client.put(
                f"/api/v1/images/{image_id}/annotations",
                json={
                    "base_revision": 0,
                    "annotation_status": "reviewed",
                    "annotations": [
                        {
                            "id": str(uuid4()),
                            "label_class_id": label["id"],
                            "x_min": 12,
                            "y_min": 12,
                            "x_max": 40,
                            "y_max": 40,
                        }
                    ],
                },
            )
        )
        assignments.append({"image_id": image_id, "split": split})
    version = require(
        client.post(
            f"/api/v1/projects/{project_id}/dataset-versions",
            json={
                "name": "Synthetic lifecycle dataset",
                "eligible_annotation_statuses": ["reviewed"],
                "split_method": "manual",
                "manual_assignments": assignments,
            },
        ),
        201,
    )
    return project_id, version["id"]


def child(output: Path, job_id: str, mode: str) -> None:
    settings = settings_for(output)
    app = create_app(settings)
    factory = app.state.session_factory
    if mode == "interrupt_final":

        def interrupt_commit(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE jobs SET") and "succeeded" in parameters:
                os._exit(73)

        event.listen(app.state.engine, "before_cursor_execute", interrupt_commit)
    success = asyncio.run(asyncio.to_thread(process_training_job, settings, factory, job_id))
    app.state.engine.dispose()
    if not success:
        raise SystemExit(1)


def assert_worker_outcome(mode: str, exit_code: int, status: str, acted: bool) -> None:
    if mode == "interrupt_final":
        assert exit_code == 73 and status == "training", "Final commit fault was not exercised"
    elif mode == "interrupt":
        assert acted and exit_code != 0 and status == "training", "Interruption was not exercised"
    elif mode == "cancel":
        assert acted and exit_code == 0 and status == "cancelled", "Cancellation did not finish"
    else:
        assert exit_code == 0 and status == "completed", "Normal training did not finalize"


def run_case(
    client: TestClient,
    output: Path,
    project_id: str,
    version_id: str,
    device: str,
    precision: str,
    mode: str,
    epochs: int,
) -> dict[str, Any]:
    name = f"{device.replace(':', '-')}-{precision}-{mode}"
    draft = require(
        client.post(
            f"/api/v1/projects/{project_id}/training-drafts",
            json={
                "name": name,
                "run_name": name,
                "dataset_version_id": version_id,
                "task": "detect",
                "provider_id": "ultralytics",
                "architecture": "yolo11n.yaml",
                "initial_checkpoint_source": "scratch",
                "device": device,
                "precision": precision,
                "training_config": {
                    "epochs": epochs,
                    "batch": 2,
                    "imgsz": 64,
                    "workers": 2,
                    "patience": 0,
                    "plots": True,
                    "val": True,
                },
                "random_seed": 17,
                "tuning_config": {"mode": "disabled"},
            },
        )
    )
    run = require(
        client.post(
            f"/api/v1/projects/{project_id}/training-runs",
            json={
                "draft_id": draft["id"],
            },
        )
    )
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--output",
        str(output),
        "--child-job",
        run["job_id"],
        "--mode",
        mode,
    ]
    progress = []
    acted = False
    started = time.monotonic()
    with (output / f"{name}.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=output)
        try:
            while process.poll() is None:
                state = require(client.get(f"/api/v1/training-runs/{run['id']}"))
                current = (state["stage"], state["progress_epoch"], state["progress_total_epochs"])
                if not progress or progress[-1] != current:
                    progress.append(current)
                    print(name, current, flush=True)
                if not acted and state["progress_epoch"] >= 1 and mode in {"interrupt", "cancel"}:
                    if mode == "interrupt":
                        process.terminate()
                    else:
                        require(client.post(f"/api/v1/jobs/{run['job_id']}/cancel"))
                    acted = True
                if time.monotonic() - started > 900:
                    raise TimeoutError(f"Training acceptance timeout: {name}")
                time.sleep(0.1)
            exit_code = process.wait(timeout=30)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=30)
    root = output / "data" / "projects" / project_id / "training" / run["id"]
    before = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }
    before_recovery = require(client.get(f"/api/v1/training-runs/{run['id']}"))
    assert_worker_outcome(mode, exit_code, before_recovery["status"], acted)
    factory = client.app.state.session_factory
    recover_interrupted_jobs(factory, client.app.state.settings)
    recover_interrupted_jobs(factory, client.app.state.settings)
    final = require(client.get(f"/api/v1/training-runs/{run['id']}"))
    expected = "failed" if mode == "interrupt" else "cancelled" if mode == "cancel" else "completed"
    if final["status"] != expected:
        raise RuntimeError(
            f"{name}: expected {expected}, got {final}; log: {output / (name + '.log')}"
        )
    after = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }
    assert before == after, "Recovery modified artifacts"
    with factory() as session:
        experiment_count = len(
            list(
                session.scalars(
                    select(ExperimentRecord).where(
                        ExperimentRecord.training_run_id == run["id"],
                    )
                )
            )
        )
        job = session.get(Job, run["job_id"])
        assert job is not None
        assert job.status == ("succeeded" if expected == "completed" else expected)
        assert experiment_count == (1 if expected == "completed" else 0)
    if expected == "completed":
        assert final["progress_epoch"] == epochs
        assert len(final["metrics_history"]["epoch"]) == epochs
        assert final["result_checkpoint_path"] and final["artifact_manifest"]["artifacts"]
        assert any(item[1] == 1 for item in progress), "No live epoch progress observed"
    return {
        "name": name,
        "status": "PASS",
        "run_id": run["id"],
        "job_id": run["job_id"],
        "device": device,
        "precision": precision,
        "epochs": epochs,
        "mode": mode,
        "exit_code": exit_code,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "progress": progress,
        "final_status": final["status"],
        "experiments": experiment_count,
        "artifact_sha256": after,
        "result_checkpoint_path": final["result_checkpoint_path"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child-job")
    parser.add_argument("--mode", default="normal")
    parser.add_argument("--cpu-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    validate_acceptance_output_root(output)
    if args.child_job:
        child(output, args.child_job, args.mode)
        return
    output.mkdir(parents=True, exist_ok=False)
    (output / "data").mkdir()
    import torch
    import ultralytics

    report: dict[str, Any] = {
        "version": __version__,
        "torch": torch.__version__,
        "torch_cuda_runtime": torch.version.cuda,
        "ultralytics": ultralytics.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cases": [],
        "status": "RUNNING",
    }
    if not args.cpu_only and not torch.cuda.is_available():
        raise RuntimeError("Real CUDA acceptance requested but CUDA is unavailable")
    if torch.cuda.is_available():
        report["gpu"] = torch.cuda.get_device_name(0)
    settings = settings_for(output)
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    report_path = output / "report.json"
    try:
        with TestClient(app) as client:
            project_id, version_id = seed_dataset(client)
            report["project_id"] = project_id
            cases = [("cpu", "fp32", "normal", 2)]
            if not args.cpu_only:
                cases += [
                    ("cuda:0", "fp32", "normal", 2),
                    ("cuda:0", "amp", "normal", 2),
                    ("cuda:0", "fp32", "interrupt", 50),
                    ("cuda:0", "fp32", "cancel", 50),
                    ("cuda:0", "fp32", "interrupt_final", 50),
                ]
            for case in cases:
                report["cases"].append(run_case(client, output, project_id, version_id, *case))
                report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        # A new app/engine represents reopen against durable storage.
        app.state.engine.dispose()
        reopened = create_app(settings)
        with TestClient(reopened) as client:
            for case in report["cases"]:
                state = require(client.get(f"/api/v1/training-runs/{case['run_id']}"))
                assert state["status"] == case["final_status"]
        reopened.state.engine.dispose()
        report["status"] = "PASS"
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = str(exc)
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        app.state.engine.dispose()
        print(report_path, flush=True)


if __name__ == "__main__":
    main()

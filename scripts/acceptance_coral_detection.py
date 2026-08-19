"""Run bounded real-coral detection acceptance through ReefVision production services."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import torch
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import Job, PredictionProposal, TrainingRun
from reefvision.jobs.inference import process_inference_job
from reefvision.jobs.training import process_training_job
from reefvision.main import create_app
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path

SPLITS = {"train": "train", "valid": "validation", "test": "test"}


def require(response: Any, status: int) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(f"API {response.request.method} {response.url}: {response.text}")
    return dict(response.json())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=2)
    args = parser.parse_args()
    source = args.dataset.resolve()
    output = args.output.resolve()
    state = args.state.resolve() if args.state else output / "reefvision-data"
    output.mkdir(parents=True, exist_ok=False)
    state.mkdir(parents=True, exist_ok=False)
    settings = Settings(
        env="acceptance",
        data_dir=state,
        database_url=f"sqlite:///{(state / 'reefvision.db').as_posix()}",
        web_origin="http://testserver",
        background_worker_enabled=False,
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    started = time.perf_counter()
    source_records: list[dict[str, Any]] = []
    split_counts: dict[str, int] = {}
    annotation_counts: dict[str, int] = {}
    image_ids: dict[str, list[str]] = {value: [] for value in SPLITS.values()}

    with TestClient(app) as client:
        project = require(
            client.post(
                "/api/v1/projects", json={"name": "APAL coral ova acceptance", "template": "blank"}
            ),
            201,
        )
        label = require(
            client.post(
                f"/api/v1/projects/{project['id']}/classes",
                json={
                    "class_index": 0,
                    "display_order": 0,
                    "name": "Egg",
                    "scientific_name": "Acropora palmata",
                    "description": "Coral ova/egg detection class imported from APAL InitialModel",
                    "display_color": "#CA962C",
                },
            ),
            201,
        )
        assignments: list[dict[str, str]] = []
        for source_split, reef_split in SPLITS.items():
            image_dir = source / source_split / "images"
            label_dir = source / source_split / "labels"
            images = sorted(path for path in image_dir.iterdir() if path.is_file())
            split_counts[reef_split] = len(images)
            annotation_counts[reef_split] = 0
            for path in images:
                label_path = label_dir / f"{path.stem}.txt"
                with Image.open(path) as image:
                    width, height = image.size
                lines = [
                    line
                    for line in label_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                boxes: list[dict[str, Any]] = []
                for line in lines:
                    class_index, cx, cy, bw, bh = (float(value) for value in line.split())
                    if int(class_index) != 0:
                        raise RuntimeError(f"Unexpected class index in {label_path}: {class_index}")
                    boxes.append(
                        {
                            "id": str(uuid4()),
                            "label_class_id": label["id"],
                            "x_min": (cx - bw / 2) * width,
                            "y_min": (cy - bh / 2) * height,
                            "x_max": (cx + bw / 2) * width,
                            "y_max": (cy + bh / 2) * height,
                        }
                    )
                annotation_counts[reef_split] += len(boxes)
                imported = require(
                    client.post(
                        f"/api/v1/projects/{project['id']}/imports/images",
                        files=[
                            ("files", (path.name, path.read_bytes(), "application/octet-stream"))
                        ],
                        data={"relative_paths": f"source/{source_split}/{path.name}"},
                    ),
                    200,
                )
                image_id = imported["successful"][0]["image_id"]
                image_ids[reef_split].append(image_id)
                updated = require(
                    client.patch(
                        f"/api/v1/images/{image_id}",
                        json={
                            "group_key": f"source:{source_split}:{path.stem}",
                            "annotation_status": "reviewed",
                        },
                    ),
                    200,
                )
                require(
                    client.put(
                        f"/api/v1/images/{image_id}/annotations",
                        json={
                            "base_revision": updated["annotation_revision"],
                            "annotation_status": "reviewed",
                            "annotations": boxes,
                        },
                    ),
                    200,
                )
                assignments.append({"image_id": image_id, "split": reef_split})
                source_records.append(
                    {
                        "source_path": str(path),
                        "source_label_path": str(label_path),
                        "source_sha256": sha256(path),
                        "label_sha256": sha256(label_path),
                        "width": width,
                        "height": height,
                        "split": reef_split,
                        "annotation_count": len(boxes),
                        "reefvision_image_id": image_id,
                    }
                )
        version = require(
            client.post(
                f"/api/v1/projects/{project['id']}/dataset-versions",
                json={
                    "name": "APAL InitialModel immutable acceptance snapshot",
                    "notes": f"Read-only source lineage: {source}",
                    "creator": "ReefVision release acceptance",
                    "eligible_annotation_statuses": ["reviewed"],
                    "split_method": "manual",
                    "manual_assignments": assignments,
                },
            ),
            201,
        )
        draft = require(
            client.post(
                f"/api/v1/projects/{project['id']}/training-drafts",
                json={
                    "name": "Real APAL coral detection acceptance",
                    "run_name": "apal-coral-detect-acceptance",
                    "dataset_version_id": version["id"],
                    "task": "detect",
                    "provider_id": "ultralytics",
                    "architecture": "yolo11.yaml",
                    "initial_checkpoint_source": "scratch",
                    "device": "cuda:0",
                    "precision": "amp",
                    "random_seed": 42,
                    "tiling_config": {"mode": "none"},
                    "training_config": {
                        "epochs": args.epochs,
                        "batch": args.batch,
                        "imgsz": args.imgsz,
                        "workers": 0,
                        "optimizer": "auto",
                        "cache": False,
                        "plots": True,
                    },
                    "tuning_config": {"mode": "disabled"},
                    "evaluation_config": {"split": "validation"},
                    "resource_limits": {"max_disk_usage_gb": 10},
                },
            ),
            200,
        )
        run = require(
            client.post(
                f"/api/v1/projects/{project['id']}/training-runs", json={"draft_id": draft["id"]}
            ),
            200,
        )
        with app.state.session_factory() as session:
            training_job = session.scalar(
                select(Job).where(Job.job_type == "training", Job.project_id == project["id"])
            )
            if training_job is None:
                raise RuntimeError("Training job was not queued")
            training_job_id = training_job.id
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable; CUDA acceptance cannot pass")
        torch.cuda.reset_peak_memory_stats()
        training_started = time.perf_counter()
        training_ok = process_training_job(settings, app.state.session_factory, training_job_id)
        training_duration = time.perf_counter() - training_started
        peak_vram = torch.cuda.max_memory_allocated()
        run_state = require(client.get(f"/api/v1/training-runs/{run['id']}"), 200)
        if not training_ok or run_state["status"] != "completed":
            raise RuntimeError(f"Training failed: {run_state.get('error_message')}")
        registered = require(
            client.post(
                f"/api/v1/projects/{project['id']}/models/register-from-run",
                json={
                    "training_run_id": run["id"],
                    "display_name": "APAL coral ova YOLO11n acceptance",
                },
            ),
            200,
        )
        inference_started = time.perf_counter()
        inference_job = require(
            client.post(
                f"/api/v1/projects/{project['id']}/inference-jobs",
                json={
                    "model_id": registered["id"],
                    "image_ids": image_ids["test"],
                    "device": "cuda:0",
                    "confidence_threshold": 0.001,
                },
            ),
            200,
        )
        inference_ok = process_inference_job(
            settings, app.state.session_factory, inference_job["id"]
        )
        inference_duration = time.perf_counter() - inference_started
        with app.state.session_factory() as session:
            proposals = list(
                session.scalars(
                    select(PredictionProposal).where(
                        PredictionProposal.inference_job_id == inference_job["id"]
                    )
                )
            )
            trained = session.get(TrainingRun, run["id"])
            if trained is None:
                raise RuntimeError("Training run missing after completion")
            checkpoint = resolve_managed_project_path(
                settings, trained.result_checkpoint_path or ""
            )
            metrics = dict(trained.metrics_json)

    app.state.engine.dispose()
    restart_app = create_app(settings)
    restart_started = time.perf_counter()
    with TestClient(restart_app) as restart_client:
        restart_job = require(
            restart_client.post(
                f"/api/v1/projects/{project['id']}/inference-jobs",
                json={
                    "model_id": registered["id"],
                    "image_ids": [image_ids["test"][0]],
                    "device": "cuda:0",
                    "confidence_threshold": 0.001,
                },
            ),
            200,
        )
        restart_ok = process_inference_job(
            settings, restart_app.state.session_factory, restart_job["id"]
        )
        restart_payload = require(restart_client.get(f"/api/v1/jobs/{restart_job['id']}"), 200)
    restart_duration = time.perf_counter() - restart_started
    restart_app.state.engine.dispose()

    geometry_valid = bool(proposals) and all(
        p.x_min < p.x_max
        and p.y_min < p.y_max
        and 0 <= p.confidence <= 1
        and p.review_status == "pending"
        for p in proposals
    )
    checkpoint_hash, checkpoint_size = hash_model_file(checkpoint)
    report = {
        "acceptance": "PASS"
        if all((training_ok, inference_ok, restart_ok, geometry_valid, checkpoint_size > 0))
        else "FAIL",
        "commit_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "source": str(source),
            "biological_context": (
                "APAL (Acropora palmata) coral ova/eggs; real microscopy imagery and "
                "real YOLO boxes; not coral polyp annotations"
            ),
            "classes": ["Egg"],
            "image_counts": split_counts,
            "annotation_counts": annotation_counts,
            "reefvision_project_id": project["id"],
            "reefvision_dataset_version_id": version["id"],
            "manifest_sha256": version["manifest_sha256"],
            "source_lineage": source_records,
        },
        "training": {
            "run_id": run["id"],
            "base_model": "yolo11.yaml nano scale (scratch)",
            "epochs": args.epochs,
            "imgsz": args.imgsz,
            "batch": args.batch,
            "device": "cuda:0",
            "seed": 42,
            "precision": "amp",
            "optimizer": "auto",
            "workers": 0,
            "duration_seconds": training_duration,
            "peak_vram_bytes": peak_vram,
            "metrics": metrics,
            "checkpoint_path": str(checkpoint),
            "checkpoint_sha256": checkpoint_hash,
            "checkpoint_size_bytes": checkpoint_size,
        },
        "hardware": {
            "gpu": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "ultralytics": __import__("ultralytics").__version__,
        },
        "model": {
            "id": registered["id"],
            "sha256": registered["sha256"],
            "managed_path": registered["managed_path"],
        },
        "inference": {
            "held_out_image_count": len(image_ids["test"]),
            "prediction_count": len(proposals),
            "confidence_threshold": 0.001,
            "duration_seconds": inference_duration,
            "mean_seconds_per_image": inference_duration / len(image_ids["test"]),
            "valid_geometry_confidence_and_pending_review": geometry_valid,
        },
        "evaluation": {
            "implementation": (
                "Ultralytics validation invoked by ReefVision training job on immutable "
                "validation split"
            ),
            "metrics": metrics,
        },
        "restart": {
            "passed": restart_ok and restart_payload["status"] == "succeeded",
            "duration_seconds": restart_duration,
            "job": restart_payload,
        },
        "total_duration_seconds": time.perf_counter() - started,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["acceptance"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

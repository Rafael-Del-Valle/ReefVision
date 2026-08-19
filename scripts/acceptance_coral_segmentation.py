"""Run bounded real-coral instance-segmentation acceptance through ReefVision.

The harness intentionally requires a real YOLO polygon dataset supplied by the caller.
It copies source images into an isolated ReefVision acceptance state, freezes polygon
annotations into an immutable dataset version, trains through ReefVision's production
segmentation worker, registers the resulting model, runs held-out inference, exercises
human review of one polygon proposal, and verifies model persistence after restart.

This is a release-execution harness, not a scientific-performance benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import torch
import yaml
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import MaskAnnotation, PredictionProposal, TrainingRun
from reefvision.jobs.inference import process_inference_job
from reefvision.jobs.training_dispatch import process_task_aware_training_job
from reefvision.main import create_app
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path

IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
REEFVISION_SPLITS = {"train": "train", "val": "validation", "test": "test"}


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


def _names_from_yaml(payload: dict[str, Any]) -> dict[int, str]:
    names = payload.get("names")
    if isinstance(names, list):
        return {index: str(name) for index, name in enumerate(names)}
    if isinstance(names, dict):
        resolved: dict[int, str] = {}
        for key, value in names.items():
            try:
                index = int(key)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"Invalid class index in data.yaml: {key!r}") from exc
            resolved[index] = str(value)
        return dict(sorted(resolved.items()))
    raise RuntimeError("data.yaml must define names as a list or class-index mapping")


def _dataset_base(source: Path, payload: dict[str, Any]) -> Path:
    configured = payload.get("path")
    if configured in (None, "", "."):
        return source
    path = Path(str(configured))
    return path.resolve() if path.is_absolute() else (source / path).resolve()


def _resolve_image_dir(source: Path, payload: dict[str, Any], key: str) -> Path | None:
    raw = payload.get(key)
    if raw is None:
        return None
    if isinstance(raw, list):
        if len(raw) != 1:
            raise RuntimeError(
                f"Acceptance currently requires one image directory for split {key}; got {len(raw)}"
            )
        raw = raw[0]
    if not isinstance(raw, str):
        raise RuntimeError(f"Split {key} must resolve to an image directory path")
    path = Path(raw)
    resolved = (
        path.resolve()
        if path.is_absolute()
        else (_dataset_base(source, payload) / path).resolve()
    )
    if not resolved.is_dir():
        raise RuntimeError(f"Image directory for split {key} does not exist: {resolved}")
    return resolved


def _label_dir_for_images(image_dir: Path) -> Path:
    parts = list(image_dir.parts)
    indexes = [index for index, part in enumerate(parts) if part.casefold() == "images"]
    if indexes:
        parts[indexes[-1]] = "labels"
        return Path(*parts)
    return image_dir.parent / "labels"


def parse_yolo_segmentation_line(
    line: str, *, label_path: Path
) -> tuple[int, list[tuple[float, float]]]:
    values = line.split()
    if len(values) < 7:
        raise RuntimeError(
            f"YOLO segmentation row must contain class + at least 3 xy points: {label_path}"
        )
    try:
        class_value = float(values[0])
        coordinates = [float(value) for value in values[1:]]
    except ValueError as exc:
        raise RuntimeError(f"Non-numeric YOLO segmentation row in {label_path}") from exc
    if not math.isfinite(class_value) or int(class_value) != class_value or class_value < 0:
        raise RuntimeError(f"Invalid class index in {label_path}: {values[0]}")
    if len(coordinates) % 2:
        raise RuntimeError(f"Odd polygon coordinate count in {label_path}")
    if any(not math.isfinite(value) or value < 0 or value > 1 for value in coordinates):
        raise RuntimeError(f"Polygon coordinates must be finite normalized values in {label_path}")
    points = list(zip(coordinates[0::2], coordinates[1::2], strict=True))
    if len(set(points)) < 3:
        raise RuntimeError(f"Polygon requires at least three unique points in {label_path}")
    return int(class_value), points


def inspect_yolo_segmentation_dataset(
    source: Path,
) -> tuple[dict[str, Any], dict[int, str], dict[str, list[tuple[Path, Path]]]]:
    yaml_path = source / "data.yaml"
    if not yaml_path.is_file():
        raise RuntimeError(f"YOLO segmentation dataset is missing data.yaml: {yaml_path}")
    payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("data.yaml must contain a mapping")
    names = _names_from_yaml(payload)
    if not names:
        raise RuntimeError("data.yaml contains no classes")

    resolved: dict[str, list[tuple[Path, Path]]] = {}
    for key in ("train", "val", "test"):
        image_dir = _resolve_image_dir(source, payload, key)
        if image_dir is None:
            if key == "test":
                continue
            raise RuntimeError(f"data.yaml is missing required {key} split")
        label_dir = _label_dir_for_images(image_dir)
        if not label_dir.is_dir():
            raise RuntimeError(f"Label directory for split {key} does not exist: {label_dir}")
        pairs: list[tuple[Path, Path]] = []
        for image_path in sorted(
            path
            for path in image_dir.iterdir()
            if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES
        ):
            label_path = label_dir / f"{image_path.stem}.txt"
            if not label_path.is_file():
                raise RuntimeError(f"Missing segmentation label for {image_path}: {label_path}")
            pairs.append((image_path, label_path))
        if not pairs:
            raise RuntimeError(f"Split {key} contains no supported images: {image_dir}")
        resolved[key] = pairs
    if "test" not in resolved:
        raise RuntimeError("Real segmentation acceptance requires an explicit held-out test split")
    return payload, names, resolved


def _polygon_is_valid(proposal: PredictionProposal) -> bool:
    polygon = proposal.polygon_json
    return (
        proposal.geometry_kind == "polygon_mask"
        and isinstance(polygon, list)
        and len(polygon) >= 3
        and len({(float(point[0]), float(point[1])) for point in polygon}) >= 3
        and proposal.x_min < proposal.x_max
        and proposal.y_min < proposal.y_max
        and 0 <= proposal.confidence <= 1
        and proposal.review_status == "pending"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--biological-context", required=True)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--architecture", default="yolo11n-seg.yaml")
    parser.add_argument("--confidence", type=float, default=0.001)
    args = parser.parse_args()

    source = args.dataset.resolve()
    output = args.output.resolve()
    state = args.state.resolve() if args.state else output / "reefvision-data"
    if output.exists():
        raise RuntimeError(f"Acceptance output already exists: {output}")
    output.mkdir(parents=True)
    state.mkdir(parents=True, exist_ok=False)

    _, class_names, source_splits = inspect_yolo_segmentation_dataset(source)
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
    image_counts: dict[str, int] = {}
    polygon_counts: dict[str, int] = {}
    image_ids: dict[str, list[str]] = {value: [] for value in REEFVISION_SPLITS.values()}

    project: dict[str, Any]
    version: dict[str, Any]
    run: dict[str, Any]
    registered: dict[str, Any]
    proposals: list[PredictionProposal]
    checkpoint: Path
    metrics: dict[str, Any]
    mask_metrics: dict[str, Any]
    reviewed_mask_id: str | None = None

    with TestClient(app) as client:
        project = require(
            client.post(
                "/api/v1/projects",
                json={"name": "Real coral segmentation acceptance", "template": "blank"},
            ),
            201,
        )
        class_ids: dict[int, str] = {}
        for class_index, name in class_names.items():
            label = require(
                client.post(
                    f"/api/v1/projects/{project['id']}/classes",
                    json={
                        "class_index": class_index,
                        "display_order": class_index,
                        "name": name,
                        "description": (
                            "Imported from real YOLO polygon segmentation "
                            "acceptance dataset"
                        ),
                        "display_color": "#4C9A8A",
                    },
                ),
                201,
            )
            class_ids[class_index] = label["id"]

        assignments: list[dict[str, str]] = []
        for source_split, reef_split in REEFVISION_SPLITS.items():
            pairs = source_splits[source_split]
            image_counts[reef_split] = len(pairs)
            polygon_counts[reef_split] = 0
            for image_path, label_path in pairs:
                with Image.open(image_path) as image:
                    width, height = image.size
                masks: list[dict[str, Any]] = []
                raw_lines = [
                    line.strip()
                    for line in label_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                for line in raw_lines:
                    class_index, normalized = parse_yolo_segmentation_line(
                        line, label_path=label_path
                    )
                    if class_index not in class_ids:
                        raise RuntimeError(
                            f"Label {label_path} uses class {class_index}, absent from data.yaml"
                        )
                    masks.append(
                        {
                            "id": str(uuid4()),
                            "label_class_id": class_ids[class_index],
                            "geometry_kind": "polygon",
                            "points": [
                                {"x": x * width, "y": y * height} for x, y in normalized
                            ],
                        }
                    )
                polygon_counts[reef_split] += len(masks)

                imported = require(
                    client.post(
                        f"/api/v1/projects/{project['id']}/imports/images",
                        files=[
                            (
                                "files",
                                (
                                    image_path.name,
                                    image_path.read_bytes(),
                                    "application/octet-stream",
                                ),
                            )
                        ],
                        data={"relative_paths": f"source/{source_split}/{image_path.name}"},
                    ),
                    200,
                )
                image_id = imported["successful"][0]["image_id"]
                image_ids[reef_split].append(image_id)
                updated = require(
                    client.patch(
                        f"/api/v1/images/{image_id}",
                        json={
                            "group_key": f"source:{source_split}:{image_path.stem}",
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
                            "annotations": [],
                            "mask_annotations": masks,
                        },
                    ),
                    200,
                )
                assignments.append({"image_id": image_id, "split": reef_split})
                source_records.append(
                    {
                        "source_path": str(image_path),
                        "source_label_path": str(label_path),
                        "source_sha256": sha256(image_path),
                        "label_sha256": sha256(label_path),
                        "width": width,
                        "height": height,
                        "split": reef_split,
                        "polygon_count": len(masks),
                        "reefvision_image_id": image_id,
                    }
                )

        if polygon_counts.get("train", 0) <= 0:
            raise RuntimeError("Training split contains no real polygon masks")
        if polygon_counts.get("validation", 0) <= 0:
            raise RuntimeError("Validation split contains no real polygon masks")
        if polygon_counts.get("test", 0) <= 0:
            raise RuntimeError("Held-out test split contains no real polygon masks")

        version = require(
            client.post(
                f"/api/v1/projects/{project['id']}/dataset-versions",
                json={
                    "name": "Real coral polygon acceptance snapshot",
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
                    "name": "Real coral segmentation acceptance",
                    "run_name": "real-coral-segment-acceptance",
                    "dataset_version_id": version["id"],
                    "task": "segment",
                    "provider_id": "ultralytics",
                    "architecture": args.architecture,
                    "initial_checkpoint_source": "scratch",
                    "device": args.device,
                    "precision": "amp" if args.device.startswith("cuda") else "fp32",
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
                f"/api/v1/projects/{project['id']}/training-runs",
                json={"draft_id": draft["id"]},
            ),
            200,
        )

        with app.state.session_factory() as session:
            training_run = session.get(TrainingRun, run["id"])
            if training_run is None or training_run.job_id is None:
                raise RuntimeError("Segmentation training job was not queued")
            training_job_id = training_run.job_id

        if args.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable; requested CUDA acceptance cannot pass")
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        training_started = time.perf_counter()
        training_ok = process_task_aware_training_job(
            settings, app.state.session_factory, training_job_id
        )
        training_duration = time.perf_counter() - training_started
        peak_vram = torch.cuda.max_memory_allocated() if torch.cuda.is_available() else 0
        run_state = require(client.get(f"/api/v1/training-runs/{run['id']}"), 200)
        if not training_ok or run_state["status"] != "completed":
            raise RuntimeError(f"Segmentation training failed: {run_state.get('error_message')}")

        registered = require(
            client.post(
                f"/api/v1/projects/{project['id']}/models/register-from-run",
                json={
                    "training_run_id": run["id"],
                    "display_name": "Real coral YOLO segmentation acceptance",
                },
            ),
            200,
        )
        if registered.get("purpose") != "segmenter":
            raise RuntimeError(
                f"Segmentation run registered unexpected model purpose: {registered.get('purpose')}"
            )

        inference_started = time.perf_counter()
        inference_job = require(
            client.post(
                f"/api/v1/projects/{project['id']}/inference-jobs",
                json={
                    "model_id": registered["id"],
                    "image_ids": image_ids["test"],
                    "device": args.device,
                    "confidence_threshold": args.confidence,
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
                raise RuntimeError("Segmentation run missing after completion")
            checkpoint = resolve_managed_project_path(
                settings, trained.result_checkpoint_path or ""
            )
            metrics = dict(trained.metrics_json)
            mask_metrics = dict(trained.artifact_manifest_json).get("mask_metrics", {})

        valid_polygons = bool(proposals) and all(_polygon_is_valid(item) for item in proposals)
        if not valid_polygons:
            raise RuntimeError(
                "Held-out segmentation inference produced no valid pending polygon-mask proposals"
            )

        review = require(
            client.post(
                f"/api/v1/prediction-proposals/{proposals[0].id}/accept",
                json={},
            ),
            200,
        )
        accepted_mask = review.get("mask_annotation")
        if not isinstance(accepted_mask, dict) or not accepted_mask.get("id"):
            raise RuntimeError("Accepting a segmentation proposal did not create a mask annotation")
        reviewed_mask_id = str(accepted_mask["id"])
        with app.state.session_factory() as session:
            persisted_mask = session.get(MaskAnnotation, reviewed_mask_id)
            if persisted_mask is None or persisted_mask.source_type != "accepted_prediction":
                raise RuntimeError(
                    "Accepted segmentation proposal was not persisted as verified mask"
                )

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
                    "device": args.device,
                    "confidence_threshold": args.confidence,
                },
            ),
            200,
        )
        restart_ok = process_inference_job(
            settings, restart_app.state.session_factory, restart_job["id"]
        )
        restart_payload = require(
            restart_client.get(f"/api/v1/jobs/{restart_job['id']}"), 200
        )
        with restart_app.state.session_factory() as session:
            restart_proposals = list(
                session.scalars(
                    select(PredictionProposal).where(
                        PredictionProposal.inference_job_id == restart_job["id"]
                    )
                )
            )
            persisted_mask_after_restart = (
                session.get(MaskAnnotation, reviewed_mask_id)
                if reviewed_mask_id is not None
                else None
            )
    restart_duration = time.perf_counter() - restart_started
    restart_app.state.engine.dispose()

    restart_geometry_valid = bool(restart_proposals) and all(
        _polygon_is_valid(item) for item in restart_proposals
    )
    review_persisted = (
        persisted_mask_after_restart is not None
        and persisted_mask_after_restart.source_type == "accepted_prediction"
    )
    checkpoint_hash, checkpoint_size = hash_model_file(checkpoint)

    acceptance = (
        "PASS"
        if all(
            (
                training_ok,
                inference_ok,
                restart_ok,
                checkpoint_size > 0,
                valid_polygons,
                restart_geometry_valid,
                review_persisted,
            )
        )
        else "FAIL"
    )
    report = {
        "acceptance": acceptance,
        "commit_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "scope": (
            "Real biological instance-segmentation software execution acceptance; "
            "not a claim of satisfactory scientific segmentation accuracy"
        ),
        "dataset": {
            "source": str(source),
            "biological_context": args.biological_context,
            "classes": [class_names[index] for index in sorted(class_names)],
            "image_counts": image_counts,
            "polygon_counts": polygon_counts,
            "reefvision_project_id": project["id"],
            "reefvision_dataset_version_id": version["id"],
            "manifest_sha256": version["manifest_sha256"],
            "source_lineage": source_records,
        },
        "training": {
            "run_id": run["id"],
            "architecture": args.architecture,
            "epochs": args.epochs,
            "imgsz": args.imgsz,
            "batch": args.batch,
            "device": args.device,
            "seed": 42,
            "precision": "amp" if args.device.startswith("cuda") else "fp32",
            "optimizer": "auto",
            "workers": 0,
            "duration_seconds": training_duration,
            "peak_vram_bytes": peak_vram,
            "metrics": metrics,
            "mask_metrics": mask_metrics,
            "checkpoint_path": str(checkpoint),
            "checkpoint_sha256": checkpoint_hash,
            "checkpoint_size_bytes": checkpoint_size,
        },
        "hardware": {
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "ultralytics": __import__("ultralytics").__version__,
        },
        "model": {
            "id": registered["id"],
            "purpose": registered.get("purpose"),
            "sha256": registered["sha256"],
            "managed_path": registered["managed_path"],
        },
        "inference": {
            "held_out_image_count": len(image_ids["test"]),
            "prediction_count": len(proposals),
            "polygon_mask_count": sum(
                item.geometry_kind == "polygon_mask" for item in proposals
            ),
            "confidence_threshold": args.confidence,
            "duration_seconds": inference_duration,
            "mean_seconds_per_image": inference_duration / len(image_ids["test"]),
            "all_pending_polygon_geometry_valid": valid_polygons,
        },
        "review": {
            "accepted_proposal_id": proposals[0].id,
            "accepted_mask_annotation_id": reviewed_mask_id,
            "persisted_as_verified_mask": review_persisted,
        },
        "evaluation": {
            "implementation": (
                "Ultralytics validation metrics persisted by ReefVision segmentation "
                "training on the immutable validation split"
            ),
            "metrics": metrics,
            "mask_metrics": mask_metrics,
        },
        "restart": {
            "passed": (
                restart_ok
                and restart_payload["status"] == "succeeded"
                and restart_geometry_valid
                and review_persisted
            ),
            "duration_seconds": restart_duration,
            "prediction_count": len(restart_proposals),
            "polygon_geometry_valid": restart_geometry_valid,
            "accepted_review_mask_persisted": review_persisted,
            "job": restart_payload,
        },
        "total_duration_seconds": time.perf_counter() - started,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if acceptance == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

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
import random
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import torch
import yaml
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import MaskAnnotation, PredictionProposal, TrainingRun
from reefvision.jobs.inference import process_inference_job
from reefvision.jobs.training_dispatch import process_task_aware_training_job
from reefvision.main import create_app
from reefvision.services.annotations import _polygon_self_intersects
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path

IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
REEFVISION_SPLITS = {"train": "train", "val": "validation", "test": "test"}
SYNTHETIC_CLASSES = ("branching coral", "massive coral")


def acceptance_dataset_label(dataset_kind: str) -> str:
    if dataset_kind == "synthetic":
        return "Synthetic technical"
    if dataset_kind == "representative":
        return "Representative coral"
    raise ValueError(f"Unsupported segmentation acceptance dataset kind: {dataset_kind}")


def require(response: Any, status: int) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(f"API {response.request.method} {response.url}: {response.text}")
    return dict(response.json())


def require_imported_image_id(report: dict[str, Any], source: Path) -> str:
    """Return the single imported image ID or preserve the API's diagnostic report."""

    successful = report.get("successful")
    if isinstance(successful, list) and len(successful) == 1:
        image_id = successful[0].get("image_id")
        if isinstance(image_id, str) and image_id:
            return image_id
    raise RuntimeError(f"Image import failed for {source}: {json.dumps(report, sort_keys=True)}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_synthetic_dataset(
    destination: Path,
    *,
    seed: int = 103,
    image_size: int = 160,
    split_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Create a deterministic varied technical dataset with leak-free splits."""

    if image_size < 96:
        raise ValueError("Synthetic segmentation images must be at least 96 pixels square")
    counts = split_counts or {"train": 20, "validation": 5, "test": 5}
    if set(counts) != {"train", "validation", "test"}:
        raise ValueError("Synthetic split counts must define train, validation, and test")
    if any(count <= 0 for count in counts.values()):
        raise ValueError("Every synthetic split must contain at least one image")
    if destination.exists():
        raise FileExistsError(f"Synthetic dataset destination already exists: {destination}")

    rng = random.Random(seed)
    destination.mkdir(parents=True)
    records: list[dict[str, Any]] = []
    sample_index = 0
    for split, count in counts.items():
        image_dir = destination / split / "images"
        label_dir = destination / split / "labels"
        image_dir.mkdir(parents=True)
        label_dir.mkdir(parents=True)
        for split_index in range(count):
            base = (12 + sample_index % 7, 18 + sample_index % 9, 24 + sample_index % 11)
            image = Image.new("RGB", (image_size, image_size), base)
            draw = ImageDraw.Draw(image)
            for y in range(image_size):
                drift = (y + sample_index * 3) % 13
                draw.line(
                    (0, y, image_size - 1, y),
                    fill=(base[0] + drift, base[1] + drift, base[2] + drift),
                )

            margin = max(8, image_size // 14)
            branch_center = (
                rng.randint(image_size // 5, image_size // 2 - margin),
                rng.randint(image_size // 5, image_size * 4 // 5),
            )
            massive_center = (
                rng.randint(image_size // 2 + margin, image_size * 4 // 5),
                rng.randint(image_size // 5, image_size * 4 // 5),
            )
            branch_radius = rng.randint(image_size // 10, image_size // 7)
            massive_radius = rng.randint(image_size // 10, image_size // 6)

            bx, by = branch_center
            br = branch_radius
            branching_polygon = [
                [bx - br, by - br // 3],
                [bx - br // 3, by - br // 3],
                [bx - br // 3, by - br],
                [bx + br // 3, by - br],
                [bx + br // 3, by - br // 3],
                [bx + br, by - br // 3],
                [bx + br, by + br // 3],
                [bx + br // 3, by + br // 3],
                [bx + br // 3, by + br],
                [bx - br // 3, by + br],
                [bx - br // 3, by + br // 3],
                [bx - br, by + br // 3],
            ]
            mx, my = massive_center
            mr = massive_radius
            massive_polygon = [
                [mx - mr, my],
                [mx - mr * 3 // 4, my - mr * 3 // 4],
                [mx, my - mr],
                [mx + mr * 3 // 4, my - mr * 3 // 4],
                [mx + mr, my],
                [mx + mr * 3 // 4, my + mr * 3 // 4],
                [mx, my + mr],
                [mx - mr * 3 // 4, my + mr * 3 // 4],
            ]
            objects = [
                {
                    "class_index": 0,
                    "class_name": SYNTHETIC_CLASSES[0],
                    "polygon": branching_polygon,
                },
                {
                    "class_index": 1,
                    "class_name": SYNTHETIC_CLASSES[1],
                    "polygon": massive_polygon,
                },
            ]
            draw.polygon(
                [tuple(point) for point in branching_polygon],
                fill=(225, 118 + sample_index % 20, 45),
            )
            draw.polygon(
                [tuple(point) for point in massive_polygon],
                fill=(38, 175, 178 + sample_index % 20),
            )

            filename = f"synthetic-{sample_index:03d}.png"
            image_path = image_dir / filename
            image.save(image_path, format="PNG")
            label_lines = []
            for item in objects:
                normalized = " ".join(
                    f"{coordinate / image_size:.8f}"
                    for point in item["polygon"]
                    for coordinate in point
                )
                label_lines.append(f"{item['class_index']} {normalized}")
            label_path = label_dir / f"{Path(filename).stem}.txt"
            label_path.write_text("\n".join(label_lines) + "\n", encoding="utf-8")
            records.append(
                {
                    "sample_index": sample_index,
                    "split_index": split_index,
                    "split": split,
                    "path": str(image_path),
                    "label_path": str(label_path),
                    "sha256": sha256(image_path),
                    "objects": objects,
                }
            )
            sample_index += 1

    (destination / "data.yaml").write_text(
        yaml.safe_dump(
            {
                "path": str(destination.resolve()),
                "train": "train/images",
                "val": "validation/images",
                "test": "test/images",
                "names": list(SYNTHETIC_CLASSES),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return records


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
                f"Acceptance requires one image directory for split {key}; got {len(raw)}"
            )
        raw = raw[0]
    if not isinstance(raw, str):
        raise RuntimeError(f"Split {key} must resolve to an image directory path")
    path = Path(raw)
    resolved = (
        path.resolve() if path.is_absolute() else (_dataset_base(source, payload) / path).resolve()
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
    split_by_hash: dict[str, str] = {}
    for split, pairs in resolved.items():
        for image_path, _label_path in pairs:
            digest = sha256(image_path)
            previous_split = split_by_hash.get(digest)
            if previous_split is not None and previous_split != split:
                raise RuntimeError(
                    "Segmentation split leakage: identical image bytes appear in "
                    f"{previous_split} and {split}: {image_path}"
                )
            split_by_hash[digest] = split
    return payload, names, resolved


def _polygon_is_valid(
    proposal: PredictionProposal,
    *,
    width: int,
    height: int,
    allowed_class_ids: set[str],
) -> bool:
    polygon = proposal.polygon_json
    if not isinstance(polygon, list) or len(polygon) < 3:
        return False
    try:
        points = [(float(point[0]), float(point[1])) for point in polygon]
    except (IndexError, TypeError, ValueError):
        return False
    if any(not math.isfinite(coordinate) for point in points for coordinate in point):
        return False
    area = abs(
        sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
        / 2
    )
    return (
        proposal.geometry_kind == "polygon_mask"
        and len(set(points)) >= 3
        and area > 0
        and not _polygon_self_intersects(points)
        and all(0 <= x < width and 0 <= y < height for x, y in points)
        and 0 <= proposal.x_min < proposal.x_max <= width
        and 0 <= proposal.y_min < proposal.y_max <= height
        and 0 <= proposal.confidence <= 1
        and proposal.review_status == "pending"
        and proposal.label_class_id in allowed_class_ids
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--biological-context", required=True)
    parser.add_argument(
        "--dataset-kind",
        choices=("representative", "synthetic"),
        default="representative",
    )
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--architecture", default="yolo11n-seg.yaml")
    parser.add_argument("--confidence", type=float, default=0.001)
    args = parser.parse_args()
    dataset_label = acceptance_dataset_label(args.dataset_kind)

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
    image_dimensions: dict[str, tuple[int, int]] = {}

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
                json={"name": f"{dataset_label} segmentation acceptance", "template": "blank"},
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
                            f"Imported from {dataset_label.lower()} YOLO polygon "
                            "segmentation acceptance dataset"
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
                            "points": [{"x": x * width, "y": y * height} for x, y in normalized],
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
                image_id = require_imported_image_id(imported, image_path)
                image_ids[reef_split].append(image_id)
                image_dimensions[image_id] = (width, height)
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
                    "name": f"{dataset_label} polygon acceptance snapshot",
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
                    "name": f"{dataset_label} segmentation acceptance",
                    "run_name": f"{args.dataset_kind}-segment-acceptance",
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
                    "display_name": f"{dataset_label} YOLO segmentation acceptance",
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

        allowed_class_ids = set(class_ids.values())
        valid_polygons = bool(proposals) and all(
            item.image_id in image_dimensions
            and _polygon_is_valid(
                item,
                width=image_dimensions[item.image_id][0],
                height=image_dimensions[item.image_id][1],
                allowed_class_ids=allowed_class_ids,
            )
            for item in proposals
        )
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
        restart_payload = require(restart_client.get(f"/api/v1/jobs/{restart_job['id']}"), 200)
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
        item.image_id in image_dimensions
        and _polygon_is_valid(
            item,
            width=image_dimensions[item.image_id][0],
            height=image_dimensions[item.image_id][1],
            allowed_class_ids=allowed_class_ids,
        )
        for item in restart_proposals
    )
    review_persisted = (
        persisted_mask_after_restart is not None
        and persisted_mask_after_restart.source_type == "accepted_prediction"
    )
    checkpoint_hash, checkpoint_size = hash_model_file(checkpoint)
    source_bytes_unchanged = all(
        sha256(Path(record["source_path"])) == record["source_sha256"] for record in source_records
    )

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
                source_bytes_unchanged,
            )
        )
        else "FAIL"
    )
    report = {
        "acceptance": acceptance,
        "commit_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "scope": (
            "Synthetic technical instance-segmentation software execution acceptance; "
            "not representative scientific validation"
            if args.dataset_kind == "synthetic"
            else "Representative biological instance-segmentation software execution acceptance"
        ),
        "results": {
            "training_lifecycle": "PASS" if training_ok else "FAIL",
            "checkpoint_registration": "PASS" if checkpoint_size > 0 else "FAIL",
            "held_out_polygon_generation": "PASS" if valid_polygons else "FAIL",
            "dataset_representativeness": (
                "UNVERIFIED" if args.dataset_kind == "synthetic" else "PASS"
            ),
            "scientific_segmentation_acceptance": (
                "UNVERIFIED" if args.dataset_kind == "synthetic" else acceptance
            ),
        },
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
            "source_bytes_unchanged": source_bytes_unchanged,
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
            "polygon_mask_count": sum(item.geometry_kind == "polygon_mask" for item in proposals),
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

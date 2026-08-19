"""Run bounded real-biological whole-image classification acceptance through ReefVision.

The caller supplies a real image classification dataset with:
    train/<class>/*
    val/<class>/*
    test/<class>/*

The harness imports source images into isolated ReefVision state, creates verified
image-level ground-truth labels, freezes explicit immutable splits, materializes
ReefVision's production classification dataset, trains the production Ultralytics
classification worker, runs held-out inference, reviews one prediction in a separate
review label set, and verifies the model and reviewed label after restart.

This is software-execution acceptance, not a claim of satisfactory scientific accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import (
    ClassificationPrediction,
    ImageLabel,
    Job,
    ModelRegistration,
)
from reefvision.jobs.classification_inference import process_classification_inference_job
from reefvision.jobs.classification_training import process_classification_training_job
from reefvision.main import create_app
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path

IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
SOURCE_SPLITS = {"train": "train", "val": "validation", "test": "test"}
GROUND_TRUTH_LABEL_SET = "acceptance-ground-truth"
REVIEW_LABEL_SET = "acceptance-model-review"


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


def inspect_classification_dataset(
    source: Path,
) -> tuple[list[str], dict[str, list[tuple[str, Path]]]]:
    if not source.is_dir():
        raise RuntimeError(f"Classification dataset directory does not exist: {source}")
    resolved: dict[str, list[tuple[str, Path]]] = {}
    classes: set[str] = set()
    for source_split in SOURCE_SPLITS:
        split_root = source / source_split
        if not split_root.is_dir():
            raise RuntimeError(
                f"Real classification acceptance requires explicit {source_split}/ directory"
            )
        pairs: list[tuple[str, Path]] = []
        class_directories = sorted(path for path in split_root.iterdir() if path.is_dir())
        if not class_directories:
            raise RuntimeError(f"Split {source_split} contains no class directories")
        for class_dir in class_directories:
            class_name = class_dir.name.strip()
            if not class_name:
                raise RuntimeError(f"Blank class directory under {split_root}")
            image_paths = sorted(
                path
                for path in class_dir.rglob("*")
                if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES
            )
            if not image_paths:
                raise RuntimeError(f"Class {class_name!r} has no images in split {source_split}")
            classes.add(class_name)
            pairs.extend((class_name, path) for path in image_paths)
        if not pairs:
            raise RuntimeError(f"Split {source_split} contains no supported images")
        resolved[source_split] = pairs

    ordered_classes = sorted(classes, key=str.casefold)
    if len(ordered_classes) < 2:
        raise RuntimeError("Real classification acceptance requires at least two classes")
    for class_name in ordered_classes:
        missing = [
            split
            for split, pairs in resolved.items()
            if not any(label == class_name for label, _path in pairs)
        ]
        if missing:
            raise RuntimeError(
                f"Class {class_name!r} is absent from required split(s): {', '.join(missing)}"
            )
    return ordered_classes, resolved


def _valid_prediction(prediction: ClassificationPrediction) -> bool:
    return (
        prediction.status == "pending"
        and prediction.rank >= 1
        and 0 <= prediction.confidence <= 1
        and bool(prediction.label_class_id)
        and isinstance(prediction.scores_json, dict)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--biological-context", required=True)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--architecture", default="yolo11n-cls.yaml")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    source = args.dataset.resolve()
    output = args.output.resolve()
    state = args.state.resolve() if args.state else output / "reefvision-data"
    if output.exists():
        raise RuntimeError(f"Acceptance output already exists: {output}")
    output.mkdir(parents=True)
    state.mkdir(parents=True, exist_ok=False)

    classes, source_splits = inspect_classification_dataset(source)
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

    class_ids: dict[str, str] = {}
    image_ids: dict[str, list[str]] = {
        reef_split: [] for reef_split in SOURCE_SPLITS.values()
    }
    image_truth: dict[str, str] = {}
    source_records: list[dict[str, Any]] = []
    image_counts: dict[str, int] = {}
    class_counts: dict[str, Counter[str]] = {}
    project: dict[str, Any]
    version: dict[str, Any]
    classification_dataset: dict[str, Any]
    model: ModelRegistration
    predictions: list[ClassificationPrediction]
    training_metrics: dict[str, Any]
    checkpoint: Path
    accepted_prediction_id: str | None = None
    accepted_image_label_id: str | None = None

    with TestClient(app) as client:
        project = require(
            client.post(
                "/api/v1/projects",
                json={"name": "Real biological classification acceptance", "template": "blank"},
            ),
            201,
        )
        for class_index, class_name in enumerate(classes):
            label = require(
                client.post(
                    f"/api/v1/projects/{project['id']}/classes",
                    json={
                        "class_index": class_index,
                        "display_order": class_index,
                        "name": class_name,
                        "description": "Imported real classification acceptance class",
                        "display_color": "#4C9A8A",
                    },
                ),
                201,
            )
            class_ids[class_name] = label["id"]

        assignments: list[dict[str, str]] = []
        for source_split, reef_split in SOURCE_SPLITS.items():
            pairs = source_splits[source_split]
            image_counts[reef_split] = len(pairs)
            class_counts[reef_split] = Counter(label for label, _path in pairs)
            for class_name, image_path in pairs:
                with Image.open(image_path) as image:
                    width, height = image.size
                    image.verify()
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
                        data={
                            "relative_paths": (
                                f"source/{source_split}/{class_name}/{image_path.name}"
                            )
                        },
                    ),
                    200,
                )
                image_id = imported["successful"][0]["image_id"]
                image_ids[reef_split].append(image_id)
                image_truth[image_id] = class_name
                updated = require(
                    client.patch(
                        f"/api/v1/images/{image_id}",
                        json={
                            "group_key": f"source:{source_split}:{class_name}:{image_path.stem}",
                            "annotation_status": "reviewed",
                        },
                    ),
                    200,
                )
                require(
                    client.put(
                        f"/api/v1/images/{image_id}/classification-labels",
                        json={
                            "label_set": GROUND_TRUTH_LABEL_SET,
                            "label_class_ids": [class_ids[class_name]],
                        },
                    ),
                    200,
                )
                assignments.append({"image_id": image_id, "split": reef_split})
                source_records.append(
                    {
                        "source_path": str(image_path),
                        "source_sha256": sha256(image_path),
                        "source_class": class_name,
                        "width": width,
                        "height": height,
                        "split": reef_split,
                        "reefvision_image_id": image_id,
                        "post_import_annotation_revision": updated["annotation_revision"],
                    }
                )

        version = require(
            client.post(
                f"/api/v1/projects/{project['id']}/dataset-versions",
                json={
                    "name": "Real biological classification acceptance snapshot",
                    "notes": f"Read-only source lineage: {source}",
                    "creator": "ReefVision release acceptance",
                    "eligible_annotation_statuses": ["reviewed"],
                    "split_method": "manual",
                    "manual_assignments": assignments,
                },
            ),
            201,
        )
        classification_dataset = require(
            client.post(
                f"/api/v1/projects/{project['id']}/classification-datasets",
                json={
                    "dataset_version_id": version["id"],
                    "mode": "image",
                    "label_set": GROUND_TRUTH_LABEL_SET,
                    "minimum_crop_pixels": 16,
                },
            ),
            201,
        )
        if classification_dataset["sample_count"] != sum(image_counts.values()):
            raise RuntimeError(
                "ReefVision classification dataset sample count does not match source images"
            )

        training_job = require(
            client.post(
                f"/api/v1/projects/{project['id']}/classification-training-jobs",
                json={
                    "classification_dataset_id": classification_dataset["id"],
                    "architecture": args.architecture,
                    "run_name": "real-biological-classification-acceptance",
                    "epochs": args.epochs,
                    "image_size": args.image_size,
                    "batch": args.batch,
                    "device": args.device,
                },
            ),
            200,
        )
        if args.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable; requested CUDA acceptance cannot pass")
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        training_started = time.perf_counter()
        training_ok = process_classification_training_job(
            settings, app.state.session_factory, training_job["id"]
        )
        training_duration = time.perf_counter() - training_started
        peak_vram = torch.cuda.max_memory_allocated() if torch.cuda.is_available() else 0

        with app.state.session_factory() as session:
            persisted_job = session.get(Job, training_job["id"])
            if persisted_job is None:
                raise RuntimeError("Classification training job disappeared")
            if not training_ok or persisted_job.status != "succeeded":
                raise RuntimeError(
                    f"Classification training failed: {persisted_job.error_message}"
                )
            result_json = dict(persisted_job.result_json)
            model_id = str(result_json.get("model_id", ""))
            model = session.get(ModelRegistration, model_id)
            if model is None or model.purpose != "classifier" or model.task != "classify":
                raise RuntimeError(
                    "Classification training did not persist a registered classifier"
                )
            training_metrics = dict(result_json.get("metrics", {}))
            checkpoint = resolve_managed_project_path(settings, model.managed_path)

        inference_started = time.perf_counter()
        inference_job = require(
            client.post(
                f"/api/v1/projects/{project['id']}/classification-inference-jobs",
                json={
                    "model_id": model.id,
                    "image_ids": image_ids["test"],
                    "label_set": REVIEW_LABEL_SET,
                    "top_k": min(args.top_k, len(classes)),
                    "device": args.device,
                },
            ),
            200,
        )
        inference_ok = process_classification_inference_job(
            settings, app.state.session_factory, inference_job["id"]
        )
        inference_duration = time.perf_counter() - inference_started

        with app.state.session_factory() as session:
            predictions = list(
                session.scalars(
                    select(ClassificationPrediction)
                    .where(
                        ClassificationPrediction.model_id == model.id,
                        ClassificationPrediction.label_set == REVIEW_LABEL_SET,
                        ClassificationPrediction.image_id.in_(image_ids["test"]),
                        ClassificationPrediction.status == "pending",
                    )
                    .order_by(
                        ClassificationPrediction.image_id,
                        ClassificationPrediction.rank,
                    )
                )
            )
        if not inference_ok or not predictions or not all(
            _valid_prediction(item) for item in predictions
        ):
            raise RuntimeError("Held-out classification inference produced invalid predictions")

        top1_by_image = {
            prediction.image_id: prediction
            for prediction in predictions
            if prediction.rank == 1
        }
        if set(top1_by_image) != set(image_ids["test"]):
            raise RuntimeError("Classification inference did not produce one top-1 result per image")
        id_to_name = {value: key for key, value in class_ids.items()}
        correct = sum(
            id_to_name.get(prediction.label_class_id) == image_truth[image_id]
            for image_id, prediction in top1_by_image.items()
        )
        heldout_top1_accuracy = correct / len(image_ids["test"])

        first_prediction = predictions[0]
        reviewed = require(
            client.put(
                f"/api/v1/classification-predictions/{first_prediction.id}/review",
                json={"action": "accept"},
            ),
            200,
        )
        accepted_prediction_id = first_prediction.id
        accepted_image_label_id = reviewed.get("accepted_image_label_id")
        if not accepted_image_label_id:
            raise RuntimeError("Accepting classification prediction did not create image label")
        with app.state.session_factory() as session:
            accepted_label = session.get(ImageLabel, accepted_image_label_id)
            if (
                accepted_label is None
                or accepted_label.source_type != "accepted_prediction"
                or accepted_label.status != "verified"
                or accepted_label.label_set != REVIEW_LABEL_SET
            ):
                raise RuntimeError(
                    "Accepted classification prediction did not persist verified provenance"
                )

    app.state.engine.dispose()

    restart_app = create_app(settings)
    restart_started = time.perf_counter()
    with TestClient(restart_app) as restart_client:
        restart_job = require(
            restart_client.post(
                f"/api/v1/projects/{project['id']}/classification-inference-jobs",
                json={
                    "model_id": model.id,
                    "image_ids": [image_ids["test"][0]],
                    "label_set": REVIEW_LABEL_SET,
                    "top_k": min(args.top_k, len(classes)),
                    "device": args.device,
                },
            ),
            200,
        )
        restart_ok = process_classification_inference_job(
            settings, restart_app.state.session_factory, restart_job["id"]
        )
        with restart_app.state.session_factory() as session:
            restart_model = session.get(ModelRegistration, model.id)
            restart_predictions = list(
                session.scalars(
                    select(ClassificationPrediction)
                    .where(
                        ClassificationPrediction.model_id == model.id,
                        ClassificationPrediction.label_set == REVIEW_LABEL_SET,
                        ClassificationPrediction.image_id == image_ids["test"][0],
                        ClassificationPrediction.status == "pending",
                    )
                    .order_by(ClassificationPrediction.rank)
                )
            )
            restart_label = (
                session.get(ImageLabel, accepted_image_label_id)
                if accepted_image_label_id is not None
                else None
            )
    restart_duration = time.perf_counter() - restart_started
    restart_app.state.engine.dispose()

    restart_predictions_valid = bool(restart_predictions) and all(
        _valid_prediction(item) for item in restart_predictions
    )
    review_persisted = (
        restart_label is not None
        and restart_label.source_type == "accepted_prediction"
        and restart_label.status == "verified"
        and restart_label.label_set == REVIEW_LABEL_SET
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
                restart_model is not None,
                restart_predictions_valid,
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
            "Real biological whole-image classification software execution acceptance; "
            "not a claim of satisfactory scientific classification accuracy"
        ),
        "dataset": {
            "source": str(source),
            "biological_context": args.biological_context,
            "classes": classes,
            "image_counts": image_counts,
            "per_split_class_counts": {
                split: dict(sorted(counts.items()))
                for split, counts in class_counts.items()
            },
            "ground_truth_label_set": GROUND_TRUTH_LABEL_SET,
            "reefvision_project_id": project["id"],
            "reefvision_dataset_version_id": version["id"],
            "dataset_manifest_sha256": version["manifest_sha256"],
            "classification_dataset_id": classification_dataset["id"],
            "classification_manifest_sha256": classification_dataset["manifest_sha256"],
            "sample_count": classification_dataset["sample_count"],
            "source_lineage": source_records,
        },
        "training": {
            "job_id": training_job["id"],
            "architecture": args.architecture,
            "epochs": args.epochs,
            "image_size": args.image_size,
            "batch": args.batch,
            "device": args.device,
            "duration_seconds": training_duration,
            "peak_vram_bytes": peak_vram,
            "metrics": training_metrics,
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
            "id": model.id,
            "purpose": model.purpose,
            "task": model.task,
            "sha256": model.sha256,
            "managed_path": model.managed_path,
        },
        "inference": {
            "job_id": inference_job["id"],
            "held_out_image_count": len(image_ids["test"]),
            "prediction_count": len(predictions),
            "top_k": min(args.top_k, len(classes)),
            "duration_seconds": inference_duration,
            "mean_seconds_per_image": inference_duration / len(image_ids["test"]),
            "heldout_top1_accuracy": heldout_top1_accuracy,
            "heldout_top1_correct": correct,
            "heldout_top1_total": len(image_ids["test"]),
            "all_pending_predictions_valid": True,
        },
        "review": {
            "review_label_set": REVIEW_LABEL_SET,
            "accepted_prediction_id": accepted_prediction_id,
            "accepted_image_label_id": accepted_image_label_id,
            "persisted_as_verified_accepted_prediction": review_persisted,
        },
        "restart": {
            "passed": (
                restart_ok
                and restart_model is not None
                and restart_predictions_valid
                and review_persisted
            ),
            "duration_seconds": restart_duration,
            "prediction_count": len(restart_predictions),
            "model_reloaded": restart_model is not None,
            "review_label_persisted": review_persisted,
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

"""Compare ReefVision uncertainty acquisition with random sampling at equal budget.

This release-evidence harness targets the already proven real APAL single-class YOLO
detection dataset layout used by ``acceptance_coral_detection.py``:

    train/images, train/labels
    valid/images, valid/labels
    test/images, test/labels

It deterministically partitions the original training split into a labeled seed and a
hidden-label acquisition pool. A baseline detector is trained through the existing real
coral detection acceptance runner. The baseline then generates production ReefVision
prediction proposals on the unlabeled pool, and the production ``uncertainty`` Active
Learning round selects an annotation budget from those candidates. A deterministic
random arm receives the exact same budget from the exact same pool. Two fresh ReefVision
projects are then trained from scratch on seed + selected samples while sharing the same
validation and test splits. The report compares downstream validation metrics and keeps
all source hashes and selected-image identities.

The experiment passes when both equal-budget arms execute reproducibly. Active Learning
is not required to beat random; the observed delta is scientific evidence, not a software
pass threshold.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.models import PredictionProposal
from reefvision.jobs.inference import process_inference_job
from reefvision.main import create_app


SOURCE_SPLITS = ("train", "valid", "test")


def require(response: Any, status: int) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(f"API {response.request.method} {response.url}: {response.text}")
    return dict(response.json())


def inspect_apal_detection_dataset(source: Path) -> dict[str, list[tuple[Path, Path]]]:
    resolved: dict[str, list[tuple[Path, Path]]] = {}
    for split in SOURCE_SPLITS:
        image_dir = source / split / "images"
        label_dir = source / split / "labels"
        if not image_dir.is_dir() or not label_dir.is_dir():
            raise RuntimeError(f"Missing YOLO image/label directories for split {split}")
        pairs: list[tuple[Path, Path]] = []
        for image_path in sorted(path for path in image_dir.iterdir() if path.is_file()):
            label_path = label_dir / f"{image_path.stem}.txt"
            if not label_path.is_file():
                raise RuntimeError(f"Missing YOLO label for {image_path}")
            for line in label_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                fields = line.split()
                if len(fields) != 5 or int(float(fields[0])) != 0:
                    raise RuntimeError(
                        "This equal-budget harness currently requires the real APAL "
                        f"single-class Egg detection contract; invalid row in {label_path}"
                    )
            pairs.append((image_path, label_path))
        if not pairs:
            raise RuntimeError(f"Split {split} contains no images")
        resolved[split] = pairs
    return resolved


def partition_training_pool(
    train_pairs: list[tuple[Path, Path]], *, seed_size: int, seed: int
) -> tuple[list[tuple[Path, Path]], list[tuple[Path, Path]]]:
    if seed_size < 1 or seed_size >= len(train_pairs):
        raise RuntimeError("seed_size must leave at least one hidden pool image")
    shuffled = list(train_pairs)
    random.Random(seed).shuffle(shuffled)
    seed_pairs = sorted(shuffled[:seed_size], key=lambda item: item[0].name.casefold())
    pool_pairs = sorted(shuffled[seed_size:], key=lambda item: item[0].name.casefold())
    return seed_pairs, pool_pairs


def _copy_pairs(pairs: list[tuple[Path, Path]], image_dir: Path, label_dir: Path) -> None:
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    for image_path, label_path in pairs:
        shutil.copy2(image_path, image_dir / image_path.name)
        shutil.copy2(label_path, label_dir / label_path.name)


def build_detection_dataset(
    destination: Path,
    *,
    train_pairs: list[tuple[Path, Path]],
    valid_pairs: list[tuple[Path, Path]],
    test_pairs: list[tuple[Path, Path]],
) -> None:
    if destination.exists():
        raise RuntimeError(f"Dataset destination already exists: {destination}")
    _copy_pairs(train_pairs, destination / "train" / "images", destination / "train" / "labels")
    _copy_pairs(valid_pairs, destination / "valid" / "images", destination / "valid" / "labels")
    _copy_pairs(test_pairs, destination / "test" / "images", destination / "test" / "labels")


def run_detection_acceptance(
    *,
    dataset: Path,
    output: Path,
    epochs: int,
    imgsz: int,
    batch: int,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).with_name("acceptance_coral_detection.py")),
        "--dataset",
        str(dataset),
        "--output",
        str(output),
        "--epochs",
        str(epochs),
        "--imgsz",
        str(imgsz),
        "--batch",
        str(batch),
    ]
    completed = subprocess.run(command, check=False)
    report_path = output / "report.json"
    if completed.returncode != 0 or not report_path.is_file():
        raise RuntimeError(
            f"Detection acceptance child run failed for {dataset} with code {completed.returncode}"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("acceptance") != "PASS":
        raise RuntimeError(f"Detection acceptance child report is not PASS: {report_path}")
    return report


def _metric(metrics: dict[str, Any], token: str) -> float | None:
    normalized_token = token.casefold().replace(" ", "")
    for key, value in metrics.items():
        normalized_key = str(key).casefold().replace(" ", "")
        if normalized_token in normalized_key:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _selected_metric_summary(report: dict[str, Any]) -> dict[str, float | None]:
    metrics = dict(report.get("training", {}).get("metrics", {}))
    return {
        "precision": _metric(metrics, "precision"),
        "recall": _metric(metrics, "recall"),
        "map50_95": _metric(metrics, "map50-95"),
        "map50": _metric(metrics, "map50"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed-size", type=int, required=True)
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--partition-seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--confidence", type=float, default=0.001)
    args = parser.parse_args()

    source = args.dataset.resolve()
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError(f"Acceptance output already exists: {output}")
    output.mkdir(parents=True)
    source_splits = inspect_apal_detection_dataset(source)
    seed_pairs, pool_pairs = partition_training_pool(
        source_splits["train"], seed_size=args.seed_size, seed=args.partition_seed
    )
    if args.budget < 1 or args.budget > len(pool_pairs):
        raise RuntimeError(
            f"budget must be between 1 and hidden pool size ({len(pool_pairs)})"
        )

    baseline_dataset = output / "baseline-dataset"
    baseline_output = output / "baseline-run"
    build_detection_dataset(
        baseline_dataset,
        train_pairs=seed_pairs,
        valid_pairs=source_splits["valid"],
        test_pairs=source_splits["test"],
    )
    experiment_started = time.perf_counter()
    baseline_report = run_detection_acceptance(
        dataset=baseline_dataset,
        output=baseline_output,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
    )

    baseline_state = baseline_output / "reefvision-data"
    settings = Settings(
        env="acceptance",
        data_dir=baseline_state,
        database_url=f"sqlite:///{(baseline_state / 'reefvision.db').as_posix()}",
        web_origin="http://testserver",
        background_worker_enabled=False,
    )
    app = create_app(settings)
    project_id = str(baseline_report["dataset"]["reefvision_project_id"])
    model_id = str(baseline_report["model"]["id"])
    pool_image_to_source: dict[str, tuple[Path, Path]] = {}
    pool_source_to_image: dict[str, str] = {}
    pool_prediction_summary: dict[str, dict[str, float | int]] = {}

    with TestClient(app) as client:
        for image_path, label_path in pool_pairs:
            imported = require(
                client.post(
                    f"/api/v1/projects/{project_id}/imports/images",
                    files=[
                        (
                            "files",
                            (image_path.name, image_path.read_bytes(), "application/octet-stream"),
                        )
                    ],
                    data={"relative_paths": f"active-learning-pool/{image_path.name}"},
                ),
                200,
            )
            image_id = str(imported["successful"][0]["image_id"])
            pool_image_to_source[image_id] = (image_path, label_path)
            pool_source_to_image[str(image_path)] = image_id

        inference_job = require(
            client.post(
                f"/api/v1/projects/{project_id}/inference-jobs",
                json={
                    "model_id": model_id,
                    "image_ids": list(pool_image_to_source),
                    "device": "cuda:0",
                    "confidence_threshold": args.confidence,
                },
            ),
            200,
        )
        if not process_inference_job(settings, app.state.session_factory, inference_job["id"]):
            raise RuntimeError("Baseline inference over the Active Learning pool failed")
        with app.state.session_factory() as session:
            proposals = list(
                session.scalars(
                    select(PredictionProposal).where(
                        PredictionProposal.model_id == model_id,
                        PredictionProposal.image_id.in_(list(pool_image_to_source)),
                        PredictionProposal.review_status == "pending",
                    )
                )
            )
        by_image: dict[str, list[float]] = {image_id: [] for image_id in pool_image_to_source}
        for proposal in proposals:
            by_image[proposal.image_id].append(float(proposal.confidence))
        for image_id, confidences in by_image.items():
            pool_prediction_summary[image_id] = {
                "proposal_count": len(confidences),
                "mean_confidence": (
                    sum(confidences) / len(confidences) if confidences else 0.0
                ),
                "minimum_confidence": min(confidences) if confidences else 0.0,
            }

        active_round = require(
            client.post(
                f"/api/v1/projects/{project_id}/active-learning-rounds",
                json={
                    "name": "Equal-budget uncertainty acquisition",
                    "strategy": "uncertainty",
                    "requested_size": args.budget,
                    "model_ids": [model_id],
                    "created_by": "ReefVision release acceptance",
                },
            ),
            201,
        )
    app.state.engine.dispose()

    selection_items = list(active_round["selection_manifest_json"].get("items", []))
    active_ids = [str(item["image_id"]) for item in selection_items]
    if len(active_ids) != args.budget or any(
        image_id not in pool_image_to_source for image_id in active_ids
    ):
        raise RuntimeError(
            "Production Active Learning selection did not return the requested hidden-pool budget"
        )
    active_pairs = [pool_image_to_source[image_id] for image_id in active_ids]
    random_pairs = random.Random(args.partition_seed).sample(pool_pairs, args.budget)
    random_pairs = sorted(random_pairs, key=lambda item: item[0].name.casefold())

    active_dataset = output / "active-learning-dataset"
    random_dataset = output / "random-dataset"
    build_detection_dataset(
        active_dataset,
        train_pairs=sorted(seed_pairs + active_pairs, key=lambda item: item[0].name.casefold()),
        valid_pairs=source_splits["valid"],
        test_pairs=source_splits["test"],
    )
    build_detection_dataset(
        random_dataset,
        train_pairs=sorted(seed_pairs + random_pairs, key=lambda item: item[0].name.casefold()),
        valid_pairs=source_splits["valid"],
        test_pairs=source_splits["test"],
    )

    active_report = run_detection_acceptance(
        dataset=active_dataset,
        output=output / "active-learning-run",
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
    )
    random_report = run_detection_acceptance(
        dataset=random_dataset,
        output=output / "random-run",
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
    )
    active_metrics = _selected_metric_summary(active_report)
    random_metrics = _selected_metric_summary(random_report)
    map_delta = (
        active_metrics["map50_95"] - random_metrics["map50_95"]
        if active_metrics["map50_95"] is not None and random_metrics["map50_95"] is not None
        else None
    )
    active_paths = {str(path) for path, _label in active_pairs}
    random_paths = {str(path) for path, _label in random_pairs}
    report = {
        "acceptance": "PASS",
        "commit_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "scope": (
            "Equal-budget real biological detection Active Learning experiment. PASS means "
            "both acquisition arms executed reproducibly, not that Active Learning beat random."
        ),
        "source_dataset": str(source),
        "partition_seed": args.partition_seed,
        "seed_size": len(seed_pairs),
        "pool_size": len(pool_pairs),
        "budget_per_arm": args.budget,
        "fixed_validation_count": len(source_splits["valid"]),
        "fixed_test_count": len(source_splits["test"]),
        "baseline": {
            "report_path": str(baseline_output / "report.json"),
            "model_id": model_id,
            "metrics": _selected_metric_summary(baseline_report),
            "pool_inference_job_id": inference_job["id"],
            "pool_prediction_summary": pool_prediction_summary,
        },
        "active_learning": {
            "strategy": "uncertainty",
            "round_id": active_round["id"],
            "selection_sha256": active_round["selection_sha256"],
            "selected_image_ids": active_ids,
            "selected_source_images": sorted(active_paths),
            "selection_manifest": active_round["selection_manifest_json"],
            "report_path": str(output / "active-learning-run" / "report.json"),
            "metrics": active_metrics,
        },
        "random": {
            "method": "deterministic random sample without replacement",
            "selected_source_images": sorted(random_paths),
            "report_path": str(output / "random-run" / "report.json"),
            "metrics": random_metrics,
        },
        "comparison": {
            "selection_overlap_count": len(active_paths & random_paths),
            "map50_95_delta_active_minus_random": map_delta,
            "active_learning_better_on_map50_95": (
                map_delta > 0 if map_delta is not None else None
            ),
        },
        "duration_seconds": time.perf_counter() - experiment_started,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

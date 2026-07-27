"""Evaluate real multi-model consensus masks against manually reviewed masks.

The script compares matching binary mask files from a ground-truth directory and
one or more model-output directories. It records per-image and aggregate IoU,
Dice, precision, recall, false-positive pixels, false-negative pixels, and area
ratios. It never treats model agreement as ground truth.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

_SUPPORTED_SUFFIXES = {".png", ".tif", ".tiff", ".bmp"}


@dataclass(frozen=True, slots=True)
class Counts:
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int


def _mask_files(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        raise ValueError(f"Mask directory does not exist: {directory}")
    files: dict[str, Path] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in _SUPPORTED_SUFFIXES:
            continue
        key = path.relative_to(directory).with_suffix("").as_posix()
        if key in files:
            raise ValueError(f"Duplicate mask key {key!r} in {directory}")
        files[key] = path
    if not files:
        raise ValueError(f"No supported mask files found in {directory}")
    return files


def _read_mask(path: Path) -> NDArray[np.bool_]:
    try:
        with Image.open(path) as source:
            source.load()
            mask = np.asarray(source.convert("L"), dtype=np.uint8) > 0
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"Could not read mask {path}: {exc}") from exc
    if mask.ndim != 2:
        raise ValueError(f"Mask must be two-dimensional: {path}")
    return mask


def _counts(
    reference: NDArray[np.bool_],
    prediction: NDArray[np.bool_],
) -> Counts:
    if reference.shape != prediction.shape:
        raise ValueError(
            f"Mask dimensions differ: reference {reference.shape}, prediction {prediction.shape}"
        )
    return Counts(
        true_positive=int(np.logical_and(reference, prediction).sum()),
        false_positive=int(np.logical_and(~reference, prediction).sum()),
        false_negative=int(np.logical_and(reference, ~prediction).sum()),
        true_negative=int(np.logical_and(~reference, ~prediction).sum()),
    )


def _ratio(
    numerator: int,
    denominator: int,
    *,
    empty_value: float = 1.0,
) -> float:
    return float(numerator / denominator) if denominator else empty_value


def _metrics(counts: Counts) -> dict[str, float | int]:
    reference_area = counts.true_positive + counts.false_negative
    prediction_area = counts.true_positive + counts.false_positive
    union = counts.true_positive + counts.false_positive + counts.false_negative
    area_ratio_empty = 1.0 if prediction_area == 0 else 0.0
    return {
        "true_positive_pixels": counts.true_positive,
        "false_positive_pixels": counts.false_positive,
        "false_negative_pixels": counts.false_negative,
        "true_negative_pixels": counts.true_negative,
        "reference_area_pixels": reference_area,
        "prediction_area_pixels": prediction_area,
        "iou": _ratio(counts.true_positive, union),
        "dice": _ratio(
            2 * counts.true_positive,
            2 * counts.true_positive + counts.false_positive + counts.false_negative,
        ),
        "precision": _ratio(
            counts.true_positive,
            counts.true_positive + counts.false_positive,
        ),
        "recall": _ratio(
            counts.true_positive,
            counts.true_positive + counts.false_negative,
        ),
        "area_ratio": _ratio(
            prediction_area,
            reference_area,
            empty_value=area_ratio_empty,
        ),
    }


def _mean(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    return float(sum(finite) / len(finite)) if finite else 0.0


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = Counts(
        true_positive=sum(int(row["true_positive_pixels"]) for row in rows),
        false_positive=sum(int(row["false_positive_pixels"]) for row in rows),
        false_negative=sum(int(row["false_negative_pixels"]) for row in rows),
        true_negative=sum(int(row["true_negative_pixels"]) for row in rows),
    )
    micro = _metrics(totals)
    macro = {
        metric: _mean([float(row[metric]) for row in rows])
        for metric in ("iou", "dice", "precision", "recall", "area_ratio")
    }
    return {"image_count": len(rows), "micro": micro, "macro": macro}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--sam3", type=Path, required=True)
    parser.add_argument("--gemini-sam2", type=Path, required=True)
    parser.add_argument("--openai-sam2", type=Path, required=True)
    parser.add_argument("--consensus-majority", type=Path, required=True)
    parser.add_argument("--consensus-intersection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--minimum-majority-macro-iou",
        type=float,
        default=0.0,
    )
    parser.add_argument(
        "--minimum-majority-improvement-over-sam3",
        type=float,
        default=0.0,
    )
    args = parser.parse_args()

    if not 0 <= args.minimum_majority_macro_iou <= 1:
        parser.error("--minimum-majority-macro-iou must be between 0 and 1")
    if not -1 <= args.minimum_majority_improvement_over_sam3 <= 1:
        parser.error("--minimum-majority-improvement-over-sam3 must be between -1 and 1")

    branch_directories = {
        "sam3": args.sam3,
        "gemini_sam2": args.gemini_sam2,
        "openai_sam2": args.openai_sam2,
        "consensus_pixel_majority": args.consensus_majority,
        "consensus_intersection": args.consensus_intersection,
    }
    try:
        ground_truth = _mask_files(args.ground_truth)
        branch_files = {name: _mask_files(path) for name, path in branch_directories.items()}
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    expected_keys = set(ground_truth)
    completeness_errors: list[str] = []
    for name, files in branch_files.items():
        missing = sorted(expected_keys - set(files))
        unexpected = sorted(set(files) - expected_keys)
        if missing:
            completeness_errors.append(f"{name} missing {len(missing)} masks: {missing[:10]}")
        if unexpected:
            completeness_errors.append(
                f"{name} has {len(unexpected)} unexpected masks: {unexpected[:10]}"
            )
    if completeness_errors:
        for message in completeness_errors:
            print(message, file=sys.stderr)
        return 2

    per_image: list[dict[str, Any]] = []
    by_branch: dict[str, list[dict[str, Any]]] = {name: [] for name in branch_files}
    try:
        for key in sorted(expected_keys):
            reference = _read_mask(ground_truth[key])
            for branch, files in branch_files.items():
                prediction = _read_mask(files[key])
                metrics = _metrics(_counts(reference, prediction))
                row = {"image_key": key, "branch": branch, **metrics}
                per_image.append(row)
                by_branch[branch].append(row)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    aggregates = {branch: _aggregate(rows) for branch, rows in by_branch.items()}
    majority_iou = float(aggregates["consensus_pixel_majority"]["macro"]["iou"])
    sam3_iou = float(aggregates["sam3"]["macro"]["iou"])
    improvement = majority_iou - sam3_iou
    failures: list[str] = []
    if majority_iou < args.minimum_majority_macro_iou:
        failures.append(
            f"Pixel-majority macro IoU {majority_iou:.4f} is below "
            f"{args.minimum_majority_macro_iou:.4f}."
        )
    if improvement < args.minimum_majority_improvement_over_sam3:
        failures.append(
            f"Pixel-majority improvement over SAM 3 {improvement:.4f} is below "
            f"{args.minimum_majority_improvement_over_sam3:.4f}."
        )

    report = {
        "schema": "reefvision-real-consensus-evaluation-v1",
        "ground_truth_directory": str(args.ground_truth.resolve()),
        "branch_directories": {
            name: str(path.resolve()) for name, path in branch_directories.items()
        },
        "image_count": len(expected_keys),
        "aggregates": aggregates,
        "consensus_majority_macro_iou": majority_iou,
        "sam3_macro_iou": sam3_iou,
        "consensus_majority_improvement_over_sam3": improvement,
        "thresholds": {
            "minimum_majority_macro_iou": args.minimum_majority_macro_iou,
            "minimum_majority_improvement_over_sam3": (args.minimum_majority_improvement_over_sam3),
        },
        "failures": failures,
        "passed": not failures,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "consensus-evaluation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with (args.output / "consensus-per-image.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(per_image[0]))
        writer.writeheader()
        writer.writerows(per_image)

    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

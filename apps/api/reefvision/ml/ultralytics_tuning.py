"""Ultralytics hyperparameter tuning execution and ReefVision-owned analytics."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from reefvision.domain.errors import ValidationError

DEFAULT_TUNING_CONFIG: dict[str, Any] = {
    "mode": "disabled",
    "iterations": 10,
    "epochs_per_trial": 10,
    "optimizer": "AdamW",
    "train_best": True,
    "search_space": {},
}


def normalize_tuning_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = {**DEFAULT_TUNING_CONFIG, **dict(config or {})}
    mode = str(merged.get("mode", "disabled")).strip().casefold()
    if mode not in {"disabled", "ultralytics"}:
        raise ValidationError("Tuning mode must be disabled or ultralytics")
    merged["mode"] = mode
    if mode == "disabled":
        return merged

    iterations = int(merged.get("iterations", 10))
    epochs = int(merged.get("epochs_per_trial", 10))
    if not 1 <= iterations <= 300:
        raise ValidationError("Tuning iterations must be between 1 and 300")
    if not 1 <= epochs <= 500:
        raise ValidationError("Tuning epochs per trial must be between 1 and 500")
    optimizer = str(merged.get("optimizer", "AdamW")).strip()
    if not optimizer:
        raise ValidationError("Choose an optimizer for tuning")
    search_space = merged.get("search_space", {})
    if not isinstance(search_space, Mapping):
        raise ValidationError("Tuning search_space must be an object")
    normalized_space: dict[str, Any] = {}
    for name, specification in search_space.items():
        key = str(name).strip()
        if not key:
            raise ValidationError("Tuning search-space parameter names cannot be empty")
        if isinstance(specification, (list, tuple)):
            values = list(specification)
            if len(values) == 2 and all(isinstance(value, (int, float)) for value in values):
                low, high = float(values[0]), float(values[1])
                if not math.isfinite(low) or not math.isfinite(high) or high <= low:
                    raise ValidationError(f"Invalid tuning range for {key}")
                normalized_space[key] = (low, high)
            elif values:
                normalized_space[key] = values
            else:
                raise ValidationError(f"Tuning choices for {key} cannot be empty")
        else:
            raise ValidationError(
                f"Tuning parameter {key} must be a two-value range or a list of choices"
            )
    merged.update(
        {
            "iterations": iterations,
            "epochs_per_trial": epochs,
            "optimizer": optimizer,
            "train_best": bool(merged.get("train_best", True)),
            "search_space": normalized_space,
        }
    )
    return merged


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            resolved: dict[str, Any] = {}
            for key, value in row.items():
                if key is None:
                    continue
                numeric = _numeric(value)
                resolved[key.strip()] = numeric if numeric is not None else value
            rows.append(resolved)
    return rows


def _read_ndjson_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _fitness_key(rows: list[dict[str, Any]]) -> str | None:
    candidates = (
        "fitness",
        "metrics/fitness",
        "metric/fitness",
        "map50_95",
        "metrics/mAP50-95(B)",
        "metrics/mAP50-95(M)",
    )
    for candidate in candidates:
        if any(_numeric(row.get(candidate)) is not None for row in rows):
            return candidate
    numeric_keys: set[str] = set()
    for row in rows:
        numeric_keys.update(key for key, value in row.items() if _numeric(value) is not None)
    return next((key for key in sorted(numeric_keys) if "fitness" in key.casefold()), None)


def summarize_tuning_rows(
    rows: list[dict[str, Any]],
    *,
    search_space_keys: set[str],
) -> dict[str, Any]:
    fitness_key = _fitness_key(rows)
    ranked = list(rows)
    if fitness_key is not None:

        def fitness_sort_value(row: dict[str, Any]) -> float:
            value = _numeric(row.get(fitness_key))
            return value if value is not None else float("-inf")

        ranked.sort(
            key=fitness_sort_value,
            reverse=True,
        )
    trials: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        trials.append(
            {
                "trial": index,
                "fitness": _numeric(row.get(fitness_key)) if fitness_key else None,
                "parameters": {
                    key: row.get(key) for key in sorted(search_space_keys) if key in row
                },
                "metrics": {
                    key: value
                    for key, value in row.items()
                    if key not in search_space_keys and key != fitness_key
                },
            }
        )
    best_row = ranked[0] if ranked else {}
    best_parameters = {
        key: best_row[key]
        for key in sorted(search_space_keys)
        if key in best_row and best_row[key] not in (None, "")
    }
    return {
        "fitness_key": fitness_key,
        "trial_count": len(rows),
        "best_fitness": _numeric(best_row.get(fitness_key)) if fitness_key else None,
        "best_parameters": best_parameters,
        "top_trials": ranked[:10],
        "trials": trials,
    }


def _find_tuning_root(search_root: Path) -> Path:
    candidates: list[Path] = []
    for pattern in (
        "tune_results.csv",
        "tune_results.ndjson",
        "best_hyperparameters.yaml",
    ):
        candidates.extend(path.parent for path in search_root.rglob(pattern) if path.is_file())
    if not candidates:
        return search_root
    return max(candidates, key=lambda path: path.stat().st_mtime)


def run_ultralytics_tuning(
    *,
    checkpoint_source: str,
    base_train_args: Mapping[str, Any],
    tuning_config: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    """Run Ultralytics tuning and return a stable summary plus generated artifacts."""

    from ultralytics import YOLO  # type: ignore[attr-defined]

    config = normalize_tuning_config(tuning_config)
    if config["mode"] == "disabled":
        return {"enabled": False, "best_parameters": {}, "artifacts": {}}

    output_root.mkdir(parents=True, exist_ok=True)
    tune_args = dict(base_train_args)
    tune_args.update(
        {
            "epochs": int(config["epochs_per_trial"]),
            "iterations": int(config["iterations"]),
            "optimizer": str(config["optimizer"]),
            "plots": True,
            "save": True,
            "val": True,
            "project": str(output_root),
            "name": "tune",
            "exist_ok": True,
        }
    )
    search_space = dict(config.get("search_space", {}))
    if search_space:
        tune_args["space"] = search_space

    model = YOLO(checkpoint_source)
    try:
        result = model.tune(**tune_args)
    except TypeError:
        # Older pinned Ultralytics releases may not accept the explicit space keyword.
        tune_args.pop("space", None)
        result = model.tune(**tune_args)

    tuning_root = _find_tuning_root(output_root)
    csv_path = next(iter(tuning_root.glob("tune_results.csv")), None)
    ndjson_path = next(iter(tuning_root.glob("tune_results.ndjson")), None)
    rows = _read_csv_rows(csv_path) if csv_path is not None else []
    if not rows and ndjson_path is not None:
        rows = _read_ndjson_rows(ndjson_path)
    summary = summarize_tuning_rows(rows, search_space_keys=set(search_space))
    plots = sorted(str(path) for path in tuning_root.glob("*.png") if path.is_file())
    summary_path = tuning_root / "reefvision-tuning-summary.json"
    artifacts = {
        "root": str(tuning_root),
        "summary_json": str(summary_path),
        "results_csv": str(csv_path) if csv_path is not None else None,
        "results_ndjson": str(ndjson_path) if ndjson_path is not None else None,
        "best_hyperparameters_yaml": (
            str(tuning_root / "best_hyperparameters.yaml")
            if (tuning_root / "best_hyperparameters.yaml").is_file()
            else None
        ),
        "plots": plots,
    }
    summary.update(
        {
            "enabled": True,
            "configuration": config,
            "ultralytics_result": result if isinstance(result, dict) else str(result),
            "artifacts": artifacts,
        }
    )
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary

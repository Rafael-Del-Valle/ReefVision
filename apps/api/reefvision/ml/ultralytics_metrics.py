"""Version-tolerant Ultralytics validation metrics and artifact export.

The pinned ReefVision stack currently uses Ultralytics 8.x, while newer releases expose
additional export helpers. This module intentionally reads stable metric attributes and
writes a ReefVision-owned JSON/CSV contract so reports do not depend on a particular
Ultralytics HTML or plotting implementation.
"""

from __future__ import annotations

import contextlib
import csv
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _python_value(value: Any) -> Any:
    """Convert tensors, arrays, and scalar wrappers into ordinary Python values."""

    if value is None:
        return None
    candidate = value
    for method_name in ("detach", "cpu"):
        method = getattr(candidate, method_name, None)
        if callable(method):
            candidate = method()
    numpy_method = getattr(candidate, "numpy", None)
    if callable(numpy_method):
        candidate = numpy_method()
    tolist = getattr(candidate, "tolist", None)
    if callable(tolist):
        candidate = tolist()
    item = getattr(candidate, "item", None)
    if callable(item) and not isinstance(candidate, (list, tuple, dict, str, bytes)):
        with contextlib.suppress(TypeError, ValueError):
            candidate = item()
    return candidate


def _as_float(value: Any) -> float | None:
    value = _python_value(value)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _as_list(value: Any) -> list[Any]:
    value = _python_value(value)
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _value_at(values: list[Any], index: int) -> float | None:
    if index < 0 or index >= len(values):
        return None
    return _as_float(values[index])


def _metric_names(metrics: Any) -> dict[int, str]:
    names = _python_value(getattr(metrics, "names", {}))
    if isinstance(names, Mapping):
        resolved: dict[int, str] = {}
        for key, value in names.items():
            try:
                resolved[int(key)] = str(value)
            except (TypeError, ValueError):
                continue
        return dict(sorted(resolved.items()))
    if isinstance(names, Sequence) and not isinstance(names, (str, bytes)):
        return {index: str(value) for index, value in enumerate(names)}
    return {}


def _class_positions(scope: Any, names: dict[int, str]) -> dict[int, int]:
    raw_indices = _as_list(getattr(scope, "ap_class_index", None))
    positions: dict[int, int] = {}
    for position, value in enumerate(raw_indices):
        try:
            positions[int(_python_value(value))] = position
        except (TypeError, ValueError):
            continue
    if positions:
        return positions

    lengths = [
        len(_as_list(getattr(scope, attribute, None)))
        for attribute in ("p", "r", "f1", "ap50", "maps")
    ]
    observed_length = max(lengths, default=0)
    if observed_length == len(names):
        return {class_id: class_id for class_id in names}
    return {
        class_id: position
        for position, class_id in enumerate(sorted(names))
        if position < observed_length
    }


def _per_class_ap75(scope: Any, position: int) -> float | None:
    ap_rows = _as_list(getattr(scope, "ap", None))
    if position >= len(ap_rows):
        return None
    row = _as_list(ap_rows[position])
    # Ultralytics AP columns begin at IoU 0.50 and increment by 0.05.
    return _value_at(row, 5)


def _per_class_map(
    scope: Any,
    class_id: int,
    position: int,
    class_count: int,
) -> float | None:
    maps = _as_list(getattr(scope, "maps", None))
    if len(maps) == class_count and class_id < len(maps):
        return _value_at(maps, class_id)
    if position < len(maps):
        return _value_at(maps, position)
    ap_rows = _as_list(getattr(scope, "ap", None))
    if position < len(ap_rows):
        values = [
            value
            for value in (_as_float(item) for item in _as_list(ap_rows[position]))
            if value is not None
        ]
        return sum(values) / len(values) if values else None
    return None


def _extract_scope(
    scope: Any,
    names: dict[int, str],
    scope_name: str,
) -> dict[str, Any]:
    precision = _as_list(getattr(scope, "p", None))
    recall = _as_list(getattr(scope, "r", None))
    f1 = _as_list(getattr(scope, "f1", None))
    ap50 = _as_list(getattr(scope, "ap50", None))
    positions = _class_positions(scope, names)
    rows: list[dict[str, Any]] = []
    for class_id, class_name in names.items():
        position = positions.get(class_id)
        row = {
            "scope": scope_name,
            "class_id": class_id,
            "class_name": class_name,
            "precision": None,
            "recall": None,
            "f1": None,
            "map50": None,
            "map75": None,
            "map50_95": None,
        }
        if position is not None:
            row.update(
                {
                    "precision": _value_at(precision, position),
                    "recall": _value_at(recall, position),
                    "f1": _value_at(f1, position),
                    "map50": _value_at(ap50, position),
                    "map75": _per_class_ap75(scope, position),
                    "map50_95": _per_class_map(
                        scope,
                        class_id,
                        position,
                        len(names),
                    ),
                }
            )
        rows.append(row)

    return {
        "scope": scope_name,
        "aggregate": {
            "precision": _as_float(getattr(scope, "mp", None)),
            "recall": _as_float(getattr(scope, "mr", None)),
            "map50": _as_float(getattr(scope, "map50", None)),
            "map75": _as_float(getattr(scope, "map75", None)),
            "map50_95": _as_float(getattr(scope, "map", None)),
        },
        "per_class": rows,
    }


def _confusion_summary(metrics: Any) -> dict[str, Any] | None:
    matrix = getattr(metrics, "confusion_matrix", None)
    if matrix is None:
        return None
    summary = getattr(matrix, "summary", None)
    if not callable(summary):
        return None
    result: dict[str, Any] = {}
    try:
        result["counts"] = _python_value(summary(normalize=False, decimals=6))
    except (TypeError, ValueError):
        try:
            result["counts"] = _python_value(summary())
        except Exception:
            return None
    try:
        result["normalized"] = _python_value(summary(normalize=True, decimals=6))
    except Exception:
        result["normalized"] = None
    return result


def extract_ultralytics_validation(metrics: Any, *, task: str) -> dict[str, Any]:
    """Extract aggregate and per-class metrics from an Ultralytics validation object."""

    names = _metric_names(metrics)
    scopes: list[dict[str, Any]] = []
    box = getattr(metrics, "box", None)
    if box is not None:
        scopes.append(_extract_scope(box, names, "box"))
    if task in {"segment", "instance_segment"}:
        segment = getattr(metrics, "seg", None)
        if segment is not None:
            scopes.append(_extract_scope(segment, names, "mask"))

    raw_results = _python_value(getattr(metrics, "results_dict", {}))
    aggregate = {
        str(key): value
        for key, raw_value in (raw_results.items() if isinstance(raw_results, Mapping) else [])
        if (value := _as_float(raw_value)) is not None
    }
    speed = _python_value(getattr(metrics, "speed", {}))
    return {
        "task": task,
        "class_names": names,
        "aggregate": aggregate,
        "scopes": scopes,
        "confusion_matrix": _confusion_summary(metrics),
        "speed": speed if isinstance(speed, Mapping) else {},
    }


def write_ultralytics_validation_artifacts(
    output_directory: Path,
    payload: dict[str, Any],
) -> dict[str, str]:
    """Write a stable JSON and tabular CSV representation of validation metrics."""

    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "reefvision-validation.json"
    csv_path = output_directory / "reefvision-per-class-metrics.csv"
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    fieldnames = [
        "scope",
        "class_id",
        "class_name",
        "precision",
        "recall",
        "f1",
        "map50",
        "map75",
        "map50_95",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for scope in payload.get("scopes", []):
            for row in scope.get("per_class", []):
                writer.writerow({key: row.get(key) for key in fieldnames})
    return {"json": str(json_path), "csv": str(csv_path)}


def _validation_split(value: object) -> str:
    normalized = str(value or "val").strip().casefold()
    aliases = {
        "validation": "val",
        "valid": "val",
        "val": "val",
        "test": "test",
        "train": "train",
    }
    return aliases.get(normalized, "val")


def run_ultralytics_validation(
    *,
    checkpoint_path: Path,
    data_yaml: Path,
    task: str,
    device: str,
    evaluation_config: Mapping[str, Any],
    output_directory: Path,
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Run an explicit Ultralytics validation pass and preserve standard plots."""

    from ultralytics import YOLO  # type: ignore[attr-defined]

    output_directory.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(checkpoint_path))
    val_args: dict[str, Any] = {
        "data": str(data_yaml),
        "device": device,
        "split": _validation_split(evaluation_config.get("split", "val")),
        "conf": float(evaluation_config.get("conf", 0.001)),
        "iou": float(evaluation_config.get("iou", 0.6)),
        "max_det": int(evaluation_config.get("max_det", 300)),
        "plots": True,
        "project": str(output_directory.parent),
        "name": output_directory.name,
        "exist_ok": True,
        "verbose": False,
    }
    metrics = model.val(**val_args)
    payload = extract_ultralytics_validation(metrics, task=task)
    artifact_paths = write_ultralytics_validation_artifacts(output_directory, payload)
    plot_paths = sorted(str(path) for path in output_directory.glob("*.png") if path.is_file())
    return payload, artifact_paths, plot_paths

"""Version-tolerant normalization for Ultralytics tuning inputs and outputs."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

FITNESS_DEFINITION = (
    "Ultralytics detection fitness: 0.1 x mAP50 + 0.9 x mAP50-95, "
    "using the provider-recorded fitness value when present."
)

RECOMMENDED_SEARCH_SPACE: dict[str, tuple[float, float]] = {
    "lr0": (1e-5, 1e-1),
    "lrf": (0.01, 1.0),
    "momentum": (0.6, 0.98),
    "weight_decay": (0.0, 0.001),
    "warmup_epochs": (0.0, 5.0),
    "box": (1.0, 20.0),
    "cls": (0.2, 4.0),
    "dfl": (0.4, 6.0),
    "hsv_h": (0.0, 0.1),
    "hsv_s": (0.0, 0.9),
    "hsv_v": (0.0, 0.9),
    "degrees": (0.0, 45.0),
    "translate": (0.0, 0.9),
    "scale": (0.0, 0.9),
    "shear": (0.0, 10.0),
    "perspective": (0.0, 0.001),
    "flipud": (0.0, 1.0),
    "fliplr": (0.0, 1.0),
    "mosaic": (0.0, 1.0),
    "mixup": (0.0, 1.0),
    "copy_paste": (0.0, 1.0),
}


def effective_search_space(config: dict[str, Any]) -> dict[str, tuple[float, float]]:
    raw = config.get("search_space")
    if not isinstance(raw, dict) or not raw:
        return dict(RECOMMENDED_SEARCH_SPACE)
    result: dict[str, tuple[float, float]] = {}
    for name, bounds in raw.items():
        if name not in RECOMMENDED_SEARCH_SPACE or not isinstance(bounds, dict):
            continue
        if bounds.get("enabled", True) is False:
            continue
        low, high = bounds.get("min"), bounds.get("max")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)) and low < high:
            result[name] = (float(low), float(high))
    if not result:
        raise ValueError("The tuning search space must contain at least one valid parameter")
    return result


def normalize_tuning_csv(path: Path) -> list[dict[str, Any]]:
    """Preserve native columns while exposing stable trial fields."""
    if not path.is_file():
        return []
    trials: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for index, raw in enumerate(csv.DictReader(stream), start=1):
            native = {str(key).strip(): _number(value) for key, value in raw.items() if key}
            fitness = _pick(native, "fitness")
            metrics = {
                key: value
                for key, value in native.items()
                if isinstance(value, (int, float)) and _is_metric(key)
            }
            parameters = {
                key: value
                for key, value in native.items()
                if isinstance(value, (int, float)) and key in RECOMMENDED_SEARCH_SPACE
            }
            trials.append(
                {
                    "trial_number": index,
                    "status": "completed" if isinstance(fitness, (int, float)) else "failed",
                    "fitness": fitness,
                    "metrics": metrics,
                    "hyperparameters": parameters,
                    "duration_seconds": _pick(native, "time", "duration"),
                    "epoch_history": [],
                    "artifacts": [],
                    "native_values": native,
                }
            )
    return trials


def best_trial(trials: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [trial for trial in trials if isinstance(trial.get("fitness"), (int, float))]
    return max(
        valid,
        key=lambda trial: (float(trial["fitness"]), -int(trial["trial_number"])),
        default=None,
    )


def _number(value: object) -> object:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return text


def _pick(values: dict[str, Any], *needles: str) -> Any:
    for needle in needles:
        for key, value in values.items():
            if key.lower().strip() == needle or key.lower().strip().endswith(needle):
                return value
    return None


def _is_metric(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("map", "precision", "recall", "accuracy", "fitness"))

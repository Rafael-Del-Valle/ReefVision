from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def harness():
    path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "acceptance_active_learning_detection.py"
    )
    spec = importlib.util.spec_from_file_location(
        "acceptance_active_learning_detection", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pairs(tmp_path: Path, count: int) -> list[tuple[Path, Path]]:
    values: list[tuple[Path, Path]] = []
    for index in range(count):
        image = tmp_path / f"image-{index:02d}.jpg"
        label = tmp_path / f"image-{index:02d}.txt"
        values.append((image, label))
    return values


def test_partition_training_pool_is_deterministic_and_disjoint(harness, tmp_path: Path) -> None:
    pairs = _pairs(tmp_path, 10)

    seed_a, pool_a = harness.partition_training_pool(pairs, seed_size=4, seed=42)
    seed_b, pool_b = harness.partition_training_pool(pairs, seed_size=4, seed=42)

    assert seed_a == seed_b
    assert pool_a == pool_b
    assert len(seed_a) == 4
    assert len(pool_a) == 6
    assert {item[0] for item in seed_a}.isdisjoint({item[0] for item in pool_a})
    assert {item[0] for item in seed_a + pool_a} == {item[0] for item in pairs}


def test_partition_requires_a_nonempty_hidden_pool(harness, tmp_path: Path) -> None:
    pairs = _pairs(tmp_path, 3)

    with pytest.raises(RuntimeError, match="leave at least one hidden pool image"):
        harness.partition_training_pool(pairs, seed_size=3, seed=42)


def test_metric_summary_extracts_ultralytics_detection_metrics(harness) -> None:
    report = {
        "training": {
            "metrics": {
                "metrics/precision(B)": 0.4,
                "metrics/recall(B)": 0.5,
                "metrics/mAP50(B)": 0.6,
                "metrics/mAP50-95(B)": 0.3,
            }
        }
    }

    summary = harness._selected_metric_summary(report)

    assert summary == {
        "precision": 0.4,
        "recall": 0.5,
        "map50_95": 0.3,
        "map50": 0.6,
    }

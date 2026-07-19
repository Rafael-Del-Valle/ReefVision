from __future__ import annotations

from types import SimpleNamespace

import pytest

from reefvision.ml.ultralytics_metrics import extract_ultralytics_validation
from reefvision.ml.ultralytics_tuning import summarize_tuning_rows


class FakeConfusionMatrix:
    def summary(self, *, normalize: bool = False, decimals: int = 6):
        del decimals
        return [{"actual": "A", "predicted_A": 0.75 if normalize else 3}]


def test_ultralytics_validation_reports_each_class_for_boxes_and_masks() -> None:
    box = SimpleNamespace(
        p=[0.8, 0.6],
        r=[0.5, 0.9],
        f1=[0.6153846, 0.72],
        ap50=[0.75, 0.88],
        ap=[[0.75, 0.72, 0.69, 0.65, 0.61, 0.58], [0.88, 0.84, 0.8, 0.76, 0.72, 0.68]],
        maps=[0.66, 0.78],
        ap_class_index=[0, 1],
        mp=0.7,
        mr=0.7,
        map50=0.815,
        map75=0.63,
        map=0.72,
    )
    mask = SimpleNamespace(
        p=[0.72, 0.55],
        r=[0.48, 0.81],
        f1=[0.576, 0.655],
        ap50=[0.7, 0.79],
        ap=[[0.7, 0.66, 0.62, 0.59, 0.55, 0.5], [0.79, 0.76, 0.72, 0.69, 0.65, 0.61]],
        maps=[0.6, 0.7],
        ap_class_index=[0, 1],
        mp=0.635,
        mr=0.645,
        map50=0.745,
        map75=0.555,
        map=0.65,
    )
    metrics = SimpleNamespace(
        names={0: "Swiftia open", 1: "Swiftia closed"},
        box=box,
        seg=mask,
        results_dict={"metrics/mAP50-95(B)": 0.72, "metrics/mAP50-95(M)": 0.65},
        confusion_matrix=FakeConfusionMatrix(),
        speed={"inference": 12.5},
    )

    payload = extract_ultralytics_validation(metrics, task="segment")

    assert [scope["scope"] for scope in payload["scopes"]] == ["box", "mask"]
    box_rows = payload["scopes"][0]["per_class"]
    assert box_rows[0]["class_name"] == "Swiftia open"
    assert box_rows[0]["precision"] == pytest.approx(0.8)
    assert box_rows[0]["recall"] == pytest.approx(0.5)
    assert box_rows[0]["f1"] == pytest.approx(0.6153846)
    assert box_rows[0]["map75"] == pytest.approx(0.58)
    assert payload["confusion_matrix"]["normalized"][0]["predicted_A"] == pytest.approx(0.75)


def test_tuning_summary_ranks_fitness_and_preserves_parameters() -> None:
    rows = [
        {"fitness": 0.55, "lr0": 0.001, "momentum": 0.8, "map50": 0.72},
        {"fitness": 0.74, "lr0": 0.004, "momentum": 0.9, "map50": 0.85},
        {"fitness": 0.63, "lr0": 0.002, "momentum": 0.85, "map50": 0.78},
    ]

    summary = summarize_tuning_rows(rows, search_space_keys={"lr0", "momentum"})

    assert summary["trial_count"] == 3
    assert summary["best_fitness"] == pytest.approx(0.74)
    assert summary["best_parameters"] == {"lr0": 0.004, "momentum": 0.9}
    assert [trial["fitness"] for trial in summary["trials"]] == [0.55, 0.74, 0.63]

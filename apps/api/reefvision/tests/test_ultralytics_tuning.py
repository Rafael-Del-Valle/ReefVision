from pathlib import Path

import pytest

from reefvision.ml.ultralytics_tuning import (
    best_trial,
    effective_search_space,
    normalize_tuning_csv,
)


def test_effective_search_space_validates_and_preserves_exact_ranges() -> None:
    result = effective_search_space(
        {
            "search_space": {
                "lr0": {"min": 0.001, "max": 0.02, "enabled": True},
                "mosaic": {"min": 0, "max": 1, "enabled": False},
            }
        }
    )
    assert result == {"lr0": (0.001, 0.02)}
    with pytest.raises(ValueError):
        effective_search_space({"search_space": {"lr0": {"min": 1, "max": 0}}})


def test_tuning_csv_keeps_trial_order_native_values_and_best_identity(tmp_path: Path) -> None:
    path = tmp_path / "tune_results.csv"
    path.write_text(
        "fitness,metrics/mAP50-95(B),lr0,time\n0.10,0.11,0.01,2\n,0.12,0.02,3\n0.15,0.16,0.03,4\n",
        encoding="utf-8",
    )
    trials = normalize_tuning_csv(path)
    assert [trial["trial_number"] for trial in trials] == [1, 2, 3]
    assert trials[1]["status"] == "failed"
    assert trials[0]["native_values"]["lr0"] == 0.01
    assert best_trial(trials)["trial_number"] == 3

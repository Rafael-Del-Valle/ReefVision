from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def _write_mask(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(array, dtype=np.uint8) * 255).save(path)


def test_consensus_evaluation_records_improvement_and_thresholds(
    tmp_path: Path,
) -> None:
    directories = {
        name: tmp_path / name
        for name in (
            "ground_truth",
            "sam3",
            "gemini_sam2",
            "openai_sam2",
            "majority",
            "intersection",
        )
    }
    reference = np.zeros((24, 24), dtype=bool)
    reference[5:19, 7:17] = True
    sam3 = np.zeros_like(reference)
    sam3[7:18, 8:16] = True
    gemini = np.zeros_like(reference)
    gemini[5:19, 7:17] = True
    openai = np.zeros_like(reference)
    openai[5:19, 7:17] = True
    majority = reference.copy()
    intersection = sam3.copy()
    for key in ("image-1", "image-2"):
        _write_mask(directories["ground_truth"] / f"{key}.png", reference)
        _write_mask(directories["sam3"] / f"{key}.png", sam3)
        _write_mask(directories["gemini_sam2"] / f"{key}.png", gemini)
        _write_mask(directories["openai_sam2"] / f"{key}.png", openai)
        _write_mask(directories["majority"] / f"{key}.png", majority)
        _write_mask(directories["intersection"] / f"{key}.png", intersection)

    output = tmp_path / "evaluation"
    script = (
        Path(__file__).parents[4]
        / "scripts"
        / "evaluate-consensus-masks.py"
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--ground-truth",
            str(directories["ground_truth"]),
            "--sam3",
            str(directories["sam3"]),
            "--gemini-sam2",
            str(directories["gemini_sam2"]),
            "--openai-sam2",
            str(directories["openai_sam2"]),
            "--consensus-majority",
            str(directories["majority"]),
            "--consensus-intersection",
            str(directories["intersection"]),
            "--output",
            str(output),
            "--minimum-majority-macro-iou",
            "0.95",
            "--minimum-majority-improvement-over-sam3",
            "0.20",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    report_path = output / "consensus-evaluation.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["image_count"] == 2
    assert report["consensus_majority_macro_iou"] == 1.0
    assert report["consensus_majority_improvement_over_sam3"] > 0.20
    assert (output / "consensus-per-image.csv").is_file()


def test_consensus_evaluation_fails_incomplete_branch(tmp_path: Path) -> None:
    directories = {
        name: tmp_path / name
        for name in (
            "ground_truth",
            "sam3",
            "gemini_sam2",
            "openai_sam2",
            "majority",
            "intersection",
        )
    }
    mask = np.zeros((12, 12), dtype=bool)
    mask[2:10, 3:9] = True
    for name, directory in directories.items():
        if name != "openai_sam2":
            _write_mask(directory / "image-1.png", mask)
        else:
            directory.mkdir(parents=True, exist_ok=True)
            _write_mask(directory / "different-image.png", mask)

    script = (
        Path(__file__).parents[4]
        / "scripts"
        / "evaluate-consensus-masks.py"
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--ground-truth",
            str(directories["ground_truth"]),
            "--sam3",
            str(directories["sam3"]),
            "--gemini-sam2",
            str(directories["gemini_sam2"]),
            "--openai-sam2",
            str(directories["openai_sam2"]),
            "--consensus-majority",
            str(directories["majority"]),
            "--consensus-intersection",
            str(directories["intersection"]),
            "--output",
            str(tmp_path / "evaluation"),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 2
    assert "openai_sam2 missing" in completed.stderr

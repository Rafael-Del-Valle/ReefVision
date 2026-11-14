from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def harness():
    path = Path(__file__).resolve().parents[4] / "scripts" / "acceptance_coral_segmentation.py"
    spec = importlib.util.spec_from_file_location("acceptance_coral_segmentation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_polygon_parser_rejects_detection_box_rows(harness, tmp_path: Path) -> None:
    label = tmp_path / "label.txt"
    with pytest.raises(RuntimeError, match="at least 3 xy points"):
        harness.parse_yolo_segmentation_line("0 0.5 0.5 0.2 0.2", label_path=label)


def test_polygon_parser_accepts_normalized_segmentation_rows(harness, tmp_path: Path) -> None:
    class_index, points = harness.parse_yolo_segmentation_line(
        "2 0.1 0.2 0.8 0.2 0.7 0.9 0.2 0.8",
        label_path=tmp_path / "label.txt",
    )
    assert class_index == 2
    assert points == [(0.1, 0.2), (0.8, 0.2), (0.7, 0.9), (0.2, 0.8)]


def test_polygon_parser_fails_closed_on_invalid_coordinates(harness, tmp_path: Path) -> None:
    label = tmp_path / "label.txt"
    with pytest.raises(RuntimeError, match="normalized"):
        harness.parse_yolo_segmentation_line(
            "0 0.1 0.1 1.2 0.1 0.8 0.8",
            label_path=label,
        )
    with pytest.raises(RuntimeError, match="Odd polygon coordinate"):
        harness.parse_yolo_segmentation_line(
            "0 0.1 0.1 0.8 0.1 0.8 0.8 0.2",
            label_path=label,
        )


def test_dataset_inspection_requires_explicit_train_val_test_polygon_layout(
    harness, tmp_path: Path
) -> None:
    for split in ("train", "valid", "test"):
        image_dir = tmp_path / split / "images"
        label_dir = tmp_path / split / "labels"
        image_dir.mkdir(parents=True)
        label_dir.mkdir(parents=True)
        (image_dir / f"{split}.png").write_bytes(f"fixture-{split}".encode())
        (label_dir / f"{split}.txt").write_text(
            "0 0.1 0.1 0.8 0.1 0.8 0.8 0.1 0.8\n", encoding="utf-8"
        )
    (tmp_path / "data.yaml").write_text(
        "train: train/images\nval: valid/images\ntest: test/images\nnames:\n  0: Coral\n",
        encoding="utf-8",
    )

    _, names, splits = harness.inspect_yolo_segmentation_dataset(tmp_path)

    assert names == {0: "Coral"}
    assert set(splits) == {"train", "val", "test"}
    assert all(len(items) == 1 for items in splits.values())

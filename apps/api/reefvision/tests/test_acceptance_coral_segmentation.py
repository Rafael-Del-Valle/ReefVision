"""Tests for the bounded CPU segmentation acceptance dataset."""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "acceptance_coral_segmentation.py"


def load_module() -> ModuleType:
    assert SCRIPT.is_file(), "CPU segmentation acceptance harness is missing"
    spec = importlib.util.spec_from_file_location("acceptance_coral_segmentation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def polygon_area(points: list[list[float]]) -> float:
    return abs(
        sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
        / 2
    )


def normalized_manifest(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **{key: value for key, value in record.items() if key not in {"path", "label_path"}},
            "path": Path(record["path"]).name,
            "label_path": Path(record["label_path"]).name,
        }
        for record in records
    ]


def test_synthetic_dataset_is_deterministic_varied_and_leak_free(tmp_path: Path) -> None:
    module = load_module()
    split_counts = {"train": 4, "validation": 2, "test": 2}
    first = module.generate_synthetic_dataset(
        tmp_path / "first",
        seed=103,
        image_size=128,
        split_counts=split_counts,
    )
    second = module.generate_synthetic_dataset(
        tmp_path / "second",
        seed=103,
        image_size=128,
        split_counts=split_counts,
    )

    assert normalized_manifest(first) == normalized_manifest(second)
    assert len(first) == sum(split_counts.values())
    assert {record["split"] for record in first} == set(split_counts)
    assert len({record["sha256"] for record in first}) == len(first)
    assert {item["class_name"] for record in first for item in record["objects"]} == {
        "branching coral",
        "massive coral",
    }

    hashes_by_split: dict[str, set[str]] = {}
    centers: set[tuple[int, int]] = set()
    for record in first:
        path = Path(record["path"])
        assert path.is_file()
        assert file_hash(path) == record["sha256"]
        hashes_by_split.setdefault(record["split"], set()).add(record["sha256"])
        with Image.open(path) as image:
            assert image.size == (128, 128)
        assert len(record["objects"]) == 2
        for item in record["objects"]:
            points = item["polygon"]
            assert len(points) >= 4
            assert polygon_area(points) > 0
            assert all(0 <= x < 128 and 0 <= y < 128 for x, y in points)
            centers.add(
                (
                    round(sum(point[0] for point in points) / len(points)),
                    round(sum(point[1] for point in points) / len(points)),
                )
            )

    assert hashes_by_split["train"].isdisjoint(hashes_by_split["validation"])
    assert hashes_by_split["train"].isdisjoint(hashes_by_split["test"])
    assert hashes_by_split["validation"].isdisjoint(hashes_by_split["test"])
    assert len(centers) >= 6


def test_dataset_inspection_rejects_cross_split_image_leakage(tmp_path: Path) -> None:
    module = load_module()
    destination = tmp_path / "leaked"
    module.generate_synthetic_dataset(
        destination,
        split_counts={"train": 2, "validation": 1, "test": 1},
    )
    train_image = next((destination / "train" / "images").iterdir())
    test_image = next((destination / "test" / "images").iterdir())
    shutil.copyfile(train_image, test_image)

    with pytest.raises(RuntimeError, match="split leakage"):
        module.inspect_yolo_segmentation_dataset(destination)


def test_polygon_validation_requires_class_mapping_and_source_bounds() -> None:
    module = load_module()
    valid = SimpleNamespace(
        geometry_kind="polygon_mask",
        polygon_json=[[8.0, 6.0], [80.0, 6.0], [80.0, 60.0], [8.0, 60.0]],
        x_min=8.0,
        y_min=6.0,
        x_max=80.0,
        y_max=60.0,
        confidence=0.9,
        review_status="pending",
        label_class_id="class-a",
    )
    outside = SimpleNamespace(**vars(valid))
    outside.polygon_json = [[8.0, 6.0], [129.0, 6.0], [80.0, 60.0], [8.0, 60.0]]
    wrong_class = SimpleNamespace(**vars(valid))
    wrong_class.label_class_id = "class-b"
    self_intersecting = SimpleNamespace(**vars(valid))
    self_intersecting.polygon_json = [
        [8.0, 8.0],
        [80.0, 80.0],
        [8.0, 80.0],
        [60.0, 8.0],
    ]

    assert module._polygon_is_valid(
        valid,
        width=128,
        height=128,
        allowed_class_ids={"class-a"},
    )
    assert not module._polygon_is_valid(
        outside,
        width=128,
        height=128,
        allowed_class_ids={"class-a"},
    )
    assert not module._polygon_is_valid(
        wrong_class,
        width=128,
        height=128,
        allowed_class_ids={"class-a"},
    )
    assert not module._polygon_is_valid(
        self_intersecting,
        width=128,
        height=128,
        allowed_class_ids={"class-a"},
    )


def test_acceptance_labels_do_not_describe_synthetic_data_as_real() -> None:
    module = load_module()

    assert module.acceptance_dataset_label("synthetic") == "Synthetic technical"
    assert module.acceptance_dataset_label("representative") == "Representative coral"


def test_failed_image_import_reports_source_and_api_detail() -> None:
    module = load_module()
    report = {
        "successful": [],
        "failed": [
            {
                "filename": "sample.png",
                "detail": "managed staging path could not be created",
            }
        ],
    }

    with pytest.raises(
        RuntimeError,
        match=r"sample\.png.*managed staging path could not be created",
    ):
        module.require_imported_image_id(report, Path("sample.png"))

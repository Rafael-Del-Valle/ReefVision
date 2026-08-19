from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def harness():
    path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "acceptance_coral_classification.py"
    )
    spec = importlib.util.spec_from_file_location("acceptance_coral_classification", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_layout(root: Path, classes: tuple[str, ...]) -> None:
    for split in ("train", "val", "test"):
        for class_name in classes:
            class_dir = root / split / class_name
            class_dir.mkdir(parents=True)
            (class_dir / f"{split}-{class_name}.png").write_bytes(b"fixture")


def test_inspection_accepts_explicit_two_class_train_val_test_layout(
    harness, tmp_path: Path
) -> None:
    _write_layout(tmp_path, ("Healthy", "Stressed"))

    classes, splits = harness.inspect_classification_dataset(tmp_path)

    assert classes == ["Healthy", "Stressed"]
    assert set(splits) == {"train", "val", "test"}
    assert all(len(items) == 2 for items in splits.values())


def test_inspection_rejects_single_class_dataset(harness, tmp_path: Path) -> None:
    _write_layout(tmp_path, ("OnlyClass",))

    with pytest.raises(RuntimeError, match="at least two classes"):
        harness.inspect_classification_dataset(tmp_path)


def test_inspection_rejects_class_missing_from_required_split(
    harness, tmp_path: Path
) -> None:
    _write_layout(tmp_path, ("Healthy", "Stressed"))
    for path in (tmp_path / "test" / "Stressed").iterdir():
        path.unlink()
    (tmp_path / "test" / "Stressed").rmdir()

    with pytest.raises(RuntimeError, match="absent from required split"):
        harness.inspect_classification_dataset(tmp_path)


def test_inspection_requires_explicit_test_split(harness, tmp_path: Path) -> None:
    _write_layout(tmp_path, ("Healthy", "Stressed"))
    for class_dir in (tmp_path / "test").iterdir():
        for path in class_dir.iterdir():
            path.unlink()
        class_dir.rmdir()
    (tmp_path / "test").rmdir()

    with pytest.raises(RuntimeError, match="explicit test"):
        harness.inspect_classification_dataset(tmp_path)

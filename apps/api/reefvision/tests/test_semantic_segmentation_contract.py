from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

import reefvision.ml.semantic_segmentation as semantic_module
from reefvision.domain.errors import ValidationError
from reefvision.ml.semantic_segmentation import (
    NnUNetV2Provider,
    SemanticClassDefinition,
    SemanticDatasetContract,
    SemanticTrainingRequest,
    _materialize_nnunet_dataset,
    semantic_provider_for_name,
)


def _dataset(tmp_path: Path) -> SemanticDatasetContract:
    export_root = tmp_path / "semantic-export"
    images_root = export_root / "images"
    masks_root = export_root / "masks"
    images_root.mkdir(parents=True)
    masks_root.mkdir(parents=True)
    classes_file = export_root / "classes.json"
    classes_file.write_text("{}", encoding="utf-8")
    return SemanticDatasetContract(
        dataset_version_id="dataset-1",
        dataset_manifest_sha256="a" * 64,
        split_manifest_sha256="b" * 64,
        export_root=export_root,
        images_root=images_root,
        masks_root=masks_root,
        classes_file=classes_file,
        classes=(
            SemanticClassDefinition(
                class_index=0,
                pixel_value=1,
                class_name="soft coral",
            ),
        ),
        overlap_policy="higher class index overwrites lower class index",
    )


def test_semantic_dataset_contract_validates_indexed_png_layout(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    dataset.validate()


def test_semantic_dataset_contract_rejects_background_as_foreground(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    invalid = SemanticDatasetContract(
        **{
            **dataset.__dict__,
            "classes": (
                SemanticClassDefinition(
                    class_index=0,
                    pixel_value=0,
                    class_name="soft coral",
                ),
            ),
        }
    )
    with pytest.raises(ValidationError, match="between 1 and 255"):
        invalid.validate()


def test_nnunet_provider_reports_optional_dependency_blockers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantic_module, "_nnunet_version", lambda: None)
    monkeypatch.setattr(semantic_module, "_command_path", lambda _name: None)
    provider = semantic_provider_for_name("nnunet")
    assert isinstance(provider, NnUNetV2Provider)
    request = SemanticTrainingRequest(
        run_id="run-1",
        project_id="project-1",
        dataset=_dataset(tmp_path),
        workspace_root=tmp_path / "work",
    )
    blockers, warnings = provider.preflight(request)
    assert warnings == []
    assert any("not installed" in blocker for blocker in blockers)
    with pytest.raises(ValidationError, match="not installed"):
        provider.train(request)


def test_nnunet_dataset_materialization_writes_native_2d_layout(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    for split in ("train", "validation", "test"):
        (dataset.images_root / split).mkdir()
        (dataset.masks_root / split).mkdir()
    Image.new("RGB", (12, 8), (10, 20, 30)).save(dataset.images_root / "train" / "coral.jpg")
    train_mask = Image.new("L", (12, 8), 0)
    train_mask.putpixel((4, 3), 1)
    train_mask.save(dataset.masks_root / "train" / "coral.png")
    Image.new("RGB", (12, 8), (30, 20, 10)).save(
        dataset.images_root / "validation" / "coral-val.png"
    )
    validation_mask = Image.new("L", (12, 8), 0)
    validation_mask.putpixel((5, 4), 1)
    validation_mask.save(dataset.masks_root / "validation" / "coral-val.png")

    raw_root = tmp_path / "nnUNet_raw"
    raw_root.mkdir()
    train, validation, test = _materialize_nnunet_dataset(
        dataset,
        raw_root,
        "Dataset501_ReefVision_Test",
    )

    dataset_root = raw_root / "Dataset501_ReefVision_Test"
    assert len(train) == 1
    assert len(validation) == 1
    assert test == []
    assert (dataset_root / "imagesTr" / f"{train[0]}_0000.png").is_file()
    assert (dataset_root / "labelsTr" / f"{train[0]}.png").is_file()
    assert (dataset_root / "imagesTr" / f"{validation[0]}_0000.png").is_file()
    payload = json.loads((dataset_root / "dataset.json").read_text(encoding="utf-8"))
    assert payload["channel_names"] == {"0": "RGB"}
    assert payload["labels"] == {"background": 0, "soft coral": 1}
    assert payload["numTraining"] == 2
    assert payload["file_ending"] == ".png"

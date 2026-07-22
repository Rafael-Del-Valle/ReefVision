"""Focused contracts for Transformers, ReefVision U-Net, and nnU-Net integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.nnunet_provider import (
    NnUNetCase,
    NnUNetDatasetManifest,
    NnUNetPaths,
    export_nnunet_dataset,
    nnunet_command_environment,
)
from reefvision.ml.reefvision_unet import PRESETS, UNetCheckpointMetadata
from reefvision.ml.transformers_provider import (
    TransformersVisionDetectionProvider,
    inspect_transformers_model,
)


@pytest.mark.parametrize(
    ("model_type", "provider"),
    [
        ("grounding-dino", "grounding_dino"),
        ("owlv2", "owlv2"),
        ("florence2", "florence2"),
    ],
)
def test_transformers_provider_inspects_local_model_directory(
    tmp_path: Path,
    model_type: str,
    provider: str,
) -> None:
    model_dir = tmp_path / provider
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        json.dumps({"model_type": model_type}),
        encoding="utf-8",
    )

    spec = inspect_transformers_model(model_dir)
    metadata = TransformersVisionDetectionProvider(provider).inspect_model(model_dir)

    assert spec.provider_name == provider
    assert metadata.framework == "transformers"
    assert metadata.metadata["local_files_only"] is True
    assert metadata.metadata["prompt_required"] is True


def test_transformers_provider_rejects_wrong_architecture(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        json.dumps({"model_type": "owlv2"}),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="not grounding_dino"):
        TransformersVisionDetectionProvider("grounding_dino").inspect_model(model_dir)


def test_unet_presets_are_ordered_and_checkpoint_metadata_is_explicit() -> None:
    assert list(PRESETS) == ["nano", "small", "medium", "large", "xlarge"]
    assert [len(PRESETS[name].channels) for name in PRESETS] == [4, 4, 4, 4, 4]
    assert PRESETS["nano"].channels[0] < PRESETS["xlarge"].channels[0]

    metadata = UNetCheckpointMetadata(
        format_version=1,
        preset="small",
        input_channels=3,
        num_classes=2,
        class_labels=("background", "coral"),
        image_size=512,
    )

    assert metadata.class_labels[1] == "coral"


def test_nnunet_export_writes_expected_raw_dataset(tmp_path: Path) -> None:
    source_image = tmp_path / "source.jpg"
    source_mask = tmp_path / "mask.png"
    Image.new("RGB", (16, 12), (10, 20, 30)).save(source_image)
    Image.new("L", (16, 12), 1).save(source_mask)
    paths = NnUNetPaths(
        raw=tmp_path / "raw",
        preprocessed=tmp_path / "preprocessed",
        results=tmp_path / "results",
    )
    manifest = NnUNetDatasetManifest(
        dataset_id=7,
        dataset_name="CoralMasks",
        channel_names={"0": "RGB"},
        labels={"background": 0, "coral": 1},
        num_training=1,
    )

    root = export_nnunet_dataset(
        paths,
        manifest,
        [NnUNetCase("coral_001", source_image, source_mask)],
    )

    assert root.name == "Dataset007_CoralMasks"
    assert (root / "imagesTr" / "coral_001_0000.png").is_file()
    assert (root / "labelsTr" / "coral_001.png").is_file()
    payload = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
    assert payload["numTraining"] == 1
    assert payload["labels"]["coral"] == 1

    environment = nnunet_command_environment(paths)
    assert environment["nnUNet_raw"] == str(paths.raw.resolve())
    assert environment["PYTHONNOUSERSITE"] == "1"


def test_nnunet_export_rejects_mask_labels_outside_manifest(tmp_path: Path) -> None:
    source_image = tmp_path / "source.jpg"
    source_mask = tmp_path / "mask.png"
    Image.new("RGB", (8, 8), (0, 0, 0)).save(source_image)
    Image.new("L", (8, 8), 3).save(source_mask)
    paths = NnUNetPaths(tmp_path / "raw", tmp_path / "pre", tmp_path / "results")
    manifest = NnUNetDatasetManifest(
        dataset_id=1,
        dataset_name="Invalid",
        channel_names={"0": "RGB"},
        labels={"background": 0, "coral": 1},
        num_training=1,
    )

    with pytest.raises(ValidationError, match="above declared maximum"):
        export_nnunet_dataset(
            paths,
            manifest,
            [NnUNetCase("case_1", source_image, source_mask)],
        )

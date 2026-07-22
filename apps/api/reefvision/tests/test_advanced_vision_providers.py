"""Focused contracts for Transformers, ReefVision U-Net, and nnU-Net integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from reefvision.db.models import Project
from reefvision.domain.errors import ValidationError
from reefvision.ml.nnunet_provider import (
    NnUNetCase,
    NnUNetDatasetManifest,
    NnUNetPaths,
    export_nnunet_dataset,
    nnunet_command_environment,
)
from reefvision.ml.providers import DetectionSettings
from reefvision.ml.reefvision_unet import PRESETS, UNetCheckpointMetadata
from reefvision.ml.reefvision_unet_semantic import _RepeatableBatchIterable
from reefvision.ml.transformers_provider import (
    TransformersVisionDetectionProvider,
    inspect_transformers_model,
)
from reefvision.services.segmentation_catalog import SegmentationModelCatalogService


class _FakeZeroShotModel:
    def __call__(self, **_inputs: Any) -> object:
        return object()


class _FakeGroundingProcessor:
    def __init__(self) -> None:
        self.received: dict[str, Any] = {}

    def __call__(self, **_inputs: Any) -> dict[str, Any]:
        import torch

        return {
            "input_ids": torch.tensor([[1, 2]]),
            "pixel_values": torch.zeros((1, 3, 8, 8)),
        }

    def post_process_grounded_object_detection(
        self,
        *,
        outputs: object,
        input_ids: Any,
        threshold: float,
        text_threshold: float,
        target_sizes: Any,
        text_labels: list[list[str]],
    ) -> list[dict[str, Any]]:
        import torch

        self.received = {
            "outputs": outputs,
            "input_ids": input_ids,
            "threshold": threshold,
            "text_threshold": text_threshold,
            "target_sizes": target_sizes,
            "text_labels": text_labels,
        }
        return [
            {
                "boxes": torch.tensor([[1.0, 2.0, 6.0, 7.0]]),
                "scores": torch.tensor([0.9]),
                "text_labels": [text_labels[0][0]],
            }
        ]


class _FakeOwlv2Processor:
    def __init__(self) -> None:
        self.received: dict[str, Any] = {}

    def __call__(self, **_inputs: Any) -> dict[str, Any]:
        import torch

        return {
            "input_ids": torch.tensor([[1, 2]]),
            "pixel_values": torch.zeros((1, 3, 8, 8)),
        }

    def post_process_grounded_object_detection(
        self,
        *,
        outputs: object,
        threshold: float,
        target_sizes: Any,
        text_labels: list[list[str]],
    ) -> list[dict[str, Any]]:
        import torch

        self.received = {
            "outputs": outputs,
            "threshold": threshold,
            "target_sizes": target_sizes,
            "text_labels": text_labels,
        }
        return [
            {
                "boxes": torch.tensor([[2.0, 3.0, 7.0, 8.0]]),
                "scores": torch.tensor([0.8]),
                "text_labels": [text_labels[0][1]],
            }
        ]


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


def test_grounding_dino_uses_pinned_postprocessor_signature(tmp_path: Path) -> None:
    import torch

    image_path = tmp_path / "image.png"
    Image.new("RGB", (8, 8), (10, 20, 30)).save(image_path)
    processor = _FakeGroundingProcessor()
    provider = TransformersVisionDetectionProvider("grounding_dino")
    provider._processor = processor
    provider._model = _FakeZeroShotModel()
    provider._device = torch.device("cpu")

    predictions = provider.predict(
        image_path,
        DetectionSettings(confidence_threshold=0.35, iou_threshold=0.45, device="cpu"),
        text_prompt="coral polyp, fish",
    )

    assert len(predictions) == 1
    assert predictions[0].label == "coral polyp"
    assert processor.received["threshold"] == pytest.approx(0.35)
    assert processor.received["text_threshold"] == pytest.approx(0.35)
    assert processor.received["text_labels"] == [["coral polyp", "fish"]]


def test_owlv2_uses_batched_text_labels(tmp_path: Path) -> None:
    import torch

    image_path = tmp_path / "image.png"
    Image.new("RGB", (8, 8), (10, 20, 30)).save(image_path)
    processor = _FakeOwlv2Processor()
    provider = TransformersVisionDetectionProvider("owlv2")
    provider._processor = processor
    provider._model = _FakeZeroShotModel()
    provider._device = torch.device("cpu")

    predictions = provider.predict(
        image_path,
        DetectionSettings(confidence_threshold=0.25, iou_threshold=0.45, device="cpu"),
        text_prompt="coral polyp, fish",
    )

    assert len(predictions) == 1
    assert predictions[0].label == "fish"
    assert processor.received["threshold"] == pytest.approx(0.25)
    assert processor.received["text_labels"] == [["coral polyp", "fish"]]


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


def test_native_unet_batch_iterable_can_be_reused_across_epochs(
    tmp_path: Path,
) -> None:
    source_image = tmp_path / "source.png"
    source_mask = tmp_path / "mask.png"
    Image.new("RGB", (16, 16), (10, 20, 30)).save(source_image)
    Image.new("L", (16, 16), 1).save(source_mask)
    batches = _RepeatableBatchIterable(
        [(source_image, source_mask)],
        image_size=16,
        batch_size=1,
        shuffle=False,
        seed=7,
    )

    first_epoch = list(batches)
    second_epoch = list(batches)

    assert len(first_epoch) == len(second_epoch) == 1
    assert first_epoch[0][0].shape == second_epoch[0][0].shape == (1, 3, 16, 16)
    assert first_epoch[0][1].shape == second_epoch[0][1].shape == (1, 16, 16)


def test_training_catalog_exposes_five_native_unets_and_one_nnunet(client) -> None:
    project_id = "33333333-3333-3333-3333-333333333333"
    with client.app.state.session_factory() as session:
        session.add(
            Project(
                id=project_id,
                name="Semantic providers",
                slug="semantic-providers",
                storage_root="projects/semantic-providers",
            )
        )
        session.commit()
        catalog = SegmentationModelCatalogService(
            session,
            client.app.state.settings,
        ).list_project_catalog(project_id, workflow="training")

    native = [
        item
        for item in catalog.models
        if item.catalog_id.startswith("reefvision/unet/")
    ]
    nnunet = [item for item in catalog.models if item.provider_id == "nnunet"]

    assert [item.variant for item in native] == [
        "large",
        "medium",
        "nano",
        "small",
        "xlarge",
    ]
    assert all(item.trainable for item in native)
    assert len(nnunet) == 1
    assert nnunet[0].catalog_id == "nnunet/v2/semantic/2d"
    assert nnunet[0].trainable is True


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

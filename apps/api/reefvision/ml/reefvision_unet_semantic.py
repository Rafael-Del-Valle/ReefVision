"""Semantic training and inference adapter for the native ReefVision U-Net."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.ml.reefvision_unet import (
    UNetCheckpointMetadata,
    build_unet,
    save_unet_checkpoint,
    train_unet,
)
from reefvision.ml.semantic_segmentation import (
    SemanticDatasetContract,
    SemanticSegmentationProvider,
    SemanticTrainingRequest,
    SemanticTrainingResult,
)

REEFVISION_UNET_PROVIDER_ID = "reefvision_unet"


def _torch() -> Any:
    try:
        import torch
    except Exception as exc:
        raise ValidationError(f"PyTorch is required for ReefVision U-Net: {exc}") from exc
    return torch


def _image_mask_pairs(
    dataset: SemanticDatasetContract,
    split: str,
    *,
    image_size: int,
) -> list[tuple[Path, Path]]:
    del image_size
    image_root = dataset.images_root / split
    mask_root = dataset.masks_root / split
    if not image_root.is_dir() or not mask_root.is_dir():
        return []
    pairs: list[tuple[Path, Path]] = []
    for image_path in sorted(path for path in image_root.iterdir() if path.is_file()):
        mask_path = mask_root / f"{image_path.stem}.png"
        if not mask_path.is_file():
            raise ValidationError(f"Semantic mask is missing for {image_path.name}")
        pairs.append((image_path, mask_path))
    return pairs


def _batch_iterator(
    pairs: list[tuple[Path, Path]],
    *,
    image_size: int,
    batch_size: int,
    shuffle: bool,
    seed: int | None,
) -> Iterator[tuple[Any, Any]]:
    torch = _torch()
    import numpy

    indices = list(range(len(pairs)))
    if shuffle:
        generator = torch.Generator()
        if seed is not None:
            generator.manual_seed(seed)
        indices = torch.randperm(len(indices), generator=generator).tolist()
    for offset in range(0, len(indices), batch_size):
        image_tensors: list[Any] = []
        mask_tensors: list[Any] = []
        for index in indices[offset : offset + batch_size]:
            image_path, mask_path = pairs[index]
            with Image.open(image_path) as source_image:
                image = source_image.convert("RGB").resize(
                    (image_size, image_size),
                    Image.Resampling.BILINEAR,
                )
            with Image.open(mask_path) as source_mask:
                mask = source_mask.convert("L").resize(
                    (image_size, image_size),
                    Image.Resampling.NEAREST,
                )
            image_array = numpy.asarray(image, dtype="float32") / 255.0
            mask_array = numpy.asarray(mask, dtype="int64")
            image_tensors.append(torch.from_numpy(image_array).permute(2, 0, 1))
            mask_tensors.append(torch.from_numpy(mask_array))
        yield torch.stack(image_tensors), torch.stack(mask_tensors)


class _RepeatableBatchIterable:
    """Create a fresh lazy batch iterator every time an epoch starts."""

    def __init__(
        self,
        pairs: list[tuple[Path, Path]],
        *,
        image_size: int,
        batch_size: int,
        shuffle: bool,
        seed: int | None,
    ) -> None:
        self.pairs = pairs
        self.image_size = image_size
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.seed = seed

    def __iter__(self) -> Iterator[tuple[Any, Any]]:
        return _batch_iterator(
            self.pairs,
            image_size=self.image_size,
            batch_size=self.batch_size,
            shuffle=self.shuffle,
            seed=self.seed,
        )


def _dice_from_indexed_masks(predicted: Any, expected: Any, num_classes: int) -> float:
    scores: list[float] = []
    for class_index in range(1, num_classes):
        prediction = predicted == class_index
        target = expected == class_index
        denominator = float(prediction.sum() + target.sum())
        if denominator == 0:
            continue
        intersection = float((prediction & target).sum())
        scores.append((2.0 * intersection) / denominator)
    return sum(scores) / len(scores) if scores else 1.0


class NativeUNetSemanticProvider(SemanticSegmentationProvider):
    provider_id = REEFVISION_UNET_PROVIDER_ID

    @property
    def provider_version(self) -> str:
        return "1.0"

    def preflight(
        self,
        request: SemanticTrainingRequest,
    ) -> tuple[list[str], list[str]]:
        blockers: list[str] = []
        warnings: list[str] = []
        try:
            request.dataset.validate()
        except ValidationError as exc:
            blockers.append(str(exc))
        preset = str(request.training_config.get("preset") or "small").casefold()
        if preset not in {"nano", "small", "medium", "large", "xlarge"}:
            blockers.append("ReefVision U-Net preset must be nano, small, medium, large, or xlarge")
        epochs = int(request.training_config.get("epochs", 50))
        if epochs < 1:
            blockers.append("ReefVision U-Net requires at least one epoch")
        image_size = int(request.training_config.get("image_size", 512))
        if image_size < 64 or image_size > 4096 or image_size % 16 != 0:
            blockers.append("ReefVision U-Net image_size must be 64-4096 and divisible by 16")
        if request.precision == "amp":
            warnings.append("Native U-Net currently trains in fp32; AMP will be ignored")
        if request.workspace_root is None:
            blockers.append("ReefVision U-Net training requires a managed workspace root")
        return blockers, warnings

    def train(self, request: SemanticTrainingRequest) -> SemanticTrainingResult:
        blockers, warnings = self.preflight(request)
        if blockers:
            raise ValidationError("; ".join(blockers))
        if request.workspace_root is None:
            raise ValidationError("ReefVision U-Net training requires a managed workspace root")
        torch = _torch()
        workspace = request.workspace_root.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        preset = str(request.training_config.get("preset") or "small").casefold()
        image_size = int(request.training_config.get("image_size", 512))
        epochs = int(request.training_config.get("epochs", 50))
        batch_size = max(1, int(request.training_config.get("batch_size", 2)))
        learning_rate = float(request.training_config.get("learning_rate", 1e-3))
        num_classes = len(request.dataset.classes) + 1
        labels = ("background",) + tuple(
            item.class_name
            for item in sorted(request.dataset.classes, key=lambda item: item.pixel_value)
        )
        train_pairs = _image_mask_pairs(request.dataset, "train", image_size=image_size)
        validation_pairs = _image_mask_pairs(
            request.dataset,
            "validation",
            image_size=image_size,
        )
        if not train_pairs:
            raise ValidationError("ReefVision U-Net requires at least one training image")
        if not validation_pairs:
            validation_pairs = train_pairs[-1:]
            train_pairs = train_pairs[:-1] or train_pairs
        model = build_unet(preset, input_channels=3, num_classes=num_classes)
        trained, history = train_unet(
            model,
            _RepeatableBatchIterable(
                train_pairs,
                image_size=image_size,
                batch_size=batch_size,
                shuffle=True,
                seed=request.random_seed,
            ),
            _RepeatableBatchIterable(
                validation_pairs,
                image_size=image_size,
                batch_size=batch_size,
                shuffle=False,
                seed=request.random_seed,
            ),
            epochs=epochs,
            learning_rate=learning_rate,
            device=request.device,
        )
        metadata = UNetCheckpointMetadata(
            format_version=1,
            preset=preset,
            input_channels=3,
            num_classes=num_classes,
            class_labels=labels,
            image_size=image_size,
        )
        checkpoint = workspace / "reefvision-unet.pt"
        save_unet_checkpoint(
            checkpoint,
            trained,
            metadata,
            epoch=epochs,
            metrics={
                "train_loss": history[-1]["train_loss"],
                "validation_loss": history[-1]["validation_loss"],
            },
        )
        device = torch.device(
            "cuda:0" if request.device != "cpu" and torch.cuda.is_available() else "cpu"
        )
        trained = trained.to(device).eval()
        dice_scores: list[float] = []
        with torch.inference_mode():
            for images, masks in _batch_iterator(
                validation_pairs,
                image_size=image_size,
                batch_size=batch_size,
                shuffle=False,
                seed=request.random_seed,
            ):
                images = images.to(device)
                masks = masks.to(device)
                predictions = trained(images).argmax(dim=1)
                dice_scores.append(_dice_from_indexed_masks(predictions, masks, num_classes))
        metrics = {
            "semantic/train_loss": history[-1]["train_loss"],
            "semantic/validation_loss": history[-1]["validation_loss"],
            "semantic/foreground_dice": sum(dice_scores) / max(len(dice_scores), 1),
        }
        manifest = {
            "format": "reefvision_unet_v1",
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "preset": preset,
            "image_size": image_size,
            "classes": [
                {
                    "class_index": item.class_index,
                    "pixel_value": item.pixel_value,
                    "class_name": item.class_name,
                }
                for item in request.dataset.classes
            ],
            "warnings": warnings,
            "history": history,
        }
        (workspace / "reefvision-unet-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        return SemanticTrainingResult(
            checkpoint_path=checkpoint,
            metrics=metrics,
            metrics_history={
                "semantic/train_loss": [item["train_loss"] for item in history],
                "semantic/validation_loss": [item["validation_loss"] for item in history],
            },
            artifact_manifest=manifest,
            provider_version=self.provider_version,
        )

    def predict(
        self,
        checkpoint_path: Path,
        image_path: Path,
        *,
        device: str,
    ) -> Path:
        from reefvision.ml.reefvision_unet import ReefVisionUNetProvider

        provider = ReefVisionUNetProvider()
        provider.load_model(checkpoint_path, device)
        try:
            indexed = provider.predict_mask(image_path)
        finally:
            provider.unload_model()
        temporary = tempfile.NamedTemporaryFile(
            prefix="reefvision-unet-prediction-",
            suffix=".png",
            delete=False,
        )
        temporary.close()
        output = Path(temporary.name)
        Image.fromarray(indexed.astype("uint8"), mode="L").save(output, format="PNG")
        return output

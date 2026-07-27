"""Native ReefVision U-Net architectures, checkpoints, training, and inference."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from reefvision.domain.errors import ValidationError


@dataclass(frozen=True)
class UNetPreset:
    name: str
    channels: tuple[int, ...]
    dropout: float


PRESETS: dict[str, UNetPreset] = {
    "nano": UNetPreset("nano", (16, 32, 64, 128), 0.0),
    "small": UNetPreset("small", (24, 48, 96, 192), 0.05),
    "medium": UNetPreset("medium", (32, 64, 128, 256), 0.1),
    "large": UNetPreset("large", (48, 96, 192, 384), 0.15),
    "xlarge": UNetPreset("xlarge", (64, 128, 256, 512), 0.2),
}


@dataclass(frozen=True)
class UNetCheckpointMetadata:
    format_version: int
    preset: str
    input_channels: int
    num_classes: int
    class_labels: tuple[str, ...]
    image_size: int


def _torch() -> Any:
    try:
        import torch
    except Exception as exc:
        raise ValidationError(f"PyTorch is required for ReefVision U-Net: {exc}") from exc
    return torch


def build_unet(
    preset: str,
    *,
    input_channels: int = 3,
    num_classes: int = 2,
) -> Any:
    torch = _torch()
    nn = torch.nn
    normalized = preset.strip().casefold()
    if normalized not in PRESETS:
        raise ValidationError(f"Unknown ReefVision U-Net preset: {preset}")
    spec = PRESETS[normalized]

    class ConvBlock(nn.Module):  # type: ignore[name-defined,misc]
        def __init__(self, in_channels: int, out_channels: int, dropout: float) -> None:
            super().__init__()
            layers: list[Any] = [
                nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, bias=False),
                nn.BatchNorm2d(out_channels),
                nn.ReLU(inplace=True),
                nn.Conv2d(out_channels, out_channels, kernel_size=3, padding=1, bias=False),
                nn.BatchNorm2d(out_channels),
                nn.ReLU(inplace=True),
            ]
            if dropout > 0:
                layers.append(nn.Dropout2d(dropout))
            self.block = nn.Sequential(*layers)

        def forward(self, value: Any) -> Any:
            return self.block(value)

    class ReefVisionUNet(nn.Module):  # type: ignore[name-defined,misc]
        def __init__(self) -> None:
            super().__init__()
            channels = spec.channels
            self.encoders = nn.ModuleList()
            previous = input_channels
            for channel in channels:
                self.encoders.append(ConvBlock(previous, channel, spec.dropout))
                previous = channel
            self.pool = nn.MaxPool2d(2)
            self.bottleneck = ConvBlock(channels[-1], channels[-1] * 2, spec.dropout)
            decoder_input = channels[-1] * 2
            self.upconvs = nn.ModuleList()
            self.decoders = nn.ModuleList()
            for channel in reversed(channels):
                self.upconvs.append(nn.ConvTranspose2d(decoder_input, channel, 2, stride=2))
                self.decoders.append(ConvBlock(channel * 2, channel, spec.dropout))
                decoder_input = channel
            self.head = nn.Conv2d(channels[0], num_classes, kernel_size=1)

        def forward(self, value: Any) -> Any:
            skips: list[Any] = []
            output = value
            for encoder in self.encoders:
                output = encoder(output)
                skips.append(output)
                output = self.pool(output)
            output = self.bottleneck(output)
            for upconv, decoder, skip in zip(
                self.upconvs,
                self.decoders,
                reversed(skips),
                strict=True,
            ):
                output = upconv(output)
                if output.shape[-2:] != skip.shape[-2:]:
                    output = torch.nn.functional.interpolate(
                        output,
                        size=skip.shape[-2:],
                        mode="bilinear",
                        align_corners=False,
                    )
                output = decoder(torch.cat((skip, output), dim=1))
            return self.head(output)

    return ReefVisionUNet()


def save_unet_checkpoint(
    path: Path,
    model: Any,
    metadata: UNetCheckpointMetadata,
    *,
    optimizer: Any | None = None,
    epoch: int | None = None,
    metrics: dict[str, float] | None = None,
) -> None:
    torch = _torch()
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "reefvision_unet": asdict(metadata),
        "model_state_dict": model.state_dict(),
        "epoch": epoch,
        "metrics": dict(metrics or {}),
    }
    if optimizer is not None:
        payload["optimizer_state_dict"] = optimizer.state_dict()
    temporary = destination.with_suffix(destination.suffix + ".part")
    torch.save(payload, temporary)
    temporary.replace(destination)


def inspect_unet_checkpoint(path: Path) -> UNetCheckpointMetadata:
    torch = _torch()
    checkpoint = path.expanduser().resolve()
    if checkpoint.suffix.casefold() not in {".pt", ".pth"} or not checkpoint.is_file():
        raise ValidationError("ReefVision U-Net requires an existing local .pt or .pth checkpoint")
    try:
        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    except Exception as exc:
        raise ValidationError(f"Could not read ReefVision U-Net checkpoint: {exc}") from exc
    raw = payload.get("reefvision_unet") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raise ValidationError("Checkpoint does not contain ReefVision U-Net metadata")
    try:
        metadata = UNetCheckpointMetadata(
            format_version=int(raw["format_version"]),
            preset=str(raw["preset"]),
            input_channels=int(raw["input_channels"]),
            num_classes=int(raw["num_classes"]),
            class_labels=tuple(str(item) for item in raw["class_labels"]),
            image_size=int(raw["image_size"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"Invalid ReefVision U-Net metadata: {exc}") from exc
    if metadata.format_version != 1:
        raise ValidationError("Unsupported ReefVision U-Net checkpoint format")
    if metadata.preset not in PRESETS:
        raise ValidationError("Checkpoint references an unknown ReefVision U-Net preset")
    if metadata.num_classes < 2 or len(metadata.class_labels) != metadata.num_classes:
        raise ValidationError("Checkpoint class metadata is inconsistent")
    return metadata


class ReefVisionUNetProvider:
    provider_name = "reefvision_unet"
    provider_version = "1.0"

    def __init__(self) -> None:
        self._model: Any | None = None
        self._metadata: UNetCheckpointMetadata | None = None
        self._device: Any = "cpu"

    def inspect_model(self, model_path: Path) -> dict[str, Any]:
        metadata = inspect_unet_checkpoint(model_path)
        return {
            "framework": "pytorch",
            "task": "semantic_segment",
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "class_labels": list(metadata.class_labels),
            "input_size": {"width": metadata.image_size, "height": metadata.image_size},
            "metadata": asdict(metadata),
        }

    def load_model(self, model_path: Path, device: str) -> None:
        torch = _torch()
        metadata = inspect_unet_checkpoint(model_path)
        resolved = device.strip().casefold()
        if resolved in {"", "auto"}:
            torch_device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        elif resolved in {"cuda", "cuda:0", "gpu"}:
            if not torch.cuda.is_available():
                raise ValidationError("CUDA was requested but is unavailable")
            torch_device = torch.device("cuda:0")
        elif resolved == "cpu":
            torch_device = torch.device("cpu")
        else:
            raise ValidationError("Supported devices are auto, cpu, and cuda")
        checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
        model = build_unet(
            metadata.preset,
            input_channels=metadata.input_channels,
            num_classes=metadata.num_classes,
        )
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
        self._model = model.to(torch_device).eval()
        self._metadata = metadata
        self._device = torch_device

    def predict_mask(self, image_path: Path) -> Any:
        torch = _torch()
        if self._model is None or self._metadata is None:
            raise ValidationError("The ReefVision U-Net model is not loaded")
        image = Image.open(image_path).convert("RGB")
        original_size = image.size
        resized = image.resize((self._metadata.image_size, self._metadata.image_size))
        import numpy

        array = numpy.asarray(resized, dtype="float32") / 255.0
        tensor = torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0).to(self._device)
        with torch.inference_mode():
            logits = self._model(tensor)
            mask = logits.argmax(dim=1)[0].to("cpu", dtype=torch.uint8).numpy()
        return numpy.asarray(
            Image.fromarray(mask).resize(original_size, resample=Image.Resampling.NEAREST)
        )

    def unload_model(self) -> None:
        self._model = None
        self._metadata = None
        try:
            torch = _torch()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ValidationError:
            return


def train_unet(
    model: Any,
    train_batches: Iterable[tuple[Any, Any]],
    validation_batches: Iterable[tuple[Any, Any]],
    *,
    epochs: int,
    learning_rate: float,
    device: str = "auto",
) -> tuple[Any, list[dict[str, float]]]:
    """Train from already prepared tensors; dataset creation remains owned by ReefVision."""

    torch = _torch()
    if epochs < 1:
        raise ValidationError("U-Net training requires at least one epoch")
    resolved = torch.device(
        "cuda:0"
        if device in {"auto", "cuda", "cuda:0", "gpu"} and torch.cuda.is_available()
        else "cpu"
    )
    model = model.to(resolved)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    criterion = torch.nn.CrossEntropyLoss()
    history: list[dict[str, float]] = []
    for epoch in range(epochs):
        model.train()
        training_loss = 0.0
        training_count = 0
        for images, masks in train_batches:
            images = images.to(resolved)
            masks = masks.to(resolved, dtype=torch.long)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(images), masks)
            loss.backward()
            optimizer.step()
            training_loss += float(loss.detach().cpu())
            training_count += 1
        model.eval()
        validation_loss = 0.0
        validation_count = 0
        with torch.inference_mode():
            for images, masks in validation_batches:
                images = images.to(resolved)
                masks = masks.to(resolved, dtype=torch.long)
                loss = criterion(model(images), masks)
                validation_loss += float(loss.detach().cpu())
                validation_count += 1
        history.append(
            {
                "epoch": float(epoch + 1),
                "train_loss": training_loss / max(training_count, 1),
                "validation_loss": validation_loss / max(validation_count, 1),
            }
        )
    return model, history


def write_unet_training_manifest(
    path: Path,
    metadata: UNetCheckpointMetadata,
    history: list[dict[str, float]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"metadata": asdict(metadata), "history": history}, indent=2) + "\n",
        encoding="utf-8",
    )

"""Training-only CUDA device resolution, including distributed Ultralytics lists."""

from __future__ import annotations

from reefvision.domain.errors import ValidationError


def resolve_training_device(requested: str) -> str | int:
    """Return an Ultralytics-compatible CPU, single-GPU, or multi-GPU device value."""

    normalized = requested.strip().casefold()
    try:
        import torch
    except Exception as exc:  # pragma: no cover - dependency failure path
        raise ValidationError(f"Torch is required for model training: {exc}") from exc

    if normalized in {"", "auto"}:
        return 0 if torch.cuda.is_available() else "cpu"
    if normalized == "cpu":
        return "cpu"
    if normalized in {"cuda", "gpu"}:
        if not torch.cuda.is_available():
            raise ValidationError("CUDA was requested but is not available")
        return 0

    tokens = [token.strip() for token in normalized.split(",") if token.strip()]
    if not tokens:
        raise ValidationError("The training device list is empty")
    indices: list[int] = []
    for token in tokens:
        if token.startswith("cuda:"):
            token = token.split(":", 1)[1]
        if not token.isdigit():
            raise ValidationError(
                "Training devices must be auto, cpu, cuda, cuda:N, N, or a comma-separated CUDA list"
            )
        index = int(token)
        if index in indices:
            raise ValidationError("Training CUDA device indices must be unique")
        indices.append(index)

    if not torch.cuda.is_available():
        raise ValidationError("CUDA devices were requested but CUDA is not available")
    available = int(torch.cuda.device_count())
    missing = [index for index in indices if index < 0 or index >= available]
    if missing:
        raise ValidationError(
            "Requested CUDA devices are unavailable: " + ", ".join(str(index) for index in missing)
        )
    if len(indices) == 1:
        return indices[0]
    return ",".join(str(index) for index in indices)

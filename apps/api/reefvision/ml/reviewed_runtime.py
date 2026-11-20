"""Resolve only the local execution adapters implemented for registered image models."""

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.ml.provider_hub import cached_runtime_provider_statuses, get_model_provider
from reefvision.ml.semantic_segmentation import NNUNET_PROVIDER_ID, nnunet_dependency_status
from reefvision.ml.sleap_nn_provider import SLEAP_NN_ACTIONABLE_RETIREMENT, SLEAP_NN_PROVIDER_ID
from reefvision.schemas.model_runtime import Device


def resolve_reviewed_runtime(
    settings: Settings, *, provider_id: str, task: str, runtime_id: str, device: Device
) -> tuple[str, str]:
    if provider_id == SLEAP_NN_PROVIDER_ID:
        raise ValidationError(SLEAP_NN_ACTIONABLE_RETIREMENT)
    torch = next(
        item for item in cached_runtime_provider_statuses().value if item.runtime_id == "pytorch"
    )
    if not torch.available or not torch.package_version:
        raise ValidationError("This installation is missing the local PyTorch runtime")
    if device == "cuda" and not torch.cuda_available:
        raise ValidationError("The selected CUDA device is unavailable on this installation")
    if (
        provider_id == NNUNET_PROVIDER_ID
        and task == "semantic_segment"
        and runtime_id == "nnunetv2"
    ):
        status = nnunet_dependency_status()
        if not status["ready"]:
            raise ValidationError(
                "The local nnU-Net runtime is unavailable: " + ", ".join(status["issues"])
            )
        return str(status["provider_version"]), torch.package_version
    supported = {"ultralytics": {"detect", "pose", "segment"}, "reefpose": {"pose"}}
    if runtime_id != "pytorch" or task not in supported.get(provider_id, set()):
        raise ValidationError(
            "No local image inference adapter supports this model, task and runtime"
        )
    descriptor = get_model_provider(provider_id, settings)
    if descriptor.availability_status != "ready":
        raise ValidationError(
            descriptor.availability_reason or "The selected local model provider is unavailable"
        )
    return descriptor.package_version or descriptor.provider_version, torch.package_version

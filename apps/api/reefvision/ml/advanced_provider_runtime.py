"""Register Transformers, ReefVision U-Net, and nnU-Net provider capabilities."""

from __future__ import annotations

from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.ml.reefvision_unet import PRESETS, ReefVisionUNetProvider
from reefvision.ml.transformers_provider import TransformersVisionDetectionProvider

_APPLIED = False
_TRANSFORMERS_CATALOG_IDS = {
    "transformers/florence2/base",
    "transformers/florence2/large",
    "transformers/grounding_dino/tiny",
    "transformers/grounding_dino/base",
    "transformers/owlv2/base",
    "transformers/owlv2/large",
}


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _transformers_ready() -> tuple[bool, str | None]:
    required = ("transformers", "accelerate", "safetensors", "huggingface-hub")
    missing = [name for name in required if _package_version(name) is None]
    if missing:
        return False, "Missing provider-pack packages: " + ", ".join(missing)
    return True, None


def _torch_ready() -> tuple[bool, str | None]:
    installed = _package_version("torch")
    return (installed is not None, None if installed else "PyTorch is not installed")


def _patch_provider_catalog() -> None:
    from reefvision.ml import provider_hub

    original = provider_hub._list_model_providers_uncached

    def list_with_advanced(
        settings: Any = None,
        *,
        refresh: bool = False,
    ) -> list[Any]:
        descriptors = original(settings, refresh=refresh)
        transformers_ready, transformers_reason = _transformers_ready()
        torch_ready, torch_reason = _torch_ready()
        output: list[Any] = []
        for descriptor in descriptors:
            if descriptor.provider_id in {"grounding_dino", "owlv2", "florence2"}:
                capabilities = replace(
                    descriptor.capabilities,
                    image_detection=True,
                    text_prompt_detection=True,
                    cpu_inference=True,
                    cuda_inference=True,
                    packaged_desktop_operation=transformers_ready,
                )
                output.append(
                    replace(
                        descriptor,
                        provider_version="1.0",
                        package_version=_package_version("transformers"),
                        required_packages=provider_hub._packages_not_yet_pinned(
                            "transformers", "accelerate", "safetensors", "huggingface-hub"
                        ),
                        availability_status="ready" if transformers_ready else "dependency_missing",
                        availability_reason=transformers_reason,
                        registerable=True,
                        desktop_packaging_state="optional_pack_runtime",
                        clean_machine_verification_state="acceptance_required",
                        known_limitations=(
                            "Inference is local-only; models must be present in a managed local directory.",
                            "Open-vocabulary predictions remain proposals until explicit review.",
                        ),
                        capabilities=capabilities,
                    )
                )
            elif descriptor.provider_id == "reefvision_unet":
                output.append(
                    replace(
                        descriptor,
                        provider_version="1.0",
                        package_version=_package_version("torch"),
                        training_support=True,
                        availability_status="ready" if torch_ready else "dependency_missing",
                        availability_reason=torch_reason,
                        default_registration_purpose="semantic_segment",
                        registerable=True,
                        desktop_packaging_state="base_sidecar_provider",
                        clean_machine_verification_state="acceptance_required",
                        code_license="MIT (ReefVision native implementation).",
                        known_limitations=(
                            "Semantic masks require explicit review before becoming annotations.",
                            "The first release supports RGB 2D images and indexed semantic masks.",
                        ),
                        capabilities=replace(
                            descriptor.capabilities,
                            image_semantic_segmentation=True,
                            training=True,
                            validation=True,
                            cpu_inference=True,
                            cuda_inference=True,
                            packaged_desktop_operation=torch_ready,
                        ),
                    )
                )
            else:
                output.append(descriptor)

        if not any(item.provider_id == "nnunet" for item in output):
            template = next(item for item in output if item.provider_id == "reefvision_unet")
            nnunet_installed = _package_version("nnunetv2")
            output.append(
                replace(
                    template,
                    provider_id="nnunet",
                    display_name="nnU-Net v2",
                    provider_version=nnunet_installed or "external",
                    package_version=nnunet_installed,
                    supported_model_families=("nnU-Net v2 2D semantic segmentation experiments",),
                    supported_tasks=("semantic_segment",),
                    supported_input_types=("image", "indexed_mask", "dataset_version"),
                    supported_output_types=("semantic_mask", "training_artifacts", "model_folder"),
                    required_model_files=(),
                    required_packages=provider_hub._packages_not_yet_pinned("nnunetv2"),
                    default_registration_purpose=None,
                    registerable=False,
                    availability_status="ready" if nnunet_installed else "dependency_missing",
                    availability_reason=(
                        None
                        if nnunet_installed
                        else "Install nnunetv2 in the configured advanced provider environment."
                    ),
                    desktop_packaging_state="advanced_external_runtime",
                    clean_machine_verification_state="acceptance_required",
                    code_license="Apache-2.0; see the installed nnU-Net package metadata.",
                    weight_license="User-trained checkpoints inherit dataset and experiment terms.",
                    memory_recommendations=(
                        "Use the 2d configuration for ReefVision image datasets.",
                        "Keep nnU-Net preprocessing and results in managed application-data directories.",
                    ),
                    known_limitations=(
                        "nnU-Net runs as an explicit external subprocess with no shell execution.",
                        "Dataset planning and training can be long-running and require substantial disk space.",
                    ),
                    capabilities=replace(
                        template.capabilities,
                        image_semantic_segmentation=True,
                        training=True,
                        validation=True,
                        export=True,
                        packaged_desktop_operation=False,
                    ),
                )
            )
        return output

    provider_hub._list_model_providers_uncached = list_with_advanced


def _patch_provider_factories() -> None:
    from reefvision.ml import provider_hub

    original_registration = provider_hub.provider_for_registration
    original_detection = provider_hub.detection_provider_for_name

    def registration_provider(
        purpose: str,
        *,
        provider_name: str | None = None,
        settings: Any = None,
    ) -> Any:
        normalized = (provider_name or "").strip().casefold().replace("-", "_")
        if purpose == "detector" and normalized in {
            "grounding_dino",
            "owlv2",
            "florence2",
        }:
            ready, reason = _transformers_ready()
            if not ready:
                raise ValidationError(reason or "Transformers provider pack is unavailable")
            return TransformersVisionDetectionProvider(normalized)
        if purpose == "semantic_segment" and normalized in {"", "reefvision_unet"}:
            ready, reason = _torch_ready()
            if not ready:
                raise ValidationError(reason or "PyTorch is unavailable")
            return ReefVisionUNetProvider()
        return original_registration(
            purpose,
            provider_name=provider_name,
            settings=settings,
        )

    def detection_provider(provider_name: str) -> Any:
        normalized = provider_name.strip().casefold().replace("-", "_")
        if normalized in {"grounding_dino", "owlv2", "florence2"}:
            ready, reason = _transformers_ready()
            if not ready:
                raise ValidationError(reason or "Transformers provider pack is unavailable")
            return TransformersVisionDetectionProvider(normalized)
        return original_detection(provider_name)

    provider_hub.provider_for_registration = registration_provider
    provider_hub.detection_provider_for_name = detection_provider


def _patch_semantic_provider() -> None:
    from reefvision.jobs import inference, semantic_training
    from reefvision.ml import semantic_segmentation
    from reefvision.ml.reefvision_unet_semantic import NativeUNetSemanticProvider

    original = semantic_segmentation.semantic_provider_for_name

    def semantic_provider(provider_id: str) -> Any:
        normalized = provider_id.strip().casefold().replace("-", "_")
        if normalized == "reefvision_unet":
            return NativeUNetSemanticProvider()
        return original(provider_id)

    semantic_segmentation.semantic_provider_for_name = semantic_provider
    inference.semantic_provider_for_name = semantic_provider
    semantic_training.semantic_provider_for_name = semantic_provider


def _patch_model_catalog_state() -> None:
    from reefvision.services import model_catalog
    from reefvision.services.bundled_transformers_models import (
        bundled_transformers_model_path,
    )

    original = model_catalog.ModelCatalogService._compose_static_state

    def compose_with_advanced(
        self: Any,
        entry: Any,
        *,
        job: Any,
        manifest: dict[str, Any],
    ) -> Any:
        if entry.catalog_id in _TRANSFORMERS_CATALOG_IDS:
            model_path = bundled_transformers_model_path(self.settings, entry.catalog_id)
            ready, reason = _transformers_ready()
            if model_path is not None and ready:
                return entry.model_copy(
                    update={
                        "availability": "available",
                        "installation_state": "Ready",
                        "installation_reason": "Bundled model snapshot and provider runtime are ready offline.",
                        "installed_asset_id": f"provider_pack:{entry.catalog_id}",
                        "installed_path": str(model_path),
                        "metadata_verified": True,
                        "provider_ready": True,
                        "provider_state": "ready",
                        "provider_failure_reason": None,
                        "selection_kind": "managed_catalog_model",
                        "requires_confirmation": False,
                        "deprecation_status": "active",
                        "desktop_package_status": "bundled_installer",
                        "clean_machine_verification_status": "acceptance_required",
                        "capabilities": {
                            "image_detection": True,
                            "text_prompt_detection": True,
                            "cpu_inference": True,
                            "cuda_inference": True,
                        },
                    }
                )
            if model_path is not None and not ready:
                return entry.model_copy(
                    update={
                        "availability": "available",
                        "installation_state": "Provider Required",
                        "installation_reason": reason or "Transformers provider runtime is unavailable.",
                        "installed_asset_id": f"provider_pack:{entry.catalog_id}",
                        "installed_path": str(model_path),
                        "metadata_verified": True,
                        "provider_ready": False,
                        "provider_state": "unavailable",
                    }
                )
        if entry.catalog_id.startswith("reefvision/unet/"):
            preset = entry.catalog_id.rsplit("/", 1)[-1]
            ready, reason = _torch_ready()
            if preset in PRESETS:
                return entry.model_copy(
                    update={
                        "availability": "available",
                        "installation_state": "Ready" if ready else "Provider Required",
                        "installation_reason": (
                            "Bundled ReefVision U-Net architecture is ready for training."
                            if ready
                            else reason
                        ),
                        "installed_asset_id": f"builtin_architecture:reefvision_unet:{preset}",
                        "metadata_verified": True,
                        "provider_ready": ready,
                        "provider_state": "ready" if ready else "unavailable",
                        "selection_kind": "builtin_architecture",
                        "architecture_reference": preset,
                        "provider_version": "1.0",
                        "trainable": True,
                        "inference": True,
                        "inference_supported": True,
                        "tuning_compatibility": True,
                        "deprecation_status": "active",
                        "desktop_package_status": "base_sidecar_provider",
                        "clean_machine_verification_status": "acceptance_required",
                        "capabilities": {
                            "image_semantic_segmentation": True,
                            "training": True,
                            "validation": True,
                            "cpu_inference": True,
                            "cuda_inference": True,
                        },
                    }
                )
        return original(self, entry, job=job, manifest=manifest)

    model_catalog.ModelCatalogService._compose_static_state = compose_with_advanced


def apply_advanced_provider_runtime_patches() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_provider_catalog()
    _patch_provider_factories()
    _patch_semantic_provider()
    _patch_model_catalog_state()
    _APPLIED = True

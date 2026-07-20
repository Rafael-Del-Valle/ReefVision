"""Register optional SAM-family providers without changing persisted schemas."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import AnnotationAssistProvider
from reefvision.ml.sam_adapters import (
    EfficientViTSAMAssistProvider,
    MobileSAMAssistProvider,
    SAM2ImageAssistProvider,
)

_APPLIED = False


def _provider(provider_name: str) -> AnnotationAssistProvider:
    normalized = provider_name.strip().casefold().replace("-", "_")
    if normalized in {"segment_anything", "sam", "original_sam"}:
        from reefvision.ml.providers import SegmentAnythingAssistProvider

        return SegmentAnythingAssistProvider()
    if normalized in {"mobilesam", "mobile_sam"}:
        return MobileSAMAssistProvider()
    if normalized in {"efficientvit_sam", "efficientvitsam"}:
        return EfficientViTSAMAssistProvider()
    if normalized in {"sam2", "sam_2"}:
        return SAM2ImageAssistProvider()
    raise ValidationError(f"Unsupported assist provider: {provider_name}")


def _patch_capability_specs() -> None:
    from reefvision.services import provider_capabilities as capabilities

    existing = {item.provider_id for item in capabilities._PROVIDER_SPECS}
    additions: list[Any] = []
    gib = 1024**3
    if "segment_anything" not in existing:
        additions.append(
            capabilities._ProviderSpec(
                provider_id="segment_anything",
                display_name="Segment Anything",
                description="Original SAM point, box, and brush-assisted image segmentation.",
                tasks=("prompt_segment", "automatic_mask"),
                prompts=("box", "positive_point", "negative_point", "brush", "existing_mask"),
                dependencies=(
                    capabilities._Dependency("torch", "torch"),
                    capabilities._Dependency("segment-anything", "segment_anything"),
                ),
                training=False,
                inference=True,
                video=False,
                batching=True,
                cpu=True,
                cuda=True,
                mixed_precision=False,
                offline_import=True,
                estimated_vram={"vit_b_1024": 3 * gib, "vit_h_1024": 8 * gib},
            )
        )
    if "mobilesam" not in existing:
        additions.append(
            capabilities._ProviderSpec(
                provider_id="mobilesam",
                display_name="MobileSAM",
                description="Lightweight SAM-compatible point and box prompting.",
                tasks=("prompt_segment", "automatic_mask"),
                prompts=("box", "positive_point", "negative_point", "brush"),
                dependencies=(
                    capabilities._Dependency("torch", "torch"),
                    capabilities._Dependency("mobile-sam", "mobile_sam"),
                ),
                training=False,
                inference=True,
                video=False,
                batching=True,
                cpu=True,
                cuda=True,
                mixed_precision=False,
                offline_import=True,
                estimated_vram={"vit_t_1024": 2 * gib},
            )
        )
    if additions:
        capabilities._PROVIDER_SPECS = (*capabilities._PROVIDER_SPECS, *additions)


def _patch_provider_catalog() -> None:
    from reefvision.ml import provider_hub

    original_list = provider_hub._list_model_providers_uncached

    def list_with_sam(
        settings: Any = None,
        *,
        refresh: bool = False,
    ) -> list[Any]:
        providers = original_list(settings, refresh=refresh)
        output = []
        for descriptor in providers:
            if descriptor.provider_id == "sam2":
                output.append(
                    replace(
                        descriptor,
                        package_version=provider_hub._package_version("sam2"),
                        availability_status=(
                            "ready"
                            if provider_hub._package_version("sam2")
                            else "dependency_missing"
                        ),
                        availability_reason=(
                            None
                            if provider_hub._package_version("sam2")
                            else (
                                "Install the optional sam2 package and register a local checkpoint."
                            )
                        ),
                        registerable=True,
                        known_limitations=(
                            "SAM 2 image prompting and managed video propagation "
                            "require a local checkpoint and inferred Hiera configuration.",
                            "Packaged Windows operation still requires clean-machine acceptance.",
                        ),
                        desktop_packaging_state="optional_pack_runtime",
                        clean_machine_verification_state="acceptance_required",
                    )
                )
            elif descriptor.provider_id == "mobilesam":
                installed = provider_hub._package_version(
                    "mobile-sam"
                ) or provider_hub._package_version("mobile_sam")
                output.append(
                    replace(
                        descriptor,
                        package_version=installed,
                        availability_status="ready" if installed else "dependency_missing",
                        availability_reason=(
                            None
                            if installed
                            else (
                                "Install the optional MobileSAM package and register "
                                "a local checkpoint."
                            )
                        ),
                        registerable=True,
                        known_limitations=(
                            "MobileSAM uses the installed package's SAM-compatible predictor API.",
                            "Packaged Windows operation still requires clean-machine acceptance.",
                        ),
                        desktop_packaging_state="optional_pack_runtime",
                        clean_machine_verification_state="acceptance_required",
                    )
                )
            else:
                output.append(descriptor)
        if not any(item.provider_id == "efficientvit_sam" for item in output):
            mobile = next(item for item in output if item.provider_id == "mobilesam")
            installed = provider_hub._package_version("efficientvit")
            output.append(
                replace(
                    mobile,
                    provider_id="efficientvit_sam",
                    display_name="EfficientViT-SAM",
                    provider_version=installed or "optional",
                    package_version=installed,
                    supported_model_families=("EfficientViT-SAM L0/L1/L2/XL0/XL1 checkpoints",),
                    availability_status="ready" if installed else "dependency_missing",
                    availability_reason=(
                        None
                        if installed
                        else (
                            "Install the optional EfficientViT-SAM package and register "
                            "a local checkpoint."
                        )
                    ),
                    memory_recommendations=(
                        "L0 and L1 variants are preferred for interactive desktop prompting.",
                    ),
                )
            )
        return output

    provider_hub._list_model_providers_uncached = list_with_sam
    provider_hub.assist_provider_for_name = _provider

    original_registration = provider_hub.provider_for_registration

    def registration_provider(
        purpose: str,
        *,
        provider_name: str | None = None,
        settings: Any = None,
    ) -> Any:
        if purpose == "assist" and (provider_name or "").strip().casefold() in {
            "mobilesam",
            "mobile_sam",
            "efficientvit_sam",
            "efficientvitsam",
            "sam2",
            "sam_2",
        }:
            return _provider(provider_name or "")
        return original_registration(
            purpose,
            provider_name=provider_name,
            settings=settings,
        )

    provider_hub.provider_for_registration = registration_provider

    from reefvision.ml import assist_runtime

    assist_runtime.assist_provider_for_name = _provider  # type: ignore[attr-defined]


def apply_sam_runtime_patch() -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_capability_specs()
    _patch_provider_catalog()
    _APPLIED = True

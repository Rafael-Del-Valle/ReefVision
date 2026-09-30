"""Unified provider catalog, capability matrix, and provider factories."""
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from reefvision.config import Settings
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.dependencies import (
    ProviderPackageRequirement,
    ProviderPreflightReport,
    cached_lightweight_provider_preflight,
    provider_spec,
)
from reefvision.ml.providers import (
    AnnotationAssistProvider,
    DetectionProvider,
    SegmentAnythingAssistProvider,
    UltralyticsDetectionProvider,
)
from reefvision.snapshot_cache import CachedSnapshot, get_cached_snapshot

LIGHTWEIGHT_PROVIDER_CATALOG_TTL_SECONDS = 300
RUNTIME_STATUS_TTL_SECONDS = 300


@dataclass(frozen=True)
class ProviderCapabilityMatrix:
    image_detection: bool = False
    image_instance_segmentation: bool = False
    image_semantic_segmentation: bool = False
    text_prompt_detection: bool = False
    image_example_detection: bool = False
    click_prompting: bool = False
    box_prompting: bool = False
    brush_prompting: bool = False
    mask_prompting: bool = False
    video_propagation: bool = False
    multi_object_tracking: bool = False
    training: bool = False
    validation: bool = False
    tiled_training: bool = False
    tiled_inference: bool = False
    export: bool = False
    cpu_inference: bool = False
    cuda_inference: bool = False
    fp16: bool = False
    quantized_inference: bool = False
    packaged_desktop_operation: bool = False


@dataclass(frozen=True)
class ProviderPackageDescriptor:
    distribution_name: str
    required_version: str | None
    installed_version: str | None
    status: str


@dataclass(frozen=True)
class ModelProviderDescriptor:
    provider_id: str
    display_name: str
    provider_version: str
    package_version: str | None
    supported_model_families: tuple[str, ...]
    supported_tasks: tuple[str, ...]
    supported_input_types: tuple[str, ...]
    supported_output_types: tuple[str, ...]
    cpu_support: bool
    cuda_support: bool
    supported_precision_modes: tuple[str, ...]
    video_support: bool
    training_support: bool
    tiling_support: bool
    supported_execution_runtimes: tuple[str, ...]
    required_packages: tuple[ProviderPackageDescriptor, ...]
    required_model_files: tuple[str, ...]
    code_license: str
    weight_license: str
    memory_recommendations: tuple[str, ...]
    known_limitations: tuple[str, ...]
    desktop_packaging_state: str
    clean_machine_verification_state: str
    availability_status: str
    availability_reason: str | None
    default_registration_purpose: str | None
    registerable: bool
    capabilities: ProviderCapabilityMatrix


@dataclass(frozen=True)
class RuntimeProviderStatus:
    runtime_id: str
    display_name: str
    package_name: str | None
    package_version: str | None
    available: bool
    status: str
    supports_cpu: bool
    supports_cuda: bool
    notes: tuple[str, ...]


def _package_version(distribution_name: str) -> str | None:
    try:
        return version(distribution_name)
    except PackageNotFoundError:
        return None


def _packages_from_preflight(
    report: ProviderPreflightReport,
) -> tuple[ProviderPackageDescriptor, ...]:
    return tuple(
        ProviderPackageDescriptor(
            distribution_name=item.distribution_name,
            required_version=item.required_version,
            installed_version=item.installed_version,
            status=item.status,
        )
        for item in report.package_statuses
    )


def _packages_from_requirements(
    requirements: tuple[ProviderPackageRequirement, ...],
) -> tuple[ProviderPackageDescriptor, ...]:
    descriptors: list[ProviderPackageDescriptor] = []
    for requirement in requirements:
        installed = _package_version(requirement.distribution_name)
        descriptors.append(
            ProviderPackageDescriptor(
                distribution_name=requirement.distribution_name,
                required_version=requirement.required_version,
                installed_version=installed,
                status=(
                    "ok"
                    if installed == requirement.required_version
                    else "incompatible"
                    if installed is not None
                    else "missing"
                ),
            )
        )
    return tuple(descriptors)


def _packages_not_yet_pinned(
    *distribution_names: str,
) -> tuple[ProviderPackageDescriptor, ...]:
    return tuple(
        ProviderPackageDescriptor(
            distribution_name=distribution_name,
            required_version=None,
            installed_version=_package_version(distribution_name),
            status="not_pinned",
        )
        for distribution_name in distribution_names
    )


def _implemented_report_map(
    settings: Settings | None = None,
    *,
    refresh: bool = False,
) -> CachedSnapshot[dict[str, ProviderPreflightReport]]:
    snapshot = cached_lightweight_provider_preflight(settings, refresh=refresh)
    return CachedSnapshot(
        value={report.provider_name: report for report in snapshot.value},
        checked_at=snapshot.checked_at,
        stale=snapshot.stale,
        error=snapshot.error,
    )


def _availability_from_report(report: ProviderPreflightReport) -> tuple[str, str | None]:
    if report.ready:
        return "ready", None
    if report.status == "missing":
        details = [
            *report.issues,
            *[
                f"{item.distribution_name} {item.required_version} is missing"
                for item in report.package_statuses
                if item.status == "missing"
            ],
        ]
        return "dependency_missing", " ".join(details) if details else None
    details = [
        *report.issues,
        *[
            f"{item.distribution_name} should be {item.required_version}"
            f"{f' (found {item.installed_version})' if item.installed_version else ''}"
            for item in report.package_statuses
            if item.status == "incompatible"
        ],
    ]
    return "dependency_incompatible", " ".join(details) if details else None


def _implemented_ultralytics_descriptor(
    report: ProviderPreflightReport,
) -> ModelProviderDescriptor:
    availability_status, availability_reason = _availability_from_report(report)
    spec = provider_spec("ultralytics")
    return ModelProviderDescriptor(
        provider_id="ultralytics",
        display_name="Ultralytics YOLO",
        provider_version=spec.provider_version,
        package_version=_package_version("ultralytics"),
        supported_model_families=(
            "Ultralytics YOLO object-detection checkpoints",
            "Ultralytics YOLO segmentation checkpoints",
            "Ultralytics YOLO pose checkpoints",
        ),
        supported_tasks=("detect", "segment", "pose"),
        supported_input_types=("image", "video"),
        supported_output_types=("prediction_proposals", "bounding_boxes", "keypoints"),
        cpu_support=True,
        cuda_support=True,
        supported_precision_modes=("fp32", "amp"),
        video_support=True,
        training_support=True,
        tiling_support=False,
        supported_execution_runtimes=("pytorch",),
        required_packages=_packages_from_preflight(report),
        required_model_files=(".pt", ".pth"),
        code_license="See the installed Ultralytics package license metadata.",
        weight_license="Varies by checkpoint; users must verify checkpoint redistribution terms.",
        memory_recommendations=(
            "CUDA is recommended for larger checkpoints or batch inference jobs.",
            "Current boxed-proposal workflow is validated against the pinned PyTorch runtime only.",
        ),
        known_limitations=(
            "Image review still reduces detection, segmentation, and pose checkpoints to box proposals.",
            "Pose landmarks are currently exposed through the video tracking workflow, not the still-image annotation editor.",
            "The Training workspace currently launches only Ultralytics object-detection runs against immutable dataset versions.",
            "Segmentation or pose training and tuning execution are not yet exposed by ReefVision.",
            "Automatic checkpoint downloads remain disabled; local checkpoints must be selected explicitly.",
        ),
        desktop_packaging_state="base_sidecar_provider",
        clean_machine_verification_state="pinned_stack_preflight_available",
        availability_status=availability_status,
        availability_reason=availability_reason,
        default_registration_purpose="detector",
        registerable=True,
        capabilities=ProviderCapabilityMatrix(
            image_detection=True,
            multi_object_tracking=True,
            training=True,
            validation=True,
            cpu_inference=True,
            cuda_inference=True,
            fp16=True,
            packaged_desktop_operation=True,
        ),
    )


def _implemented_segment_anything_descriptor(
    report: ProviderPreflightReport,
) -> ModelProviderDescriptor:
    availability_status, availability_reason = _availability_from_report(report)
    spec = provider_spec("segment_anything")
    return ModelProviderDescriptor(
        provider_id="segment_anything",
        display_name="Segment Anything / Smart Mask",
        provider_version=spec.provider_version,
        package_version=_package_version("segment-anything"),
        supported_model_families=("Original Segment Anything checkpoints",),
        supported_tasks=("assist_segmentation",),
        supported_input_types=("image", "box_prompt", "brush_prompt", "point_prompt"),
        supported_output_types=("mask_candidate", "bounding_box"),
        cpu_support=True,
        cuda_support=True,
        supported_precision_modes=("fp32",),
        video_support=False,
        training_support=False,
        tiling_support=False,
        supported_execution_runtimes=("pytorch",),
        required_packages=_packages_from_preflight(report),
        required_model_files=(".pt", ".pth"),
        code_license="See the installed Segment Anything package license metadata.",
        weight_license="Varies by checkpoint; users must verify checkpoint redistribution terms.",
        memory_recommendations=(
            "Keep one assist checkpoint loaded at a time on 12 GB desktop GPUs.",
            "Use CPU only for smaller test images or fallback validation.",
        ),
        known_limitations=(
            "Current ReefVision integration supports original SAM image prompting only.",
            "SAM 2, MobileSAM, FastSAM, and video propagation are not yet packaged in ReefVision.",
            "Automatic checkpoint downloads remain disabled; local checkpoints must be selected explicitly.",
        ),
        desktop_packaging_state="base_sidecar_provider",
        clean_machine_verification_state="pinned_stack_preflight_available",
        availability_status=availability_status,
        availability_reason=availability_reason,
        default_registration_purpose="assist",
        registerable=True,
        capabilities=ProviderCapabilityMatrix(
            click_prompting=True,
            box_prompting=True,
            brush_prompting=True,
            cpu_inference=True,
            cuda_inference=True,
            packaged_desktop_operation=True,
        ),
    )


def _blocked_descriptor(
    *,
    provider_id: str,
    display_name: str,
    package_version: str | None,
    supported_model_families: tuple[str, ...],
    supported_tasks: tuple[str, ...],
    supported_input_types: tuple[str, ...],
    supported_output_types: tuple[str, ...],
    cpu_support: bool,
    cuda_support: bool,
    supported_precision_modes: tuple[str, ...],
    video_support: bool,
    training_support: bool,
    tiling_support: bool,
    supported_execution_runtimes: tuple[str, ...],
    required_packages: tuple[ProviderPackageDescriptor, ...],
    required_model_files: tuple[str, ...],
    code_license: str,
    weight_license: str,
    memory_recommendations: tuple[str, ...],
    known_limitations: tuple[str, ...],
    desktop_packaging_state: str,
    clean_machine_verification_state: str,
    availability_reason: str,
    default_registration_purpose: str | None,
    capabilities: ProviderCapabilityMatrix,
) -> ModelProviderDescriptor:
    return ModelProviderDescriptor(
        provider_id=provider_id,
        display_name=display_name,
        provider_version="planned",
        package_version=package_version,
        supported_model_families=supported_model_families,
        supported_tasks=supported_tasks,
        supported_input_types=supported_input_types,
        supported_output_types=supported_output_types,
        cpu_support=cpu_support,
        cuda_support=cuda_support,
        supported_precision_modes=supported_precision_modes,
        video_support=video_support,
        training_support=training_support,
        tiling_support=tiling_support,
        supported_execution_runtimes=supported_execution_runtimes,
        required_packages=required_packages,
        required_model_files=required_model_files,
        code_license=code_license,
        weight_license=weight_license,
        memory_recommendations=memory_recommendations,
        known_limitations=known_limitations,
        desktop_packaging_state=desktop_packaging_state,
        clean_machine_verification_state=clean_machine_verification_state,
        availability_status="not_implemented",
        availability_reason=availability_reason,
        default_registration_purpose=default_registration_purpose,
        registerable=False,
        capabilities=capabilities,
    )


def list_model_providers(
    settings: Settings | None = None,
    *,
    refresh: bool = False,
) -> list[ModelProviderDescriptor]:
    snapshot = get_cached_snapshot(
        f"model_provider_catalog:{_settings_cache_key(settings)}",
        lambda: _list_model_providers_uncached(settings, refresh=refresh),
        ttl_seconds=LIGHTWEIGHT_PROVIDER_CATALOG_TTL_SECONDS,
        refresh=refresh,
    )
    return snapshot.value


def cached_model_provider_catalog(
    settings: Settings | None = None,
    *,
    refresh: bool = False,
) -> CachedSnapshot[list[ModelProviderDescriptor]]:
    return get_cached_snapshot(
        f"model_provider_catalog:{_settings_cache_key(settings)}",
        lambda: _list_model_providers_uncached(settings, refresh=refresh),
        ttl_seconds=LIGHTWEIGHT_PROVIDER_CATALOG_TTL_SECONDS,
        refresh=refresh,
    )


def _list_model_providers_uncached(
    settings: Settings | None = None,
    *,
    refresh: bool = False,
) -> list[ModelProviderDescriptor]:
    reports = _implemented_report_map(settings, refresh=refresh).value
    providers = [
        _implemented_ultralytics_descriptor(reports["ultralytics"]),
        _implemented_segment_anything_descriptor(reports["segment_anything"]),
        _blocked_descriptor(
            provider_id="rt_detr",
            display_name="RT-DETR",
            package_version=_package_version("ultralytics"),
            supported_model_families=("RT-DETR local detection checkpoints",),
            supported_tasks=("detect",),
            supported_input_types=("image",),
            supported_output_types=("prediction_proposals", "bounding_boxes"),
            cpu_support=True,
            cuda_support=True,
            supported_precision_modes=("fp32",),
            video_support=False,
            training_support=False,
            tiling_support=False,
            supported_execution_runtimes=("pytorch",),
            required_packages=_packages_from_requirements(provider_spec("ultralytics").packages),
            required_model_files=(".pt",),
            code_license="See the installed Ultralytics package license metadata.",
            weight_license="Varies by checkpoint; users must verify checkpoint redistribution terms.",
            memory_recommendations=(
                "Use the pinned Ultralytics runtime stack when this provider is implemented.",
            ),
            known_limitations=(
                "ReefVision does not yet register or execute RT-DETR checkpoints through a formal provider.",
            ),
            desktop_packaging_state="not_packaged",
            clean_machine_verification_state="not_verified",
            availability_reason=(
                "RT-DETR is requested in the provider hub but ReefVision does not yet expose a formal RT-DETR registration or inference path."
            ),
            default_registration_purpose="detector",
            capabilities=ProviderCapabilityMatrix(
                image_detection=True,
                cpu_inference=True,
                cuda_inference=True,
            ),
        ),
        _blocked_descriptor(
            provider_id="grounding_dino",
            display_name="Grounding DINO",
            package_version=_package_version("transformers"),
            supported_model_families=("Grounding DINO text-conditioned detectors",),
            supported_tasks=("open_vocabulary_detect", "phrase_grounding"),
            supported_input_types=("image", "text_prompt"),
            supported_output_types=("prediction_proposals", "bounding_boxes"),
            cpu_support=True,
            cuda_support=True,
            supported_precision_modes=("fp32", "fp16"),
            video_support=False,
            training_support=False,
            tiling_support=False,
            supported_execution_runtimes=("pytorch",),
            required_packages=_packages_not_yet_pinned("transformers", "accelerate", "safetensors"),
            required_model_files=(".safetensors", ".bin"),
            code_license="Would depend on the pinned Transformers implementation and package metadata.",
            weight_license="Varies by checkpoint; users must verify checkpoint redistribution terms.",
            memory_recommendations=(
                "Text-grounding checkpoints should be isolated behind an optional provider pack.",
            ),
            known_limitations=(
                "Transformers is not pinned or installed in the current desktop provider stack.",
                "No Grounding DINO provider implementation exists in ReefVision yet.",
            ),
            desktop_packaging_state="optional_pack_required",
            clean_machine_verification_state="not_verified",
            availability_reason=(
                "Grounding DINO is not implemented in ReefVision and the compatible Transformers stack is not yet pinned for desktop packaging."
            ),
            default_registration_purpose="detector",
            capabilities=ProviderCapabilityMatrix(
                image_detection=True,
                text_prompt_detection=True,
                cpu_inference=True,
                cuda_inference=True,
            ),
        ),
        _blocked_descriptor(
            provider_id="owlv2",
            display_name="OWLv2",
            package_version=_package_version("transformers"),
            supported_model_families=("OWLv2 open-vocabulary detectors",),
            supported_tasks=("open_vocabulary_detect", "example_guided_detect"),
            supported_input_types=("image", "text_prompt", "image_example"),
            supported_output_types=("prediction_proposals", "bounding_boxes"),
            cpu_support=True,
            cuda_support=True,
            supported_precision_modes=("fp32", "fp16"),
            video_support=False,
            training_support=False,
            tiling_support=False,
            supported_execution_runtimes=("pytorch",),
            required_packages=_packages_not_yet_pinned("transformers", "accelerate", "safetensors"),
            required_model_files=(".safetensors", ".bin"),
            code_license="Would depend on the pinned Transformers implementation and package metadata.",
            weight_license="Varies by checkpoint; users must verify checkpoint redistribution terms.",
            memory_recommendations=(
                "Use one large vision-language checkpoint at a time on 12 GB desktop GPUs.",
            ),
            known_limitations=(
                "OWLv2 is not implemented in ReefVision.",
                "Image-guided search and prompt provenance storage are not yet wired into the review workflow.",
            ),
            desktop_packaging_state="optional_pack_required",
            clean_machine_verification_state="not_verified",
            availability_reason=(
                "OWLv2 is not implemented and the required Transformers stack is not yet pinned or packaged in ReefVision."
            ),
            default_registration_purpose="detector",
            capabilities=ProviderCapabilityMatrix(
                image_detection=True,
                text_prompt_detection=True,
                image_example_detection=True,
                cpu_inference=True,
                cuda_inference=True,
            ),
        ),
        _blocked_descriptor(
            provider_id="florence2",
            display_name="Florence-2",
            package_version=_package_version("transformers"),
            supported_model_families=("Florence-2 vision-language checkpoints",),
            supported_tasks=("open_vocabulary_detect", "phrase_grounding", "caption"),
            supported_input_types=("image", "text_prompt"),
            supported_output_types=("prediction_proposals", "bounding_boxes", "text"),
            cpu_support=True,
            cuda_support=True,
            supported_precision_modes=("fp32", "fp16"),
            video_support=False,
            training_support=False,
            tiling_support=False,
            supported_execution_runtimes=("pytorch",),
            required_packages=_packages_not_yet_pinned("transformers", "accelerate", "safetensors"),
            required_model_files=(".safetensors", ".bin"),
            code_license="Would depend on the pinned Transformers implementation and package metadata.",
            weight_license="Varies by checkpoint; users must verify checkpoint redistribution terms.",
            memory_recommendations=(
                "Treat Florence-2 as an optional provider-pack candidate until packaging is validated.",
            ),
            known_limitations=(
                "Florence-2 is not implemented in ReefVision.",
                "The current desktop stack does not include a pinned safe Florence-2 dependency path.",
            ),
            desktop_packaging_state="optional_pack_required",
            clean_machine_verification_state="not_verified",
            availability_reason=(
                "Florence-2 is not implemented and ReefVision does not yet ship a pinned, reviewed native implementation for the desktop build."
            ),
            default_registration_purpose="detector",
            capabilities=ProviderCapabilityMatrix(
                image_detection=True,
                text_prompt_detection=True,
                cpu_inference=True,
                cuda_inference=True,
            ),
        ),
        _blocked_descriptor(
            provider_id="sam2",
            display_name="SAM 2",
            package_version=None,
            supported_model_families=("SAM 2 image and video checkpoints",),
            supported_tasks=("assist_segmentation", "video_propagation"),
            supported_input_types=("image", "box_prompt", "point_prompt", "video"),
            supported_output_types=("mask_candidate", "mask_proposals"),
            cpu_support=True,
            cuda_support=True,
            supported_precision_modes=("fp32", "fp16"),
            video_support=True,
            training_support=False,
            tiling_support=False,
            supported_execution_runtimes=("pytorch",),
            required_packages=_packages_not_yet_pinned("torch", "torchvision"),
            required_model_files=(".pt", ".pth"),
            code_license="Would depend on the selected SAM 2 package implementation.",
            weight_license="Varies by checkpoint; users must verify checkpoint redistribution terms.",
            memory_recommendations=(
                "SAM 2 video propagation needs explicit Windows packaging validation before desktop claims.",
            ),
            known_limitations=(
                "SAM 2 image and video workflows are not implemented in ReefVision.",
            ),
            desktop_packaging_state="blocked_pending_windows_validation",
            clean_machine_verification_state="not_verified",
            availability_reason=(
                "SAM 2 is not yet implemented or validated for ReefVision's packaged Windows desktop environment."
            ),
            default_registration_purpose="assist",
            capabilities=ProviderCapabilityMatrix(
                click_prompting=True,
                box_prompting=True,
                video_propagation=True,
                cpu_inference=True,
                cuda_inference=True,
            ),
        ),
        _blocked_descriptor(
            provider_id="mobilesam",
            display_name="MobileSAM",
            package_version=None,
            supported_model_families=("MobileSAM checkpoints",),
            supported_tasks=("assist_segmentation",),
            supported_input_types=("image", "box_prompt", "point_prompt"),
            supported_output_types=("mask_candidate", "bounding_box"),
            cpu_support=True,
            cuda_support=True,
            supported_precision_modes=("fp32",),
            video_support=False,
            training_support=False,
            tiling_support=False,
            supported_execution_runtimes=("pytorch",),
            required_packages=_packages_not_yet_pinned("torch", "torchvision"),
            required_model_files=(".pt", ".pth"),
            code_license="Would depend on the selected MobileSAM package implementation.",
            weight_license="Varies by checkpoint; users must verify checkpoint redistribution terms.",
            memory_recommendations=(
                "A lighter assist model belongs in an optional provider pack until it is pinned and validated.",
            ),
            known_limitations=("MobileSAM is not implemented in ReefVision.",),
            desktop_packaging_state="optional_pack_required",
            clean_machine_verification_state="not_verified",
            availability_reason=(
                "MobileSAM is not implemented and no pinned MobileSAM dependency path exists in the current ReefVision build."
            ),
            default_registration_purpose="assist",
            capabilities=ProviderCapabilityMatrix(
                click_prompting=True,
                box_prompting=True,
                cpu_inference=True,
                cuda_inference=True,
            ),
        ),
        _blocked_descriptor(
            provider_id="fastsam",
            display_name="FastSAM",
            package_version=_package_version("ultralytics"),
            supported_model_families=("FastSAM checkpoints",),
            supported_tasks=("assist_segmentation",),
            supported_input_types=("image", "box_prompt", "point_prompt"),
            supported_output_types=("mask_candidate", "bounding_box"),
            cpu_support=True,
            cuda_support=True,
            supported_precision_modes=("fp32",),
            video_support=False,
            training_support=False,
            tiling_support=False,
            supported_execution_runtimes=("pytorch",),
            required_packages=_packages_from_requirements(provider_spec("ultralytics").packages),
            required_model_files=(".pt", ".pth"),
            code_license="See the installed Ultralytics package license metadata.",
            weight_license="Varies by checkpoint; users must verify checkpoint redistribution terms.",
            memory_recommendations=(
                "FastSAM needs a dedicated ReefVision provider implementation before it can be exposed.",
            ),
            known_limitations=("FastSAM is not implemented in ReefVision.",),
            desktop_packaging_state="not_packaged",
            clean_machine_verification_state="not_verified",
            availability_reason=(
                "FastSAM is not yet integrated into ReefVision's assist runtime or frontend workflows."
            ),
            default_registration_purpose="assist",
            capabilities=ProviderCapabilityMatrix(
                click_prompting=True,
                box_prompting=True,
                cpu_inference=True,
                cuda_inference=True,
            ),
        ),
        _blocked_descriptor(
            provider_id="reefvision_unet",
            display_name="ReefVision U-Net",
            package_version=None,
            supported_model_families=("Custom ReefVision U-Net checkpoints",),
            supported_tasks=("semantic_segment",),
            supported_input_types=("image",),
            supported_output_types=("semantic_mask", "proposals"),
            cpu_support=True,
            cuda_support=True,
            supported_precision_modes=("fp32",),
            video_support=False,
            training_support=False,
            tiling_support=False,
            supported_execution_runtimes=("pytorch", "onnxruntime"),
            required_packages=_packages_not_yet_pinned("torch", "onnxruntime"),
            required_model_files=(".pt", ".pth", ".onnx"),
            code_license="Would be defined by ReefVision once a U-Net provider is added.",
            weight_license="Varies by checkpoint; users must verify checkpoint redistribution terms.",
            memory_recommendations=(
                "Semantic segmentation checkpoints need explicit architecture metadata before safe loading.",
            ),
            known_limitations=(
                "No ReefVision U-Net implementation or checkpoint validator exists in the current repository.",
            ),
            desktop_packaging_state="not_packaged",
            clean_machine_verification_state="not_verified",
            availability_reason=(
                "The repository does not currently contain a formal ReefVision U-Net provider implementation."
            ),
            default_registration_purpose=None,
            capabilities=ProviderCapabilityMatrix(
                image_semantic_segmentation=True,
                cpu_inference=True,
                cuda_inference=True,
            ),
        ),
        _blocked_descriptor(
            provider_id="bytetrack",
            display_name="ByteTrack",
            package_version=_package_version("lap"),
            supported_model_families=("ByteTrack multi-object trackers",),
            supported_tasks=("track",),
            supported_input_types=("video", "detections"),
            supported_output_types=("tracks", "track_proposals"),
            cpu_support=True,
            cuda_support=True,
            supported_precision_modes=("fp32",),
            video_support=True,
            training_support=False,
            tiling_support=False,
            supported_execution_runtimes=("pytorch",),
            required_packages=_packages_not_yet_pinned("lap"),
            required_model_files=(),
            code_license="Would depend on the selected ByteTrack implementation.",
            weight_license="Trackers do not ship universal checkpoint licenses in ReefVision yet.",
            memory_recommendations=(
                "Trackers should remain separate from detector registration and loading.",
            ),
            known_limitations=(
                "ByteTrack is not exposed as a formal ReefVision tracking provider.",
            ),
            desktop_packaging_state="not_packaged",
            clean_machine_verification_state="not_verified",
            availability_reason=(
                "ByteTrack is not implemented as a standalone ReefVision tracking provider even though lap is pinned for future compatibility."
            ),
            default_registration_purpose=None,
            capabilities=ProviderCapabilityMatrix(
                multi_object_tracking=True,
                cpu_inference=True,
                cuda_inference=True,
            ),
        ),
        _blocked_descriptor(
            provider_id="botsort",
            display_name="BoT-SORT",
            package_version=_package_version("lap"),
            supported_model_families=("BoT-SORT multi-object trackers",),
            supported_tasks=("track",),
            supported_input_types=("video", "detections"),
            supported_output_types=("tracks", "track_proposals"),
            cpu_support=True,
            cuda_support=True,
            supported_precision_modes=("fp32",),
            video_support=True,
            training_support=False,
            tiling_support=False,
            supported_execution_runtimes=("pytorch",),
            required_packages=_packages_not_yet_pinned("lap"),
            required_model_files=(),
            code_license="Would depend on the selected BoT-SORT implementation.",
            weight_license="Trackers do not ship universal checkpoint licenses in ReefVision yet.",
            memory_recommendations=(
                "Trackers should remain separate from detector registration and loading.",
            ),
            known_limitations=(
                "BoT-SORT is not exposed as a formal ReefVision tracking provider.",
            ),
            desktop_packaging_state="not_packaged",
            clean_machine_verification_state="not_verified",
            availability_reason=(
                "BoT-SORT is not implemented as a standalone ReefVision tracking provider."
            ),
            default_registration_purpose=None,
            capabilities=ProviderCapabilityMatrix(
                multi_object_tracking=True,
                cpu_inference=True,
                cuda_inference=True,
            ),
        ),
    ]
    return providers


def get_model_provider(
    provider_id: str, settings: Settings | None = None
) -> ModelProviderDescriptor:
    for provider in list_model_providers(settings):
        if provider.provider_id == provider_id:
            return provider
    raise NotFoundError("Model provider not found")


def get_model_provider_capabilities(
    provider_id: str, settings: Settings | None = None
) -> ProviderCapabilityMatrix:
    return get_model_provider(provider_id, settings).capabilities


def runtime_provider_statuses() -> list[RuntimeProviderStatus]:
    return cached_runtime_provider_statuses().value


def cached_runtime_provider_statuses(
    *,
    refresh: bool = False,
) -> CachedSnapshot[list[RuntimeProviderStatus]]:
    return get_cached_snapshot(
        "runtime_provider_statuses",
        _runtime_provider_statuses_uncached,
        ttl_seconds=RUNTIME_STATUS_TTL_SECONDS,
        refresh=refresh,
    )


def _runtime_provider_statuses_uncached() -> list[RuntimeProviderStatus]:
    statuses: list[RuntimeProviderStatus] = []

    torch_version = _package_version("torch")
    torch_available = torch_version is not None
    statuses.append(
        RuntimeProviderStatus(
            runtime_id="pytorch",
            display_name="PyTorch",
            package_name="torch",
            package_version=torch_version,
            available=torch_available,
            status="ready" if torch_available else "missing",
            supports_cpu=True,
            supports_cuda=torch_available,
            notes=(
                "Reference runtime for the implemented ReefVision providers.",
                "Live CUDA verification is deferred until launch-time preflight.",
            ),
        )
    )

    statuses.append(
        RuntimeProviderStatus(
            runtime_id="torchscript",
            display_name="TorchScript",
            package_name="torch",
            package_version=torch_version,
            available=torch_available,
            status="ready" if torch_available else "missing",
            supports_cpu=True,
            supports_cuda=torch_available,
            notes=(
                "Runtime metadata is surfaced for future validated exports; arbitrary TorchScript files are not yet registered in ReefVision.",
            ),
        )
    )

    for runtime_id, display_name, package_name, cpu_support, cuda_support, note in (
        (
            "onnxruntime",
            "ONNX Runtime",
            "onnxruntime",
            True,
            True,
            "No ONNX Runtime model registration or execution path exists in ReefVision yet.",
        ),
        (
            "openvino",
            "OpenVINO",
            "openvino",
            True,
            False,
            "OpenVINO is not yet pinned or packaged in the ReefVision desktop build.",
        ),
        (
            "tensorrt",
            "TensorRT",
            "tensorrt",
            False,
            True,
            "TensorRT remains unavailable until compatible engine validation and NVIDIA packaging support are added.",
        ),
    ):
        installed_version = _package_version(package_name)
        statuses.append(
            RuntimeProviderStatus(
                runtime_id=runtime_id,
                display_name=display_name,
                package_name=package_name,
                package_version=installed_version,
                available=installed_version is not None,
                status="ready" if installed_version is not None else "missing",
                supports_cpu=cpu_support,
                supports_cuda=cuda_support,
                notes=(note,),
            )
        )

    return statuses


def provider_for_registration(
    purpose: str,
    *,
    provider_name: str | None = None,
    settings: Settings | None = None,
) -> DetectionProvider | AnnotationAssistProvider:
    normalized = (provider_name or "").strip().lower()
    if purpose == "detector":
        if normalized in {"", "ultralytics"}:
            descriptor = get_model_provider("ultralytics", settings)
            if descriptor.availability_status not in {
                "ready",
                "dependency_missing",
                "dependency_incompatible",
            }:
                raise ValidationError("Ultralytics registration is not available")
            return UltralyticsDetectionProvider()
        raise ValidationError(f"Unsupported detector provider: {provider_name}")
    if purpose == "assist":
        if normalized in {"", "segment_anything"}:
            descriptor = get_model_provider("segment_anything", settings)
            if descriptor.availability_status not in {
                "ready",
                "dependency_missing",
                "dependency_incompatible",
            }:
                raise ValidationError("Segment Anything registration is not available")
            return SegmentAnythingAssistProvider()
        raise ValidationError(f"Unsupported assist provider: {provider_name}")
    raise ValidationError("Unknown model purpose")


def detection_provider_for_name(provider_name: str) -> DetectionProvider:
    normalized = provider_name.strip().lower()
    if normalized == "ultralytics":
        return UltralyticsDetectionProvider()
    raise ValidationError(f"Unsupported detection provider: {provider_name}")


def assist_provider_for_name(provider_name: str) -> AnnotationAssistProvider:
    normalized = provider_name.strip().lower()
    if normalized == "segment_anything":
        return SegmentAnythingAssistProvider()
    raise ValidationError(f"Unsupported assist provider: {provider_name}")


def _settings_cache_key(settings: Settings | None) -> str:
    if settings is None:
        return "default"
    return str(settings.resolved_data_dir)

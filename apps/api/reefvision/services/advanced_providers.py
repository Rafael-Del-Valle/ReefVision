"""Advanced provider manifests and fail-closed execution preflight."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ModelRegistration, Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.provider_hub import list_model_providers
from reefvision.schemas.advanced_providers import (
    AdvancedProviderManifestResponse,
    AdvancedProviderPreflightRequest,
    AdvancedProviderPreflightResponse,
)


@dataclass(frozen=True, slots=True)
class _AdvancedProviderProfile:
    provider_id: str
    display_name: str
    execution_supported: bool
    supported_tasks: tuple[str, ...]
    prompt_fields_by_task: dict[str, tuple[str, ...]]
    output_contracts_by_task: dict[str, tuple[str, ...]]
    required_model_extensions: tuple[str, ...]
    required_packages: tuple[str, ...]
    recommended_devices: tuple[str, ...]
    known_limitations: tuple[str, ...]
    integration_notes: tuple[str, ...]
    model_required: bool = True
    expected_model_purpose: str | None = None


_PROFILES: tuple[_AdvancedProviderProfile, ...] = (
    _AdvancedProviderProfile(
        provider_id="segment_anything",
        display_name="Segment Anything / Smart Mask",
        execution_supported=True,
        supported_tasks=("assist_segmentation",),
        prompt_fields_by_task={"assist_segmentation": ("image_id", "prompt_type")},
        output_contracts_by_task={"assist_segmentation": ("mask_candidate", "bounding_box")},
        required_model_extensions=(".pt", ".pth"),
        required_packages=("segment-anything", "torch", "torchvision"),
        recommended_devices=("cuda", "cpu"),
        known_limitations=(
            "Current implementation uses original SAM image embeddings and does not propagate masks through video.",
        ),
        integration_notes=(
            "prompt_type must identify box, click, or brush prompting; the prompt geometry remains in the existing assist-session request.",
        ),
        expected_model_purpose="assist",
    ),
    _AdvancedProviderProfile(
        provider_id="grounding_dino",
        display_name="Grounding DINO",
        execution_supported=False,
        supported_tasks=("open_vocabulary_detect", "phrase_grounding"),
        prompt_fields_by_task={
            "open_vocabulary_detect": ("image_id", "text_prompts", "confidence"),
            "phrase_grounding": ("image_id", "text_prompts", "confidence"),
        },
        output_contracts_by_task={
            "open_vocabulary_detect": ("prediction_proposals", "bounding_boxes", "phrases"),
            "phrase_grounding": ("prediction_proposals", "bounding_boxes", "phrases"),
        },
        required_model_extensions=(".safetensors", ".bin"),
        required_packages=("transformers", "accelerate", "safetensors"),
        recommended_devices=("cuda", "cpu"),
        known_limitations=(
            "No pinned Transformers provider pack or reviewed adapter is currently shipped.",
        ),
        integration_notes=(
            "Future results must enter the normal prediction-proposal review flow with prompt and checkpoint provenance.",
        ),
    ),
    _AdvancedProviderProfile(
        provider_id="owlv2",
        display_name="OWLv2",
        execution_supported=False,
        supported_tasks=("open_vocabulary_detect", "example_guided_detect"),
        prompt_fields_by_task={
            "open_vocabulary_detect": ("image_id", "text_prompts", "confidence"),
            "example_guided_detect": ("image_id", "example_image_id", "confidence"),
        },
        output_contracts_by_task={
            "open_vocabulary_detect": ("prediction_proposals", "bounding_boxes"),
            "example_guided_detect": ("prediction_proposals", "bounding_boxes"),
        },
        required_model_extensions=(".safetensors", ".bin"),
        required_packages=("transformers", "accelerate", "safetensors"),
        recommended_devices=("cuda", "cpu"),
        known_limitations=("No ReefVision adapter or pinned desktop package exists yet.",),
        integration_notes=(
            "Example-guided requests must preserve the example image checksum in proposal provenance.",
        ),
    ),
    _AdvancedProviderProfile(
        provider_id="florence2",
        display_name="Florence-2",
        execution_supported=False,
        supported_tasks=("open_vocabulary_detect", "phrase_grounding", "caption"),
        prompt_fields_by_task={
            "open_vocabulary_detect": ("image_id", "text_prompts"),
            "phrase_grounding": ("image_id", "text_prompts"),
            "caption": ("image_id",),
        },
        output_contracts_by_task={
            "open_vocabulary_detect": ("prediction_proposals", "bounding_boxes", "text"),
            "phrase_grounding": ("prediction_proposals", "bounding_boxes", "text"),
            "caption": ("text",),
        },
        required_model_extensions=(".safetensors", ".bin"),
        required_packages=("transformers", "accelerate", "safetensors"),
        recommended_devices=("cuda", "cpu"),
        known_limitations=("No pinned or security-reviewed Florence-2 runtime exists yet.",),
        integration_notes=(
            "Generated text must remain advisory and must never alter class labels automatically.",
        ),
    ),
    _AdvancedProviderProfile(
        provider_id="sam2",
        display_name="SAM 2",
        execution_supported=True,
        supported_tasks=("assist_segmentation",),
        prompt_fields_by_task={"assist_segmentation": ("image_id", "prompt_type")},
        output_contracts_by_task={
            "assist_segmentation": ("mask_candidate", "bounding_box")
        },
        required_model_extensions=(".zip",),
        required_packages=("transformers", "torch", "safetensors"),
        recommended_devices=("cuda", "cpu"),
        known_limitations=(
            "This milestone enables SAM2 image prompting only; SAM2 video propagation remains disabled until its long-video memory and cancellation behavior are validated.",
            "The provider accepts local Transformers-style ReefVision ZIP bundles and does not download weights automatically.",
        ),
        integration_notes=(
            "SAM2 image prompts use the existing ReefVision Prompt Assist session, edit, accept, and mask-persistence workflow.",
        ),
        expected_model_purpose="assist",
    ),
    _AdvancedProviderProfile(
        provider_id="mobilesam",
        display_name="MobileSAM",
        execution_supported=False,
        supported_tasks=("assist_segmentation",),
        prompt_fields_by_task={"assist_segmentation": ("image_id", "prompt_type")},
        output_contracts_by_task={"assist_segmentation": ("mask_candidate",)},
        required_model_extensions=(".pt", ".pth"),
        required_packages=("torch", "torchvision"),
        recommended_devices=("cpu", "cuda"),
        known_limitations=("No pinned package or checkpoint inspector exists yet.",),
        integration_notes=(
            "The adapter should implement the same image-prompt contract as original SAM.",
        ),
    ),
    _AdvancedProviderProfile(
        provider_id="fastsam",
        display_name="FastSAM",
        execution_supported=False,
        supported_tasks=("assist_segmentation",),
        prompt_fields_by_task={"assist_segmentation": ("image_id", "prompt_type")},
        output_contracts_by_task={"assist_segmentation": ("mask_candidate", "bounding_box")},
        required_model_extensions=(".pt",),
        required_packages=("ultralytics",),
        recommended_devices=("cuda", "cpu"),
        known_limitations=(
            "The installed Ultralytics package is present, but ReefVision has no reviewed FastSAM adapter.",
        ),
        integration_notes=(
            "Do not route FastSAM through the detector provider without task-specific result validation.",
        ),
    ),
    _AdvancedProviderProfile(
        provider_id="depth_anything_v2",
        display_name="Depth Anything V2",
        execution_supported=True,
        supported_tasks=("relative_depth",),
        prompt_fields_by_task={"relative_depth": ("image_id",)},
        output_contracts_by_task={
            "relative_depth": ("relative_depth_array", "depth_preview", "value_range")
        },
        required_model_extensions=(".zip",),
        required_packages=("transformers", "torch", "numpy", "safetensors"),
        recommended_devices=("cuda", "cpu"),
        known_limitations=(
            "Predictions are relative depth, not calibrated metric distance.",
            "Depth values must not be interpreted as meters or converted to surface area without a separate calibrated geometry model.",
            "The provider accepts local Transformers-style ReefVision ZIP bundles and does not download weights automatically.",
        ),
        integration_notes=(
            "Depth outputs are stored as immutable float arrays plus a 16-bit preview with source-image and model provenance.",
        ),
        expected_model_purpose="depth",
    ),
)

_MANAGED_TRANSFORMERS_PROVIDERS = {"sam2", "depth_anything_v2"}


def _installed_version(distribution_name: str) -> str | None:
    try:
        return version(distribution_name)
    except PackageNotFoundError:
        return None


def _managed_runtime_status(provider_id: str) -> tuple[str, str | None]:
    if provider_id not in _MANAGED_TRANSFORMERS_PROVIDERS:
        return "not_managed", None
    required = ["transformers", "torch"]
    if provider_id == "depth_anything_v2":
        required.append("numpy")
    missing = [item for item in required if _installed_version(item) is None]
    if missing:
        return (
            "dependency_missing",
            "Install the optional advanced provider dependencies: " + ", ".join(missing),
        )
    return "ready", None


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


class AdvancedProviderService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    @staticmethod
    def _profile(provider_id: str) -> _AdvancedProviderProfile:
        profile = next((item for item in _PROFILES if item.provider_id == provider_id), None)
        if profile is None:
            raise NotFoundError("Advanced provider manifest not found")
        return profile

    def manifests(self) -> list[AdvancedProviderManifestResponse]:
        descriptors = {
            item.provider_id: item for item in list_model_providers(self.settings)
        }
        results: list[AdvancedProviderManifestResponse] = []
        for profile in _PROFILES:
            if profile.provider_id in _MANAGED_TRANSFORMERS_PROVIDERS:
                maturity, _ = _managed_runtime_status(profile.provider_id)
            else:
                descriptor = descriptors.get(profile.provider_id)
                maturity = descriptor.availability_status if descriptor else "not_registered"
            results.append(
                AdvancedProviderManifestResponse(
                    provider_id=profile.provider_id,
                    display_name=profile.display_name,
                    maturity=maturity,
                    execution_supported=profile.execution_supported,
                    supported_tasks=list(profile.supported_tasks),
                    prompt_fields_by_task={
                        key: list(value) for key, value in profile.prompt_fields_by_task.items()
                    },
                    output_contracts_by_task={
                        key: list(value) for key, value in profile.output_contracts_by_task.items()
                    },
                    required_model_extensions=list(profile.required_model_extensions),
                    required_packages=list(profile.required_packages),
                    recommended_devices=list(profile.recommended_devices),
                    known_limitations=list(profile.known_limitations),
                    integration_notes=list(profile.integration_notes),
                )
            )
        return results

    def preflight(
        self,
        project_id: str,
        provider_id: str,
        request: AdvancedProviderPreflightRequest,
    ) -> AdvancedProviderPreflightResponse:
        self._project(project_id)
        profile = self._profile(provider_id)
        if request.task not in profile.supported_tasks:
            raise ValidationError("The selected provider does not declare the requested task")

        blockers: list[str] = []
        warnings: list[str] = list(profile.known_limitations)
        if provider_id in _MANAGED_TRANSFORMERS_PROVIDERS:
            availability_status, availability_reason = _managed_runtime_status(provider_id)
            if availability_status != "ready" and availability_reason:
                blockers.append(availability_reason)
        else:
            descriptors = {
                item.provider_id: item
                for item in list_model_providers(self.settings, refresh=True)
            }
            descriptor = descriptors.get(provider_id)
            availability_status = (
                descriptor.availability_status if descriptor else "not_registered"
            )
            if descriptor is None:
                blockers.append("The provider is not registered in the main provider hub")
            elif descriptor.availability_status != "ready":
                blockers.append(
                    descriptor.availability_reason
                    or f"Provider availability is {descriptor.availability_status}"
                )
        if not profile.execution_supported:
            blockers.append("No reviewed ReefVision execution adapter is enabled for this provider")

        required_fields = list(profile.prompt_fields_by_task[request.task])
        provided_fields = sorted(request.prompt_fields)
        missing_fields = [
            field
            for field in required_fields
            if field not in request.prompt_fields
            or request.prompt_fields[field] in (None, "", [], {})
        ]
        if missing_fields:
            blockers.append("Missing required prompt fields: " + ", ".join(missing_fields))

        selected_model_id: str | None = None
        if profile.model_required:
            if request.model_id is None:
                blockers.append("Select a registered model checkpoint for this provider")
            else:
                model = self.session.get(ModelRegistration, request.model_id)
                if model is None or model.project_id != project_id:
                    blockers.append("Selected model does not belong to this project")
                elif model.provider_name != provider_id:
                    blockers.append(
                        f"Selected model is registered for provider {model.provider_name}, not {provider_id}"
                    )
                elif (
                    profile.expected_model_purpose is not None
                    and model.purpose != profile.expected_model_purpose
                ):
                    blockers.append(
                        f"Selected model purpose is {model.purpose}, not {profile.expected_model_purpose}"
                    )
                else:
                    selected_model_id = model.id

        normalized_device = request.device.strip().casefold()
        if normalized_device not in {"auto", "cpu", "cuda", "cuda:0", "0"}:
            blockers.append("Supported devices are auto, cpu, and cuda")
        elif normalized_device in {"cuda", "cuda:0", "0"} and not _cuda_available():
            blockers.append("CUDA was requested but Torch does not report an available CUDA device")
        elif normalized_device == "auto" and not _cuda_available():
            warnings.append("CUDA is unavailable; this provider will fall back to CPU")
        if normalized_device == "cpu" and "cpu" not in profile.recommended_devices:
            warnings.append("CPU execution is not recommended for this provider profile")

        return AdvancedProviderPreflightResponse(
            provider_id=provider_id,
            task=request.task,
            ready=not blockers,
            execution_supported=profile.execution_supported,
            availability_status=availability_status,
            blockers=blockers,
            warnings=warnings,
            required_prompt_fields=required_fields,
            provided_prompt_fields=provided_fields,
            missing_prompt_fields=missing_fields,
            output_contract=list(profile.output_contracts_by_task[request.task]),
            selected_model_id=selected_model_id,
            selected_device=request.device,
        )

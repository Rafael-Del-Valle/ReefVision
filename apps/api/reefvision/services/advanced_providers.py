"""Advanced provider manifests and fail-closed execution preflight."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
from reefvision.services.advanced_provider_execution import (
    PROVIDER_LAB_EXECUTION_IDS,
    optional_provider_runtime_status,
)

AdvancedProviderExecutionSurface = Literal[
    "provider_lab",
    "existing_workflow",
    "blocked",
]


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
            "Current implementation uses original SAM image embeddings and does not "
            "propagate masks through video.",
        ),
        integration_notes=(
            "prompt_type must identify box, click, or brush prompting; the prompt geometry "
            "remains in the existing assist-session request.",
        ),
    ),
    _AdvancedProviderProfile(
        provider_id="grounding_dino",
        display_name="Grounding DINO",
        execution_supported=True,
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
        required_packages=("transformers", "torch", "safetensors"),
        recommended_devices=("cuda", "cpu"),
        known_limitations=(
            "The pinned model is downloaded only after explicit user approval "
            "and remains local to ReefVision application data.",
        ),
        integration_notes=(
            "Results are advisory proposals and preserve prompt/model provenance for human review.",
        ),
        model_required=False,
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
            "Example-guided requests must preserve the example image checksum in proposal "
            "provenance.",
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
        prompt_fields_by_task={
            "assist_segmentation": ("image_id", "box"),
        },
        output_contracts_by_task={
            "assist_segmentation": ("prediction_proposals", "mask_candidate"),
            "video_propagation": ("frame_mask_proposals", "object_ids"),
        },
        required_model_extensions=(".safetensors",),
        required_packages=("transformers", "torch", "torchvision", "safetensors"),
        recommended_devices=("cuda", "cpu"),
        known_limitations=(
            "Image prompting is enabled through the pinned Transformers runtime; "
            "long-video SAM 2 propagation remains a separate acceptance target.",
        ),
        integration_notes=(
            "Image masks remain editable proposals and require researcher "
            "review before acceptance.",
        ),
        model_required=False,
    ),
    _AdvancedProviderProfile(
        provider_id="smolvlm",
        display_name="SmolVLM 256M Instruct",
        execution_supported=True,
        supported_tasks=("caption", "visual_question"),
        prompt_fields_by_task={
            "caption": ("image_id", "prompt"),
            "visual_question": ("image_id", "prompt"),
        },
        output_contracts_by_task={
            "caption": ("text",),
            "visual_question": ("text",),
        },
        required_model_extensions=(".safetensors",),
        required_packages=("transformers", "torch", "safetensors"),
        recommended_devices=("cuda", "cpu"),
        known_limitations=(
            "Generated text is advisory and is never converted into verified labels automatically.",
        ),
        integration_notes=(
            "Use the VLM for descriptions and questions, not unattended scientific conclusions.",
        ),
        model_required=False,
    ),
    _AdvancedProviderProfile(
        provider_id="nnunet",
        display_name="nnU-Net v2",
        execution_supported=True,
        supported_tasks=("semantic_segment",),
        prompt_fields_by_task={
            "semantic_segment": (
                "input_folder",
                "output_folder",
                "dataset",
                "configuration",
            )
        },
        output_contracts_by_task={"semantic_segment": ("prediction_folder",)},
        required_model_extensions=(),
        required_packages=("nnunetv2",),
        recommended_devices=("cuda", "cpu"),
        known_limitations=(
            "nnU-Net remains an optional provider pack and requires its "
            "upstream data/result environment variables.",
        ),
        integration_notes=(
            "Predicted segmentation files remain external artifacts until "
            "reviewed and imported into ReefVision.",
        ),
        model_required=False,
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
            "The installed Ultralytics package is present, but ReefVision has no reviewed "
            "FastSAM adapter.",
        ),
        integration_notes=(
            "Do not route FastSAM through the detector provider without task-specific result "
            "validation.",
        ),
    ),
    _AdvancedProviderProfile(
        provider_id="depth_anything_v2",
        display_name="Depth Anything V2",
        execution_supported=False,
        supported_tasks=("relative_depth",),
        prompt_fields_by_task={"relative_depth": ("image_id",)},
        output_contracts_by_task={
            "relative_depth": ("relative_depth_array", "depth_preview", "value_range")
        },
        required_model_extensions=(".pth", ".safetensors"),
        required_packages=("torch", "torchvision", "transformers"),
        recommended_devices=("cuda", "cpu"),
        known_limitations=(
            "Predictions are relative depth, not calibrated metric distance.",
            "No ReefVision checkpoint inspector, tiling policy, or packaged adapter exists yet.",
        ),
        integration_notes=(
            "Depth outputs should be stored as immutable float arrays with source-image checksum "
            "and model provenance.",
            "Depth must not be converted to coral surface area until a separate calibration and "
            "geometry model is selected.",
        ),
    ),
)


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
    def _execution_surface(
        provider_id: str,
    ) -> AdvancedProviderExecutionSurface:
        if provider_id in PROVIDER_LAB_EXECUTION_IDS:
            return "provider_lab"
        if provider_id == "segment_anything":
            return "existing_workflow"
        return "blocked"

    @staticmethod
    def _profile(provider_id: str) -> _AdvancedProviderProfile:
        profile = next((item for item in _PROFILES if item.provider_id == provider_id), None)
        if profile is None:
            raise NotFoundError("Advanced provider manifest not found")
        return profile

    def manifests(self) -> list[AdvancedProviderManifestResponse]:
        descriptors = {item.provider_id: item for item in list_model_providers(self.settings)}
        results: list[AdvancedProviderManifestResponse] = []
        for profile in _PROFILES:
            descriptor = descriptors.get(profile.provider_id)
            if profile.provider_id in {"grounding_dino", "sam2", "smolvlm", "nnunet"}:
                runtime = optional_provider_runtime_status(self.settings, profile.provider_id)
                maturity = "ready" if runtime.get("ready") else "available_on_demand"
            else:
                maturity = descriptor.availability_status if descriptor else "not_registered"
            results.append(
                AdvancedProviderManifestResponse(
                    provider_id=profile.provider_id,
                    display_name=profile.display_name,
                    maturity=maturity,
                    execution_supported=profile.execution_supported,
                    execution_surface=self._execution_surface(profile.provider_id),
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
        execution_surface = self._execution_surface(provider_id)

        if request.task not in profile.supported_tasks:
            raise ValidationError("The selected provider does not declare the requested task")

        descriptors = {
            item.provider_id: item for item in list_model_providers(self.settings, refresh=True)
        }
        descriptor = descriptors.get(provider_id)
        optional_provider = provider_id in {"grounding_dino", "sam2", "smolvlm", "nnunet"}
        runtime = (
            optional_provider_runtime_status(self.settings, provider_id)
            if optional_provider
            else None
        )
        availability_status = (
            "ready"
            if runtime and runtime.get("ready")
            else "available_on_demand"
            if optional_provider
            else descriptor.availability_status
            if descriptor
            else "not_registered"
        )
        blockers: list[str] = []
        warnings: list[str] = list(profile.known_limitations)
        if not profile.execution_supported:
            blockers.append("No reviewed ReefVision execution adapter is enabled for this provider")
        if optional_provider:
            if provider_id == "nnunet" and runtime and not runtime.get("ready"):
                blockers.append(str(runtime.get("reason") or "nnU-Net runtime is not ready"))
            elif runtime and not runtime.get("ready") and not request.allow_model_download:
                blockers.append(
                    "Optional model is not cached. Enable explicit model download for this action."
                )
        elif descriptor is None:
            blockers.append("The provider is not registered in the main provider hub")
        elif descriptor.availability_status != "ready":
            blockers.append(
                descriptor.availability_reason
                or f"Provider availability is {descriptor.availability_status}"
            )

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
                        "Selected model is registered for provider "
                        f"{model.provider_name}, not {provider_id}"
                    )
                else:
                    selected_model_id = model.id

        if request.device not in {"auto", "cpu", "cuda", "0"}:
            warnings.append("Device value is provider-specific and has not been desktop-validated")
        if request.device in {"cpu"} and "cpu" not in profile.recommended_devices:
            warnings.append("CPU execution is not recommended for this provider profile")

        return AdvancedProviderPreflightResponse(
            provider_id=provider_id,
            task=request.task,
            ready=not blockers,
            execution_supported=profile.execution_supported,
            execution_surface=execution_surface,
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

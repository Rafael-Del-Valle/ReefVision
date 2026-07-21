"""Model-catalog extensions for installed segmentation architectures."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from reefvision.db.models import ModelRegistration
from reefvision.ml.semantic_segmentation import (
    NNUNET_CONFIGURATION,
    NNUNET_PROVIDER_ID,
    SEMANTIC_SEGMENTATION_TASK,
    nnunet_dependency_status,
)
from reefvision.schemas.model_catalog import (
    CatalogTask,
    CatalogWorkflow,
    ModelCatalogEntryResponse,
    ModelCatalogResponse,
)
from reefvision.services.model_catalog import ModelCatalogService


def installed_ultralytics_segmentation_architectures() -> set[str]:
    """Return installed Ultralytics segmentation architecture filenames."""

    try:
        models_root = Path(str(files("ultralytics.cfg").joinpath("models")))
    except Exception:
        return set()
    return {
        path.name
        for path in models_root.rglob("*-seg.yaml")
        if not any(
            token in path.name.casefold() for token in ("-cls", "-pose", "-obb", "world", "yoloe")
        )
    }


def _segmentation_architecture_name(
    detection_architecture: str | None,
) -> str | None:
    if not detection_architecture or not detection_architecture.endswith(".yaml"):
        return None
    return detection_architecture.removesuffix(".yaml") + "-seg.yaml"


def _segmentation_architecture_entry(
    source: ModelCatalogEntryResponse,
    architecture_reference: str,
) -> ModelCatalogEntryResponse:
    size_label = source.model_size or source.variant
    return source.model_copy(
        update={
            "catalog_id": source.catalog_id.replace(
                "/detect/",
                "/segment-architecture/",
            ),
            "display_name": (
                f"{source.architecture_family} {str(size_label).upper()} Segmentation"
            ),
            "display_summary": (
                "Installed Ultralytics instance-segmentation architecture "
                "for local scratch training from immutable polygon datasets."
            ),
            "task": "segment",
            "model_variant": "segment",
            "trainable": True,
            "inference": False,
            "inference_supported": False,
            "checkpoint_identifier": architecture_reference,
            "checkpoint_source": "builtin_architecture",
            "download_source_type": "builtin_architecture",
            "expected_checksum": None,
            "expected_file_size": None,
            "expected_files": [],
            "expected_size": None,
            "model_weight_license": (
                "No pretrained weights are attached; training begins from "
                "the installed architecture definition."
            ),
            "license_summary": (
                "Architecture definition supplied by the installed "
                "Ultralytics package; resulting model use remains subject "
                "to applicable licensing."
            ),
            "minimum_recommended_ram_gb": source.minimum_recommended_ram_gb,
            "minimum_recommended_vram_gb": source.minimum_recommended_vram_gb,
            "desktop_package_status": "base_sidecar_provider",
            "clean_machine_verification_status": "installed_architecture_discovery",
            "known_limitations": [
                "This preset starts from an architecture definition rather "
                "than pretrained weights.",
                "YOLO instance-segmentation training consumes polygon masks; "
                "raster masks are not converted silently.",
            ],
            "installation_state": "Ready",
            "installation_reason": (
                "The segmentation architecture definition is installed with "
                "the pinned Ultralytics provider."
            ),
            "installation_job_id": None,
            "installed_asset_id": f"builtin_architecture:{architecture_reference}",
            "installed_path": None,
            "installed_checksum": None,
            "advanced_only": False,
            "requires_confirmation": False,
            "selection_kind": "builtin_architecture",
            "architecture_reference": architecture_reference,
            "resolved_model_id": None,
        }
    )


def _semantic_architecture_entry() -> ModelCatalogEntryResponse:
    dependency = nnunet_dependency_status()
    ready = bool(dependency["ready"])
    return ModelCatalogEntryResponse(
        catalog_id="nnunet/v2/semantic/2d",
        display_name="nnU-Net v2 2D",
        display_summary=(
            "Self-configuring semantic segmentation for indexed polygon and raster mask datasets."
        ),
        category="pretrained_catalog",
        provider_id=NNUNET_PROVIDER_ID,
        architecture="nnU-Net v2",
        variant=NNUNET_CONFIGURATION,
        task=SEMANTIC_SEGMENTATION_TASK,
        trainable=True,
        inference_supported=False,
        checkpoint_identifier=NNUNET_CONFIGURATION,
        download_source_type="builtin_architecture",
        expected_files=[],
        expected_size=None,
        license_summary="nnU-Net is distributed under the Apache-2.0 license.",
        provider_pack_id=None,
        recommended_ram=16.0,
        recommended_vram=8.0,
        supported_devices=["cpu", "cuda", "mps"],
        supported_runtimes=["pytorch", "nnunetv2"],
        desktop_support="optional_local_provider",
        availability="experimental",
        provider=NNUNET_PROVIDER_ID,
        provider_version=str(dependency["provider_version"]),
        architecture_family="nnU-Net v2",
        model_variant="semantic",
        model_size="2d",
        inference=False,
        video_compatibility=False,
        prompt_assist_compatibility=False,
        tiling_compatibility=False,
        tuning_compatibility=False,
        checkpoint_source="builtin_architecture",
        expected_checksum=None,
        expected_file_size=None,
        model_weight_license="No pretrained weights are attached; training starts from scratch.",
        package_license="Apache-2.0",
        required_provider_pack=None,
        required_package_versions=["nnunetv2"],
        supported_runtime=["pytorch", "nnunetv2"],
        supported_precision=["fp32", "amp"],
        expected_input_size=None,
        minimum_recommended_ram_gb=16.0,
        minimum_recommended_vram_gb=8.0,
        desktop_package_status="optional_local_provider",
        clean_machine_verification_status=(
            "provider_preflight_ready" if ready else "provider_not_installed"
        ),
        deprecation_status="experimental",
        replacement_model_id=None,
        known_limitations=[
            "The optional nnU-Net provider must be installed into ReefVision's Python environment.",
            "This first slice supports the 2D configuration and scratch training.",
            "Training progress is stage-level until nnU-Net subprocess streaming is added.",
        ],
        installation_state="Ready" if ready else "Provider Required",
        installation_reason=(
            "The nnU-Net command-line provider is installed and ready."
            if ready
            else "; ".join(str(item) for item in dependency["issues"])
        ),
        installation_job_id=None,
        installed_asset_id=("builtin_architecture:nnunet-2d" if ready else None),
        installed_path=None,
        installed_checksum=None,
        advanced_only=False,
        requires_confirmation=False,
        selection_kind="builtin_architecture",
        architecture_reference=NNUNET_CONFIGURATION,
        resolved_model_id=None,
    )


def _catalog_entry_sort_key(
    item: ModelCatalogEntryResponse,
) -> tuple[int, int, str, str, str, str]:
    category_rank = (
        0
        if item.category == "pretrained_catalog"
        else 1
        if item.category == "my_trained_models"
        else 2
    )
    availability_rank = 0 if item.installation_state in {"Ready", "Available"} else 1
    return (
        category_rank,
        availability_rank,
        item.task,
        item.architecture_family.casefold(),
        item.display_name.casefold(),
        item.catalog_id,
    )


class SegmentationModelCatalogService(ModelCatalogService):
    """Add installed segment architectures and task-correct project models."""

    def list_project_catalog(
        self,
        project_id: str,
        *,
        workflow: CatalogWorkflow | None = None,
        task: CatalogTask | None = None,
        include_unavailable: bool = True,
    ) -> ModelCatalogResponse:
        catalog = super().list_project_catalog(
            project_id,
            workflow=workflow,
            task=None,
            include_unavailable=include_unavailable,
        )
        available = installed_ultralytics_segmentation_architectures()
        architecture_entries: list[ModelCatalogEntryResponse] = []
        if workflow in {None, "model_hub", "training"} and task in {None, "segment"}:
            seen_architectures: set[str] = set()
            for entry in catalog.models:
                if entry.task != "detect" or entry.category != "pretrained_catalog":
                    continue
                segment_architecture = _segmentation_architecture_name(entry.architecture_reference)
                if (
                    segment_architecture is None
                    or segment_architecture not in available
                    or segment_architecture in seen_architectures
                ):
                    continue
                seen_architectures.add(segment_architecture)
                architecture_entries.append(
                    _segmentation_architecture_entry(entry, segment_architecture)
                )
        if workflow in {None, "model_hub", "training"} and task in {
            None,
            SEMANTIC_SEGMENTATION_TASK,
        }:
            architecture_entries.append(_semantic_architecture_entry())
        filtered = [entry for entry in catalog.models if task is None or entry.task == task]
        ordered = sorted(
            [*filtered, *architecture_entries],
            key=_catalog_entry_sort_key,
        )
        return catalog.model_copy(update={"models": ordered})

    def _dynamic_entry_from_model(
        self,
        model: ModelRegistration,
    ) -> ModelCatalogEntryResponse:
        entry = super()._dynamic_entry_from_model(model)
        if model.purpose == "segmenter":
            return entry.model_copy(
                update={
                    "task": "segment",
                    "variant": "segment",
                    "model_variant": "segment",
                    "trainable": True,
                    "inference": True,
                    "inference_supported": True,
                    "prompt_assist_compatibility": False,
                    "known_limitations": [
                        "This model prefers reviewable polygon-mask proposals and falls "
                        "back to managed source-aligned raster masks when needed.",
                        "Per-class semantic label maps use a separate provider workflow.",
                    ],
                }
            )
        if model.purpose == "semantic_segmenter":
            return entry.model_copy(
                update={
                    "task": SEMANTIC_SEGMENTATION_TASK,
                    "variant": "semantic",
                    "model_variant": "semantic",
                    "trainable": False,
                    "inference": True,
                    "inference_supported": True,
                    "prompt_assist_compatibility": False,
                    "known_limitations": [
                        "This model produces reviewable per-class raster-mask proposals."
                    ],
                }
            )
        return entry

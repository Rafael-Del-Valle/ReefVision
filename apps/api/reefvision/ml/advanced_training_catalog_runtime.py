"""Add the external nnU-Net 2D provider to the project training catalog."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

_APPLIED = False
_CATALOG_ID = "nnunet/v2/2d"


def _nnunet_version() -> str | None:
    try:
        return version("nnunetv2")
    except PackageNotFoundError:
        return None


def apply_advanced_training_catalog_patch() -> None:
    global _APPLIED
    if _APPLIED:
        return

    from reefvision.services import model_catalog

    original = model_catalog.ModelCatalogService.list_project_catalog

    def list_with_nnunet(
        self: Any,
        project_id: str,
        *,
        workflow: Any = None,
        task: Any = None,
        include_unavailable: bool = True,
    ) -> Any:
        response = original(
            self,
            project_id,
            workflow=workflow,
            task=task,
            include_unavailable=include_unavailable,
        )
        if workflow not in {None, "model_hub", "training"}:
            return response
        if task not in {None, "semantic_segment"}:
            return response
        if any(item.catalog_id == _CATALOG_ID for item in response.models):
            return response
        template = next(
            (
                item
                for item in response.models
                if item.catalog_id.startswith("reefvision/unet/")
            ),
            None,
        )
        if template is None:
            return response
        installed_version = _nnunet_version()
        ready = installed_version is not None
        if not ready and not include_unavailable:
            return response
        entry = template.model_copy(
            update={
                "catalog_id": _CATALOG_ID,
                "display_name": "nnU-Net v2 2D",
                "display_summary": (
                    "Advanced self-configuring 2D semantic segmentation using ReefVision's "
                    "immutable indexed-mask dataset exports."
                ),
                "provider": "nnunet",
                "provider_id": "nnunet",
                "provider_version": installed_version or "not-installed",
                "architecture": "nnU-Net v2 2D",
                "architecture_family": "nnU-Net v2",
                "variant": "2d",
                "model_variant": "semantic_segment",
                "model_size": "default",
                "task": "semantic_segment",
                "trainable": True,
                "inference": True,
                "inference_supported": True,
                "video_compatibility": False,
                "prompt_assist_compatibility": False,
                "tiling_compatibility": False,
                "tuning_compatibility": False,
                "checkpoint_identifier": "nnunet-v2-2d",
                "checkpoint_source": "builtin_external_architecture",
                "download_source_type": "installed_python_provider",
                "expected_files": [],
                "expected_size": None,
                "expected_file_size": None,
                "expected_checksum": None,
                "license_summary": "Apache-2.0 provider; trained weights inherit dataset terms.",
                "model_weight_license": "User-trained checkpoint; verify dataset and deployment terms.",
                "package_license": "Apache-2.0; see installed nnunetv2 package metadata.",
                "provider_pack_id": "nnunetv2",
                "required_provider_pack": "nnunetv2",
                "required_package_versions": [
                    f"nnunetv2=={installed_version}" if installed_version else "nnunetv2"
                ],
                "recommended_ram": 16.0,
                "recommended_vram": 8.0,
                "minimum_recommended_ram_gb": 16.0,
                "minimum_recommended_vram_gb": 8.0,
                "supported_devices": ["cpu", "cuda"],
                "supported_runtimes": ["pytorch", "nnunetv2_cli"],
                "supported_runtime": ["pytorch", "nnunetv2_cli"],
                "supported_precision": ["fp32", "amp"],
                "desktop_support": "advanced_external_runtime",
                "desktop_package_status": "bundled_provider_runtime",
                "clean_machine_verification_status": "acceptance_required",
                "availability": "available" if ready else "unavailable",
                "deprecation_status": "active",
                "known_limitations": [
                    "Training invokes the packaged nnU-Net command entry points without shell execution.",
                    "Planning, preprocessing, and training require additional temporary disk space.",
                    "ReefVision tiling and hyperparameter tuning remain disabled for this preset.",
                ],
                "installation_state": "Ready" if ready else "Provider Required",
                "installation_reason": (
                    "The packaged nnU-Net v2 2D training provider is ready."
                    if ready
                    else "The nnunetv2 dependency is not installed in this runtime."
                ),
                "installed_asset_id": "builtin_architecture:nnunet:2d" if ready else None,
                "installed_path": None,
                "installed_checksum": None,
                "metadata_verified": ready,
                "provider_ready": ready,
                "provider_state": "ready" if ready else "unavailable",
                "provider_failure_reason": None if ready else "nnunetv2 is not installed",
                "capabilities": {
                    "image_semantic_segmentation": True,
                    "training": True,
                    "validation": True,
                    "export": True,
                    "cpu_inference": True,
                    "cuda_inference": True,
                },
                "advanced_only": False,
                "requires_confirmation": False,
                "selection_kind": "builtin_architecture",
                "architecture_reference": "2d",
                "resolved_model_id": None,
            }
        )
        models = sorted(
            [*response.models, entry],
            key=lambda item: (
                item.task,
                item.architecture_family.casefold(),
                item.display_name.casefold(),
                item.catalog_id,
            ),
        )
        return response.model_copy(update={"models": models})

    model_catalog.ModelCatalogService.list_project_catalog = list_with_nnunet
    _APPLIED = True

"""Update the existing nnU-Net training card for the packaged provider runtime."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from reefvision.ml.nnunet_dependency_contract import (
    PINNED_NNUNET_VERSION,
    validate_nnunet_dependency_contract,
)

_APPLIED = False


def _installed_version() -> str | None:
    try:
        return version("nnunetv2")
    except PackageNotFoundError:
        return None


def apply_nnunet_catalog_runtime_patch() -> None:
    global _APPLIED
    if _APPLIED:
        return

    from reefvision.services import segmentation_catalog

    original = segmentation_catalog._semantic_architecture_entry

    def packaged_semantic_architecture_entry() -> Any:
        entry = original()
        issues = validate_nnunet_dependency_contract()
        ready = not issues
        return entry.model_copy(
            update={
                "availability": "available" if ready else "experimental",
                "provider_version": _installed_version() or "not-installed",
                "required_package_versions": [
                    f"nnunetv2=={PINNED_NNUNET_VERSION}"
                ],
                "desktop_support": "base_sidecar_provider",
                "desktop_package_status": "base_sidecar_provider",
                "clean_machine_verification_status": "acceptance_required",
                "deprecation_status": "active",
                "known_limitations": [
                    "This first release supports the 2D configuration and scratch training.",
                    "Planning and training require additional managed temporary disk space.",
                    "Training progress is stage-level until subprocess streaming is added.",
                ],
                "installation_state": "Ready" if ready else "Provider Required",
                "installation_reason": (
                    "The pinned nnU-Net provider and packaged command entrypoints are ready."
                    if ready
                    else "; ".join(issues)
                ),
                "installed_asset_id": (
                    "builtin_architecture:nnunet-2d" if ready else None
                ),
                "metadata_verified": ready,
                "provider_ready": ready,
                "provider_state": "ready" if ready else "unavailable",
                "provider_failure_reason": None if ready else "; ".join(issues),
            }
        )

    segmentation_catalog._semantic_architecture_entry = (
        packaged_semantic_architecture_entry
    )
    _APPLIED = True

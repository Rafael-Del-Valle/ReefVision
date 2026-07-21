"""Persistent unified provider lifecycle and catalog reconciliation service."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, ProviderAcceptanceRecord, ProviderModelAsset
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.provider_contract import (
    CheckpointKind,
    DeviceMode,
    LifecycleInferenceRequest,
    ProviderCapabilities,
    ProviderFileRecord,
    ProviderModelDefinition,
    ProviderState,
)
from reefvision.ml.provider_lifecycle import ProviderRuntimeManager
from reefvision.ml.provider_verification import (
    diagnose_model,
    folder_checksum,
    resolve_managed_relative_path,
    sha256_file,
    verify_checkpoint,
)
from reefvision.schemas.provider_lifecycle import (
    ProviderAcceptanceRecordListResponse,
    ProviderAcceptanceRecordResponse,
    ProviderCancelResponse,
    ProviderDiscoveryResponse,
    ProviderInferenceRequest,
    ProviderInferenceResponse,
    ProviderLifecycleActionResponse,
    ProviderModelAssetListResponse,
    ProviderModelAssetResponse,
    TrustedExternalModelRegisterRequest,
)
from reefvision.storage.catalog_models import load_catalog_manifest
from reefvision.storage.projects import resolve_managed_project_path

CLIP_TEXT_MODEL_SHA256 = "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af"
CLIP_TEXT_MODEL_RELATIVE_PATH = "models/provider-dependencies/clip/ViT-B-32.pt"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _managed_capabilities(model_id: str) -> ProviderCapabilities:
    normalized = model_id.casefold()
    if "/detect/" in normalized:
        return ProviderCapabilities(box_output=True, batching=True, training=True)
    if "/segment/" in normalized:
        return ProviderCapabilities(
            box_output=True,
            mask_output=True,
            batching=True,
            training=True,
        )
    if "/rtdetr/" in normalized:
        return ProviderCapabilities(box_output=True, batching=True)
    if "yolo_world" in normalized:
        return ProviderCapabilities(box_output=True, text_prompt=True, batching=True)
    if "/yoloe/" in normalized:
        return ProviderCapabilities(box_output=True, mask_output=True, batching=True)
    if "fastsam" in normalized:
        return ProviderCapabilities(
            point_prompt=True,
            box_prompt=True,
            brush_refinement=True,
            mask_output=True,
        )
    return ProviderCapabilities(
        point_prompt=True,
        negative_point_prompt=True,
        box_prompt=True,
        mixed_point_box_prompt=True,
        brush_refinement=True,
        mask_output=True,
    )


def _managed_metadata(model_id: str, filename: str) -> dict[str, Any]:
    normalized = model_id.casefold()
    task = "detect"
    provider_id = "ultralytics"
    architecture = filename.rsplit(".", 1)[0]
    output_types = ["prediction_proposal", "bounding_box"]
    prompt_types: list[str] = []
    supports_training = False
    supports_video = False
    limitations: list[str] = [
        "Software acceptance is not scientific validation on coral imagery.",
        "Packaged-desktop operation is not exercised by source-runtime acceptance.",
    ]
    if "/detect/" in normalized:
        supports_training = True
    elif "/segment/" in normalized:
        task = "segment"
        supports_training = True
        output_types.extend(["polygon_mask", "source_aligned_raster_mask"])
    elif "/rtdetr/" in normalized:
        architecture = "RT-DETR"
        limitations.append("ReefVision does not advertise RT-DETR training support.")
    elif "yolo_world" in normalized:
        architecture = "YOLO-World v2"
        task = "open_vocabulary_detect"
        prompt_types = ["text_class"]
        limitations.extend(
            [
                "An explicit user-provided class list is required for inference.",
                "Open-vocabulary detections remain review proposals until accepted.",
            ]
        )
    elif "/yoloe/" in normalized:
        architecture = "YOLOE prompt-free segmentation"
        task = "prompt_free_segment"
        output_types.extend(["polygon_mask", "source_aligned_raster_mask"])
        limitations.append("Prompt-free proposals remain unverified until explicit review.")
    elif any(key in normalized for key in ("sam/", "sam2/", "mobilesam", "fastsam")):
        provider_id = "ultralytics_sam"
        task = "assist_segmentation"
        output_types = ["editable_mask_candidate", "bounding_box"]
        capabilities = _managed_capabilities(model_id)
        if capabilities.point_prompt:
            prompt_types.append("positive_point")
        if capabilities.negative_point_prompt:
            prompt_types.append("negative_point")
        if capabilities.box_prompt:
            prompt_types.append("box")
        if capabilities.brush_refinement:
            prompt_types.append("brush")
        if "sam2/" in normalized:
            architecture = "SAM 2 Base image"
            limitations.append(
                "The installed Ultralytics image checkpoint does not provide ReefVision's "
                "SAM 2 video predictor API; video propagation remains unavailable."
            )
        elif "mobilesam" in normalized:
            architecture = "MobileSAM"
        elif "fastsam" in normalized:
            architecture = "FastSAM Small"
            limitations.append(
                "Negative-point and mixed point/box prompting are not advertised for FastSAM."
            )
        else:
            architecture = "Ultralytics SAM ViT-B"
    return {
        "provider_id": provider_id,
        "architecture": architecture,
        "task": task,
        "output_types": output_types,
        "prompt_types": prompt_types,
        "supports_training": supports_training,
        "supports_video": supports_video,
        "known_limitations": limitations,
    }


def _external_capabilities(provider_id: str) -> ProviderCapabilities:
    if provider_id == "segment_anything":
        return ProviderCapabilities(
            point_prompt=True,
            negative_point_prompt=True,
            box_prompt=True,
            mixed_point_box_prompt=True,
            brush_refinement=True,
            mask_output=True,
        )
    return ProviderCapabilities(depth_output=True, batching=True)


class ProviderLifecycleService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        runtime: ProviderRuntimeManager,
    ) -> None:
        self.session = session
        self.settings = settings
        self.runtime = runtime

    @staticmethod
    def _definition(asset: ProviderModelAsset) -> ProviderModelDefinition:
        capability_fields = ProviderCapabilities.__dataclass_fields__
        capabilities = ProviderCapabilities(
            **{
                key: bool(value)
                for key, value in asset.capabilities_json.items()
                if key in capability_fields
            }
        )
        return ProviderModelDefinition(
            provider_id=asset.provider_id,
            provider_version=asset.provider_version,
            model_id=asset.model_id,
            architecture=asset.architecture,
            task=asset.task,
            capabilities=capabilities,
            checkpoint_path=Path(asset.checkpoint_path),
            checkpoint_kind=(
                CheckpointKind.DIRECTORY
                if asset.checkpoint_format == "huggingface_directory"
                else CheckpointKind.FILE
            ),
            checkpoint_sha256=asset.checkpoint_sha256,
            checkpoint_size_bytes=asset.checkpoint_size_bytes,
            checkpoint_format=asset.checkpoint_format,
            source=asset.source,
            revision=asset.revision,
            license_metadata=dict(asset.license_json),
            required_packages=tuple(asset.required_packages_json),
            optional_packages=tuple(asset.optional_packages_json),
            supported_devices=tuple(DeviceMode(value) for value in asset.supported_devices_json),
            preferred_device=DeviceMode(asset.preferred_device),
            estimated_vram_bytes=asset.estimated_vram_bytes,
            input_types=tuple(asset.input_types_json),
            output_types=tuple(asset.output_types_json),
            prompt_types=tuple(asset.prompt_types_json),
            file_manifest=tuple(
                ProviderFileRecord(
                    relative_path=str(item["relative_path"]),
                    size_bytes=int(item["size_bytes"]),
                    sha256=str(item["sha256"]),
                )
                for item in asset.file_manifest_json
            ),
            metadata=dict(asset.metadata_json),
        )

    def _latest_acceptance_status(self, asset_id: str) -> str | None:
        record = self.session.scalar(
            select(ProviderAcceptanceRecord)
            .where(ProviderAcceptanceRecord.provider_asset_id == asset_id)
            .order_by(
                ProviderAcceptanceRecord.recorded_at.desc(), ProviderAcceptanceRecord.id.desc()
            )
            .limit(1)
        )
        if record is None:
            return None
        return (
            "passed"
            if record.load_result == record.inference_result == record.unload_result == "passed"
            else "failed"
        )

    def _response(self, asset: ProviderModelAsset) -> ProviderModelAssetResponse:
        return ProviderModelAssetResponse(
            id=asset.id,
            provider_id=asset.provider_id,
            provider_version=asset.provider_version,
            model_id=asset.model_id,
            architecture=asset.architecture,
            task=asset.task,
            capabilities={key: bool(value) for key, value in asset.capabilities_json.items()},
            checkpoint_path=asset.checkpoint_path,
            checkpoint_path_kind=asset.checkpoint_path_kind,
            checkpoint_sha256=asset.checkpoint_sha256,
            checkpoint_size_bytes=asset.checkpoint_size_bytes,
            checkpoint_format=asset.checkpoint_format,
            file_manifest=asset.file_manifest_json,
            source=asset.source,
            revision=asset.revision,
            license_metadata=asset.license_json,
            required_packages=asset.required_packages_json,
            optional_packages=asset.optional_packages_json,
            supported_devices=asset.supported_devices_json,
            preferred_device=asset.preferred_device,
            estimated_vram_bytes=asset.estimated_vram_bytes,
            input_types=asset.input_types_json,
            output_types=asset.output_types_json,
            prompt_types=asset.prompt_types_json,
            supports_training=asset.supports_training,
            supports_inference=asset.supports_inference,
            supports_video=asset.supports_video,
            state=asset.state,
            failure_reason=asset.failure_reason,
            verification=asset.verification_json,
            last_health_check=asset.last_health_check_json,
            last_health_check_at=asset.last_health_check_at,
            last_successful_load_at=asset.last_successful_load_at,
            last_successful_inference_at=asset.last_successful_inference_at,
            metadata=asset.metadata_json,
            latest_acceptance_status=self._latest_acceptance_status(asset.id),
            created_at=asset.created_at,
            updated_at=asset.updated_at,
        )

    def _get(self, asset_id: str) -> ProviderModelAsset:
        asset = self.session.get(ProviderModelAsset, asset_id)
        if asset is None:
            raise NotFoundError("Provider model asset not found")
        return asset

    def _reconcile_runtime_states(self) -> None:
        """Remove impossible persisted loaded states after a process restart."""

        changed = False
        for asset in self.session.scalars(
            select(ProviderModelAsset).where(
                ProviderModelAsset.state.in_(
                    [ProviderState.LOADING.value, ProviderState.LOADED.value]
                )
            )
        ):
            runtime_owns_asset = (
                self.runtime.loaded_model_id == asset.model_id
                and self.runtime.state is ProviderState.LOADED
            )
            if runtime_owns_asset:
                if asset.state != ProviderState.LOADED.value:
                    asset.state = ProviderState.LOADED.value
                    asset.updated_at = _utc_now()
                    changed = True
                continue
            asset.state = (
                ProviderState.UNLOADED.value
                if bool(asset.verification_json.get("verified"))
                else ProviderState.UNAVAILABLE.value
            )
            asset.updated_at = _utc_now()
            changed = True
        if changed:
            self.session.commit()

    def _verify_and_diagnose(self, asset: ProviderModelAsset) -> None:
        model = self._definition(asset)
        verification = verify_checkpoint(model)
        diagnosis = diagnose_model(model, asset.preferred_device)
        if asset.checkpoint_size_bytes is None:
            asset.checkpoint_size_bytes = verification.size_bytes
        asset.verification_json = {
            "status": verification.status,
            "verified": verification.verified,
            "checkpoint_exists": verification.checkpoint_exists,
            "expected_sha256": verification.expected_sha256,
            "observed_sha256": verification.observed_sha256,
            "expected_size_bytes": verification.expected_size_bytes,
            "observed_size_bytes": verification.size_bytes,
            "warnings": list(verification.warnings),
            "failure_reason": verification.failure_reason,
            "verified_at": _utc_now().isoformat(),
        }
        dependency_failure: str | None = None
        dependency_verification: dict[str, Any] = {}
        if asset.task == "open_vocabulary_detect":
            dependency_path_value = asset.metadata_json.get("clip_text_checkpoint_path")
            dependency_path = Path(str(dependency_path_value)) if dependency_path_value else None
            dependency_exists = bool(dependency_path and dependency_path.is_file())
            observed_dependency_sha256 = (
                sha256_file(dependency_path)
                if dependency_path is not None and dependency_exists
                else None
            )
            dependency_verified = observed_dependency_sha256 == CLIP_TEXT_MODEL_SHA256
            dependency_verification = {
                "clip_text_checkpoint_exists": dependency_exists,
                "clip_text_checkpoint_verified": dependency_verified,
                "clip_text_checkpoint_expected_sha256": CLIP_TEXT_MODEL_SHA256,
                "clip_text_checkpoint_observed_sha256": observed_dependency_sha256,
            }
            if not dependency_verified:
                dependency_failure = (
                    "YOLO-World requires the explicitly managed CLIP ViT-B/32 text "
                    "checkpoint; automatic downloads are disabled."
                )
        if not verification.verified:
            asset.state = ProviderState.UNAVAILABLE.value
            asset.failure_reason = verification.failure_reason
        elif not diagnosis.ready:
            asset.state = ProviderState.UNAVAILABLE.value
            asset.failure_reason = diagnosis.failure_reason
        elif dependency_failure:
            asset.state = ProviderState.UNAVAILABLE.value
            asset.failure_reason = dependency_failure
        elif asset.state not in {ProviderState.LOADED.value, ProviderState.LOADING.value}:
            asset.state = ProviderState.READY.value
            asset.failure_reason = None
        asset.metadata_json = {
            **dict(asset.metadata_json or {}),
            "runtime_versions": diagnosis.runtime_versions,
            "resolved_preferred_device": diagnosis.resolved_device,
            "missing_packages": list(diagnosis.missing_packages),
            **dependency_verification,
        }
        asset.updated_at = _utc_now()

    def discover(self) -> ProviderDiscoveryResponse:
        self._reconcile_runtime_states()
        manifest = load_catalog_manifest(self.settings)
        raw_assets = manifest.get("assets")
        assets = raw_assets if isinstance(raw_assets, dict) else {}
        warnings: list[str] = []
        managed_ids: list[str] = []
        for model_id in sorted(assets):
            raw = assets[model_id]
            if not isinstance(raw, dict):
                warnings.append(f"Manifest entry is not an object: {model_id}")
                continue
            relative_path = str(raw.get("relative_path") or "")
            path = resolve_managed_relative_path(self.settings.resolved_data_dir, relative_path)
            filename = str(raw.get("filename") or Path(relative_path).name)
            metadata = _managed_metadata(model_id, filename)
            capabilities = _managed_capabilities(model_id)
            asset = self.session.scalar(
                select(ProviderModelAsset).where(ProviderModelAsset.model_id == model_id)
            )
            if asset is None:
                asset = ProviderModelAsset(
                    model_id=model_id,
                    created_at=_utc_now(),
                    updated_at=_utc_now(),
                )
                self.session.add(asset)
            asset.provider_id = str(metadata["provider_id"])
            asset.provider_version = str(raw.get("provider_version") or "unknown")
            asset.architecture = str(metadata["architecture"])
            asset.task = str(metadata["task"])
            asset.capabilities_json = capabilities.as_dict()
            asset.checkpoint_path = str(path or self.settings.resolved_data_dir / relative_path)
            asset.checkpoint_path_kind = "managed"
            asset.checkpoint_sha256 = str(raw.get("sha256") or "") or None
            asset.checkpoint_size_bytes = (
                int(raw["size_bytes"]) if isinstance(raw.get("size_bytes"), int) else None
            )
            asset.checkpoint_format = "pytorch_checkpoint"
            asset.file_manifest_json = []
            asset.source = str(raw.get("source") or "managed_catalog")
            asset.revision = (
                str(raw.get("revision") or raw.get("bundle_catalog_version") or "") or None
            )
            asset.license_json = {
                "summary": (
                    "Upstream checkpoint license applies; catalog metadata must be reviewed "
                    "before redistribution."
                )
            }
            asset.required_packages_json = ["torch", "ultralytics"]
            if str(metadata["task"]) == "open_vocabulary_detect":
                asset.required_packages_json.append("clip")
            asset.optional_packages_json = []
            asset.supported_devices_json = ["cpu", "cuda"]
            asset.preferred_device = "auto"
            asset.estimated_vram_bytes = None
            asset.input_types_json = ["image", *metadata["prompt_types"]]
            asset.output_types_json = list(metadata["output_types"])
            asset.prompt_types_json = list(metadata["prompt_types"])
            asset.supports_training = bool(metadata["supports_training"])
            asset.supports_inference = True
            asset.supports_video = bool(metadata["supports_video"])
            asset.metadata_json = {
                **dict(asset.metadata_json or {}),
                "catalog_id": model_id,
                "managed_relative_path": relative_path,
                "known_limitations": metadata["known_limitations"],
                "scientific_validation": False,
                "packaged_desktop_validation": False,
                "automatic_downloads_disabled": True,
            }
            if str(metadata["task"]) == "open_vocabulary_detect":
                clip_path = self.settings.resolved_data_dir / CLIP_TEXT_MODEL_RELATIVE_PATH
                asset.metadata_json = {
                    **asset.metadata_json,
                    "clip_text_checkpoint_path": str(clip_path),
                    "clip_text_checkpoint_sha256": CLIP_TEXT_MODEL_SHA256,
                    "clip_text_model": "ViT-B/32",
                }
            if path is None:
                asset.state = ProviderState.UNAVAILABLE.value
                asset.failure_reason = (
                    "Managed manifest path escapes the ReefVision data directory."
                )
                asset.verification_json = {
                    "status": "unsafe_path",
                    "verified": False,
                }
            else:
                if (
                    asset.state in {ProviderState.LOADED.value, ProviderState.LOADING.value}
                    and self.runtime.loaded_model_id != asset.model_id
                ):
                    asset.state = ProviderState.UNLOADED.value
                self._verify_and_diagnose(asset)
            managed_ids.append(model_id)

        self.session.flush()
        checksum_groups: dict[str, list[str]] = defaultdict(list)
        for asset in self.session.scalars(select(ProviderModelAsset)):
            if asset.checkpoint_sha256:
                checksum_groups[asset.checkpoint_sha256].append(asset.model_id)
        duplicates = [sorted(group) for group in checksum_groups.values() if len(group) > 1]
        for group in duplicates:
            for model_id in group:
                asset = self.session.scalar(
                    select(ProviderModelAsset).where(ProviderModelAsset.model_id == model_id)
                )
                if asset is not None:
                    asset.metadata_json = {
                        **dict(asset.metadata_json or {}),
                        "duplicate_checksum_model_ids": [
                            value for value in group if value != model_id
                        ],
                    }
        self.session.commit()
        all_assets = list(self.session.scalars(select(ProviderModelAsset)))
        return ProviderDiscoveryResponse(
            discovered_count=len(all_assets),
            managed_count=len(managed_ids),
            external_count=sum(
                item.checkpoint_path_kind == "trusted_external" for item in all_assets
            ),
            verified_count=sum(bool(item.verification_json.get("verified")) for item in all_assets),
            unavailable_count=sum(
                item.state == ProviderState.UNAVAILABLE.value for item in all_assets
            ),
            duplicate_checksum_groups=duplicates,
            warnings=warnings,
        )

    def register_external(
        self, request: TrustedExternalModelRegisterRequest
    ) -> ProviderModelAssetResponse:
        if not request.confirmed:
            raise ValidationError("Confirm trusted external registration before continuing")
        path = Path(request.checkpoint_path).expanduser()
        if not path.is_absolute():
            raise ValidationError("Trusted external checkpoint paths must be absolute")
        path = path.resolve(strict=False)
        existing = self.session.scalar(
            select(ProviderModelAsset).where(ProviderModelAsset.model_id == request.model_id)
        )
        if existing is not None and existing.checkpoint_path_kind == "managed":
            raise ConflictError("A managed catalog model already uses this model id")

        file_manifest: list[dict[str, Any]] = []
        checkpoint_format: str
        digest: str | None
        size: int | None
        metadata: dict[str, Any] = {
            "trusted_external": True,
            "copied_into_managed_storage": False,
            "automatic_downloads_disabled": True,
            "scientific_validation": False,
            "packaged_desktop_validation": False,
        }
        required_packages: list[str]
        if request.provider_id == "segment_anything":
            if not path.is_file() or path.suffix.casefold() not in {".pth", ".pt"}:
                raise ValidationError("Original SAM requires an existing .pth or .pt checkpoint")
            digest = sha256_file(path)
            size = path.stat().st_size
            checkpoint_format = "pytorch_checkpoint"
            required_packages = ["torch", "segment-anything", "opencv-python"]
            metadata.update(
                sam_variant="vit_b",
                known_limitations=[
                    "Image prompting only; this original SAM checkpoint has no video propagation.",
                    "Accepted candidates remain editable raster masks with explicit provenance.",
                ],
            )
        else:
            if not path.is_dir():
                raise ValidationError("Depth Anything requires an existing local model folder")
            required_names = ("config.json", "model.safetensors", "preprocessor_config.json")
            records: list[ProviderFileRecord] = []
            for filename in required_names:
                candidate = path / filename
                if not candidate.is_file():
                    raise ValidationError(f"Depth Anything folder is missing {filename}")
                record = ProviderFileRecord(
                    relative_path=filename,
                    size_bytes=candidate.stat().st_size,
                    sha256=sha256_file(candidate),
                )
                records.append(record)
                file_manifest.append(
                    {
                        "relative_path": record.relative_path,
                        "size_bytes": record.size_bytes,
                        "sha256": record.sha256,
                    }
                )
            digest = folder_checksum(tuple(records))
            size = sum(record.size_bytes for record in records)
            checkpoint_format = "huggingface_directory"
            required_packages = ["torch", "transformers", "safetensors"]
            metadata.update(
                relative_depth_only=True,
                physical_units=None,
                raw_output_distinct_from_display_normalization=True,
                known_limitations=[
                    "Output is relative depth, not centimeters, meters, or physical coral height.",
                    "Physical interpretation requires independent metric calibration.",
                ],
            )

        asset = existing or ProviderModelAsset(
            model_id=request.model_id,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        if existing is None:
            self.session.add(asset)
        capabilities = _external_capabilities(request.provider_id)
        asset.provider_id = request.provider_id
        asset.provider_version = (
            "1.0" if request.provider_id == "segment_anything" else "transformers-local"
        )
        asset.architecture = request.architecture
        asset.task = request.task
        asset.capabilities_json = capabilities.as_dict()
        asset.checkpoint_path = str(path)
        asset.checkpoint_path_kind = "trusted_external"
        asset.checkpoint_sha256 = digest
        asset.checkpoint_size_bytes = size
        asset.checkpoint_format = checkpoint_format
        asset.file_manifest_json = file_manifest
        asset.source = request.source
        asset.revision = request.revision
        asset.license_json = dict(request.license_metadata)
        asset.required_packages_json = required_packages
        asset.optional_packages_json = []
        asset.supported_devices_json = ["cpu", "cuda"]
        asset.preferred_device = "auto"
        asset.estimated_vram_bytes = None
        asset.input_types_json = (
            ["image", "positive_point", "negative_point", "box"]
            if request.provider_id == "segment_anything"
            else ["image"]
        )
        asset.output_types_json = (
            ["editable_raster_mask", "candidate_score"]
            if request.provider_id == "segment_anything"
            else ["relative_depth_raw", "relative_depth_display"]
        )
        asset.prompt_types_json = (
            ["positive_point", "negative_point", "box", "mixed_point_box", "brush"]
            if request.provider_id == "segment_anything"
            else []
        )
        asset.supports_training = False
        asset.supports_inference = True
        asset.supports_video = False
        asset.metadata_json = metadata
        self._verify_and_diagnose(asset)
        self.session.commit()
        self.session.refresh(asset)
        return self._response(asset)

    def list_assets(
        self,
        *,
        limit: int,
        offset: int,
        provider_id: str | None = None,
        state: str | None = None,
    ) -> ProviderModelAssetListResponse:
        self._reconcile_runtime_states()
        conditions: list[Any] = []
        if provider_id:
            conditions.append(ProviderModelAsset.provider_id == provider_id)
        if state:
            conditions.append(ProviderModelAsset.state == state)
        statement = select(ProviderModelAsset)
        count_statement = select(func.count()).select_from(ProviderModelAsset)
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        assets = list(
            self.session.scalars(
                statement.order_by(ProviderModelAsset.model_id).offset(offset).limit(limit)
            )
        )
        all_checksums: dict[str, list[str]] = defaultdict(list)
        for checksum, model_id in self.session.execute(
            select(ProviderModelAsset.checkpoint_sha256, ProviderModelAsset.model_id).where(
                ProviderModelAsset.checkpoint_sha256.is_not(None)
            )
        ):
            if checksum:
                all_checksums[str(checksum)].append(str(model_id))
        return ProviderModelAssetListResponse(
            items=[self._response(asset) for asset in assets],
            total=int(self.session.scalar(count_statement) or 0),
            limit=limit,
            offset=offset,
            duplicate_checksum_groups=[
                sorted(values) for values in all_checksums.values() if len(values) > 1
            ],
        )

    def get(self, asset_id: str) -> ProviderModelAssetResponse:
        self._reconcile_runtime_states()
        return self._response(self._get(asset_id))

    def verify(self, asset_id: str) -> ProviderLifecycleActionResponse:
        asset = self._get(asset_id)
        self._verify_and_diagnose(asset)
        self.session.commit()
        self.session.refresh(asset)
        return ProviderLifecycleActionResponse(
            asset=self._response(asset),
            action="verify",
            state=asset.state,
            details=dict(asset.verification_json),
            warnings=list(asset.verification_json.get("warnings") or []),
        )

    def diagnose(self, asset_id: str, device: str) -> ProviderLifecycleActionResponse:
        asset = self._get(asset_id)
        diagnosis = diagnose_model(self._definition(asset), device)
        details = {
            "ready": diagnosis.ready,
            "runtime_versions": diagnosis.runtime_versions,
            "missing_packages": list(diagnosis.missing_packages),
            "incompatible_packages": list(diagnosis.incompatible_packages),
            "failure_reason": diagnosis.failure_reason,
        }
        return ProviderLifecycleActionResponse(
            asset=self._response(asset),
            action="diagnose",
            state=asset.state,
            resolved_device=diagnosis.resolved_device,
            details=details,
            warnings=list(diagnosis.warnings),
        )

    def load(self, asset_id: str, device: str) -> ProviderLifecycleActionResponse:
        asset = self._get(asset_id)
        self._verify_and_diagnose(asset)
        if not bool(asset.verification_json.get("verified")):
            self.session.commit()
            raise ConflictError(asset.failure_reason or "Checkpoint verification failed")
        asset.state = ProviderState.LOADING.value
        asset.updated_at = _utc_now()
        self.session.commit()
        try:
            resolved = self.runtime.load(self._definition(asset), device)
        except Exception as exc:
            asset.state = ProviderState.FAILED.value
            asset.failure_reason = str(exc)
            asset.updated_at = _utc_now()
            self.session.commit()
            raise
        asset.state = ProviderState.LOADED.value
        asset.failure_reason = None
        asset.last_successful_load_at = _utc_now()
        asset.updated_at = _utc_now()
        self.session.commit()
        return ProviderLifecycleActionResponse(
            asset=self._response(asset),
            action="load",
            state="loaded",
            resolved_device=resolved,
            details=self.runtime.health_check(),
        )

    def health_check(
        self,
        asset_id: str,
        *,
        device: str,
        kind: str,
        keep_loaded: bool,
    ) -> ProviderLifecycleActionResponse:
        asset = self._get(asset_id)
        checked_at = _utc_now()
        if kind == "metadata":
            self._verify_and_diagnose(asset)
            details = {
                "kind": "metadata",
                "verification": asset.verification_json,
                "runtime_versions": asset.metadata_json.get("runtime_versions", {}),
            }
            healthy = asset.state == ProviderState.READY.value
            resolved = asset.metadata_json.get("resolved_preferred_device")
        else:
            try:
                load_response = self.load(asset_id, device)
                resolved = load_response.resolved_device
                details = {"kind": "load", **self.runtime.health_check()}
                healthy = True
                if not keep_loaded:
                    self.runtime.unload()
                    asset.state = ProviderState.UNLOADED.value
            except Exception as exc:
                asset.last_health_check_at = checked_at
                asset.last_health_check_json = {
                    "kind": "load",
                    "healthy": False,
                    "checked_at": checked_at.isoformat(),
                    "failure_reason": str(exc),
                }
                asset.updated_at = checked_at
                self.session.commit()
                raise
        asset.last_health_check_at = checked_at
        asset.last_health_check_json = {
            **details,
            "healthy": healthy,
            "checked_at": checked_at.isoformat(),
        }
        asset.updated_at = checked_at
        self.session.commit()
        return ProviderLifecycleActionResponse(
            asset=self._response(asset),
            action="health_check",
            state=asset.state,
            resolved_device=str(resolved) if resolved else None,
            details=dict(asset.last_health_check_json),
        )

    def infer(
        self,
        asset_id: str,
        request: ProviderInferenceRequest,
    ) -> ProviderInferenceResponse:
        asset = self._get(asset_id)
        if request.image_id:
            image = self.session.get(ImageAsset, request.image_id)
            if image is None:
                raise NotFoundError("Provider inference image not found")
            source_path = resolve_managed_project_path(self.settings, image.managed_path)
        else:
            source_path = Path(str(request.source_path)).resolve(strict=False)
        try:
            source_path.relative_to(self.settings.resolved_data_dir)
        except ValueError as exc:
            raise ValidationError(
                "Provider API inference sources must be managed ReefVision files"
            ) from exc
        if not source_path.is_file():
            raise ValidationError("The managed provider inference source is missing")
        if self.runtime.loaded_model_id != asset.model_id:
            self.load(asset_id, request.device)
        result = self.runtime.infer(
            self._definition(asset),
            LifecycleInferenceRequest(
                request_id=request.request_id,
                source_path=source_path,
                device=request.device,
                parameters=dict(request.parameters),
            ),
        )
        asset.last_successful_inference_at = _utc_now()
        asset.updated_at = _utc_now()
        self.session.commit()
        return ProviderInferenceResponse(
            request_id=result.request_id,
            provider_id=result.provider_id,
            model_id=result.model_id,
            task=result.task,
            resolved_device=result.resolved_device,
            outputs=result.outputs,
            metadata=result.metadata,
            warnings=result.warnings,
        )

    def cancel(self, request_id: str) -> ProviderCancelResponse:
        return ProviderCancelResponse(
            request_id=request_id,
            cancellation_requested=self.runtime.cancel(request_id),
        )

    def unload(self, asset_id: str) -> ProviderLifecycleActionResponse:
        asset = self._get(asset_id)
        was_loaded = self.runtime.loaded_model_id == asset.model_id
        if was_loaded:
            self.runtime.unload()
        asset.state = (
            ProviderState.UNLOADED.value
            if bool(asset.verification_json.get("verified"))
            else ProviderState.UNAVAILABLE.value
        )
        asset.updated_at = _utc_now()
        self.session.commit()
        return ProviderLifecycleActionResponse(
            asset=self._response(asset),
            action="unload",
            state=asset.state,
            details={"was_loaded": was_loaded},
        )

    def repair_metadata(self, asset_id: str, *, confirmed: bool) -> ProviderModelAssetResponse:
        if not confirmed:
            raise ValidationError("Confirm metadata repair before updating the registration")
        asset = self._get(asset_id)
        if asset.checkpoint_path_kind != "trusted_external":
            raise ConflictError(
                "Managed catalog checksums can only be repaired by an explicit managed install"
            )
        definition = self._definition(asset)
        observed = verify_checkpoint(replace(definition, checkpoint_sha256=None))
        if not observed.checkpoint_exists or observed.observed_sha256 is None:
            raise ConflictError(observed.failure_reason or "Checkpoint metadata cannot be repaired")
        asset.checkpoint_sha256 = observed.observed_sha256
        asset.checkpoint_size_bytes = observed.size_bytes
        if observed.files:
            asset.file_manifest_json = [
                {
                    "relative_path": item.relative_path,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for item in observed.files
            ]
        self._verify_and_diagnose(asset)
        asset.metadata_json = {
            **dict(asset.metadata_json or {}),
            "metadata_repaired_at": _utc_now().isoformat(),
        }
        self.session.commit()
        return self._response(asset)

    def acceptance_records(
        self,
        *,
        asset_id: str | None,
        limit: int,
        offset: int,
    ) -> ProviderAcceptanceRecordListResponse:
        statement = select(ProviderAcceptanceRecord)
        count_statement = select(func.count()).select_from(ProviderAcceptanceRecord)
        if asset_id is not None:
            statement = statement.where(ProviderAcceptanceRecord.provider_asset_id == asset_id)
            count_statement = count_statement.where(
                ProviderAcceptanceRecord.provider_asset_id == asset_id
            )
        records = list(
            self.session.scalars(
                statement.order_by(
                    ProviderAcceptanceRecord.recorded_at.desc(),
                    ProviderAcceptanceRecord.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )
        return ProviderAcceptanceRecordListResponse(
            items=[self._acceptance_response(record) for record in records],
            total=int(self.session.scalar(count_statement) or 0),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def _acceptance_response(
        record: ProviderAcceptanceRecord,
    ) -> ProviderAcceptanceRecordResponse:
        return ProviderAcceptanceRecordResponse(
            id=record.id,
            run_id=record.run_id,
            provider_asset_id=record.provider_asset_id,
            provider_id=record.provider_id,
            model_id=record.model_id,
            checkpoint_sha256=record.checkpoint_sha256,
            device=record.device,
            runtime_versions=record.runtime_versions_json,
            load_result=record.load_result,
            inference_result=record.inference_result,
            unload_result=record.unload_result,
            peak_memory_bytes=record.peak_memory_bytes,
            execution_time_ms=record.execution_time_ms,
            warnings=record.warnings_json,
            failure_reason=record.failure_reason,
            test_input_identifier=record.test_input_identifier,
            details=record.details_json,
            validation_kind="software_acceptance",
            recorded_at=record.recorded_at,
        )

    def persist_acceptance(
        self,
        *,
        asset: ProviderModelAsset,
        run_id: str,
        device: str,
        runtime_versions: dict[str, str],
        load_result: str,
        inference_result: str,
        unload_result: str,
        peak_memory_bytes: int | None,
        execution_time_ms: int,
        warnings: list[str],
        failure_reason: str | None,
        test_input_identifier: str,
        details: dict[str, Any],
    ) -> ProviderAcceptanceRecord:
        record = ProviderAcceptanceRecord(
            id=str(uuid4()),
            run_id=run_id,
            provider_asset_id=asset.id,
            provider_id=asset.provider_id,
            model_id=asset.model_id,
            checkpoint_sha256=asset.checkpoint_sha256,
            device=device,
            runtime_versions_json=runtime_versions,
            load_result=load_result,
            inference_result=inference_result,
            unload_result=unload_result,
            peak_memory_bytes=peak_memory_bytes,
            execution_time_ms=execution_time_ms,
            warnings_json=warnings,
            failure_reason=failure_reason,
            test_input_identifier=test_input_identifier,
            details_json=json.loads(json.dumps(details, default=str)),
            validation_kind="software_acceptance",
            recorded_at=_utc_now(),
        )
        self.session.add(record)
        self.session.commit()
        return record

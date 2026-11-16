"""Versioned, atomic ReefPose checkpoint persistence."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import torch

from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.model import ReefPoseConfig, ReefPoseS
from reefvision.ml.reefpose.schema import AnatomySchema

CHECKPOINT_FORMAT = "reefpose-checkpoint-0001"


class StatefulScaler(Protocol):
    def state_dict(self) -> dict[str, Any]: ...

    def load_state_dict(self, state_dict: dict[str, Any]) -> None: ...


def _safe_metadata(value: Any, *, label: str) -> Any:
    """Normalize metadata to base JSON scalar/container types for safe loading."""

    if value is None:
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReefPoseValidationError(f"Checkpoint {label} contains a non-finite value")
        return float(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_metadata(item, label=label) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_metadata(item, label=label) for item in value]
    raise ReefPoseValidationError(
        f"Checkpoint {label} contains unsupported metadata type {type(value).__name__}"
    )


@dataclass(slots=True)
class CheckpointState:
    model: ReefPoseS
    schema: AnatomySchema
    epoch: int
    global_step: int
    metrics: dict[str, float]
    optimizer_state: dict[str, Any] | None
    scaler_state: dict[str, Any] | None
    training_config: dict[str, Any]
    reproducibility: dict[str, Any]
    created_at: str


def save_checkpoint(
    path: Path,
    *,
    model: ReefPoseS,
    schema: AnatomySchema,
    epoch: int,
    global_step: int,
    metrics: dict[str, float] | None = None,
    optimizer: torch.optim.Optimizer | None = None,
    scaler: StatefulScaler | None = None,
    training_config: dict[str, Any] | None = None,
    reproducibility: dict[str, Any] | None = None,
) -> None:
    if model.config.num_keypoints != schema.keypoint_count:
        raise ReefPoseValidationError("Checkpoint model and anatomy landmark counts differ")
    if epoch < -1 or global_step < 0:
        raise ReefPoseValidationError("Checkpoint epoch or global step is invalid")
    if path.suffix.casefold() not in {".pt", ".pth"}:
        raise ReefPoseValidationError("ReefPose checkpoints must use .pt or .pth")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": CHECKPOINT_FORMAT,
        "architecture": model.architecture_name,
        "architecture_version": model.architecture_version,
        "model_config": model.config.to_dict(),
        "model_state": model.state_dict(),
        "anatomy_schema": schema.to_dict(),
        "anatomy_integrity_hash": schema.integrity_hash,
        "epoch": epoch,
        "global_step": global_step,
        "metrics": {str(key): float(value) for key, value in (metrics or {}).items()},
        "optimizer_state": optimizer.state_dict() if optimizer is not None else None,
        "scaler_state": scaler.state_dict() if scaler is not None else None,
        "training_config": _safe_metadata(dict(training_config or {}), label="training config"),
        "reproducibility": _safe_metadata(dict(reproducibility or {}), label="reproducibility"),
        "created_at": datetime.now(UTC).isoformat(),
    }
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        torch.save(payload, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_checkpoint(
    path: Path,
    *,
    device: torch.device | str = "cpu",
    model: ReefPoseS | None = None,
    optimizer: torch.optim.Optimizer | None = None,
    scaler: StatefulScaler | None = None,
    expected_schema_hash: str | None = None,
) -> CheckpointState:
    if not path.is_file():
        raise ReefPoseValidationError("ReefPose checkpoint does not exist")
    try:
        payload = torch.load(path, map_location=device, weights_only=True)
    except Exception as exc:
        raise ReefPoseValidationError("ReefPose checkpoint could not be read safely") from exc
    if not isinstance(payload, dict) or payload.get("format") != CHECKPOINT_FORMAT:
        raise ReefPoseValidationError("Unsupported ReefPose checkpoint format")
    if payload.get("architecture") != ReefPoseS.architecture_name:
        raise ReefPoseValidationError("Unsupported ReefPose checkpoint architecture")
    try:
        schema_payload = payload["anatomy_schema"]
        config_payload = payload["model_config"]
        if not isinstance(schema_payload, dict) or not isinstance(config_payload, dict):
            raise TypeError
        schema = AnatomySchema.from_dict(schema_payload)
        serialized_schema_hash = schema_payload.get("integrity_hash")
        valid_schema_hashes = {schema.integrity_hash}
        if isinstance(serialized_schema_hash, str):
            valid_schema_hashes.add(serialized_schema_hash)
        if payload.get("anatomy_integrity_hash") not in valid_schema_hashes:
            raise ReefPoseValidationError("Checkpoint anatomy integrity hash does not match")
        if expected_schema_hash is not None and expected_schema_hash not in valid_schema_hashes:
            raise ReefPoseValidationError("Checkpoint anatomy differs from the expected schema")
        config = ReefPoseConfig.from_dict(config_payload)
        if config.num_keypoints != schema.keypoint_count:
            raise ReefPoseValidationError("Checkpoint model and anatomy landmark counts differ")
        resolved_model = model or ReefPoseS(config)
        if resolved_model.config != config:
            raise ReefPoseValidationError("Checkpoint model configuration does not match")
        resolved_model.load_state_dict(payload["model_state"], strict=True)
        optimizer_state = payload.get("optimizer_state")
        scaler_state = payload.get("scaler_state")
        if optimizer is not None and optimizer_state is not None:
            optimizer.load_state_dict(optimizer_state)
        if scaler is not None and scaler_state is not None:
            scaler.load_state_dict(scaler_state)
        raw_metrics = payload.get("metrics", {})
        raw_training_config = payload.get("training_config", {})
        raw_reproducibility = payload.get("reproducibility", {})
        if not all(
            isinstance(item, dict)
            for item in (raw_metrics, raw_training_config, raw_reproducibility)
        ):
            raise TypeError
        return CheckpointState(
            model=resolved_model,
            schema=schema,
            epoch=int(payload.get("epoch", -2)),
            global_step=int(payload.get("global_step", -1)),
            metrics={str(key): float(value) for key, value in raw_metrics.items()},
            optimizer_state=optimizer_state,
            scaler_state=scaler_state,
            training_config=dict(raw_training_config),
            reproducibility=dict(raw_reproducibility),
            created_at=str(payload.get("created_at", "")),
        )
    except ReefPoseValidationError:
        raise
    except Exception as exc:
        raise ReefPoseValidationError("ReefPose checkpoint contents are invalid") from exc

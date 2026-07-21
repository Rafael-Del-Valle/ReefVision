"""Deterministic provider checkpoint and runtime verification helpers."""

from __future__ import annotations

import hashlib
import importlib.util
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from reefvision.ml.provider_contract import (
    CheckpointKind,
    DeviceMode,
    ProviderDiagnosis,
    ProviderFileRecord,
    ProviderModelDefinition,
    ProviderVerification,
)

_PACKAGE_IMPORTS = {
    "segment-anything": "segment_anything",
    "opencv-python": "cv2",
    "pillow": "PIL",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def folder_checksum(files: tuple[ProviderFileRecord, ...]) -> str:
    """Hash relative names, sizes, and file digests into one stable folder identity."""

    digest = hashlib.sha256()
    for item in sorted(files, key=lambda value: value.relative_path.casefold()):
        digest.update(item.relative_path.replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item.size_bytes).encode("ascii"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def resolve_managed_relative_path(root: Path, relative_path: str) -> Path | None:
    """Resolve an untrusted manifest path only when it remains below ``root``."""

    raw = Path(relative_path)
    if raw.is_absolute():
        return None
    resolved_root = root.resolve()
    candidate = (resolved_root / raw).resolve(strict=False)
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        return None
    return candidate


def _verify_directory(model: ProviderModelDefinition) -> ProviderVerification:
    root = model.checkpoint_path
    if not root.exists():
        return ProviderVerification(
            status="missing",
            verified=False,
            checkpoint_exists=False,
            expected_sha256=model.checkpoint_sha256,
            observed_sha256=None,
            size_bytes=None,
            expected_size_bytes=model.checkpoint_size_bytes,
            failure_reason="The registered checkpoint directory is missing.",
        )
    if not root.is_dir():
        return ProviderVerification(
            status="wrong_type",
            verified=False,
            checkpoint_exists=True,
            expected_sha256=model.checkpoint_sha256,
            observed_sha256=None,
            size_bytes=None,
            expected_size_bytes=model.checkpoint_size_bytes,
            failure_reason="The registered folder checkpoint is not a directory.",
        )

    observed: list[ProviderFileRecord] = []
    warnings: list[str] = []
    for expected in model.file_manifest:
        candidate = resolve_managed_relative_path(root, expected.relative_path)
        if candidate is None:
            return ProviderVerification(
                status="unsafe_path",
                verified=False,
                checkpoint_exists=True,
                expected_sha256=model.checkpoint_sha256,
                observed_sha256=None,
                size_bytes=None,
                expected_size_bytes=model.checkpoint_size_bytes,
                failure_reason=(
                    f"Folder manifest path escapes the checkpoint root: {expected.relative_path}"
                ),
            )
        if not candidate.is_file():
            return ProviderVerification(
                status="missing",
                verified=False,
                checkpoint_exists=True,
                expected_sha256=model.checkpoint_sha256,
                observed_sha256=None,
                size_bytes=None,
                expected_size_bytes=model.checkpoint_size_bytes,
                failure_reason=f"Required checkpoint file is missing: {expected.relative_path}",
            )
        size = candidate.stat().st_size
        digest = sha256_file(candidate)
        observed.append(
            ProviderFileRecord(
                relative_path=expected.relative_path,
                size_bytes=size,
                sha256=digest,
            )
        )
        if size != expected.size_bytes or digest != expected.sha256:
            warnings.append(f"Checksum or size mismatch: {expected.relative_path}")

    records = tuple(observed)
    observed_digest = folder_checksum(records)
    total_size = sum(item.size_bytes for item in records)
    expected_digest = model.checkpoint_sha256 or folder_checksum(model.file_manifest)
    size_matches = model.checkpoint_size_bytes is None or total_size == model.checkpoint_size_bytes
    verified = not warnings and observed_digest == expected_digest and size_matches
    if not size_matches:
        warnings.append("Checkpoint folder byte size does not match the registered manifest size.")
    return ProviderVerification(
        status=(
            "verified" if verified else "size_mismatch" if not size_matches else "checksum_mismatch"
        ),
        verified=verified,
        checkpoint_exists=True,
        expected_sha256=expected_digest,
        observed_sha256=observed_digest,
        size_bytes=total_size,
        expected_size_bytes=model.checkpoint_size_bytes,
        files=records,
        warnings=tuple(warnings),
        failure_reason=None if verified else "Folder checkpoint verification failed.",
    )


def verify_checkpoint(model: ProviderModelDefinition) -> ProviderVerification:
    """Verify a file or multi-file checkpoint without importing its provider."""

    if model.checkpoint_kind is CheckpointKind.DIRECTORY:
        return _verify_directory(model)
    path = model.checkpoint_path
    if not path.exists():
        return ProviderVerification(
            status="missing",
            verified=False,
            checkpoint_exists=False,
            expected_sha256=model.checkpoint_sha256,
            observed_sha256=None,
            size_bytes=None,
            expected_size_bytes=model.checkpoint_size_bytes,
            failure_reason="The registered checkpoint file is missing.",
        )
    if not path.is_file():
        return ProviderVerification(
            status="wrong_type",
            verified=False,
            checkpoint_exists=True,
            expected_sha256=model.checkpoint_sha256,
            observed_sha256=None,
            size_bytes=None,
            expected_size_bytes=model.checkpoint_size_bytes,
            failure_reason="The registered file checkpoint is not a regular file.",
        )
    observed = sha256_file(path)
    size = path.stat().st_size
    checksum_matches = model.checkpoint_sha256 is None or observed == model.checkpoint_sha256
    size_matches = model.checkpoint_size_bytes is None or size == model.checkpoint_size_bytes
    verified = checksum_matches and size_matches
    return ProviderVerification(
        status=(
            "verified" if verified else "size_mismatch" if not size_matches else "checksum_mismatch"
        ),
        verified=verified,
        checkpoint_exists=True,
        expected_sha256=model.checkpoint_sha256,
        observed_sha256=observed,
        size_bytes=size,
        expected_size_bytes=model.checkpoint_size_bytes,
        files=(ProviderFileRecord(relative_path=path.name, size_bytes=size, sha256=observed),),
        failure_reason=(
            None
            if verified
            else "Checkpoint byte size does not match registration."
            if not size_matches
            else "Checkpoint checksum does not match registration."
        ),
    )


def _requirement_name(requirement: str) -> str:
    for separator in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        if separator in requirement:
            return requirement.split(separator, 1)[0].strip()
    return requirement.strip()


def _runtime_versions(requirements: tuple[str, ...]) -> tuple[dict[str, str], list[str]]:
    observed: dict[str, str] = {}
    missing: list[str] = []
    for requirement in requirements:
        package = _requirement_name(requirement)
        import_name = _PACKAGE_IMPORTS.get(package, package.replace("-", "_"))
        if importlib.util.find_spec(import_name) is None:
            missing.append(requirement)
            continue
        try:
            observed[package] = version(package)
        except PackageNotFoundError:
            observed[package] = "installed"
    return observed, missing


def resolve_device(requested: DeviceMode | str) -> str:
    normalized = str(requested).strip().casefold()
    if normalized.startswith("devicemode."):
        normalized = normalized.split(".", 1)[1]
    if normalized in {"", "auto"}:
        try:
            import torch

            return "cuda:0" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"
    if normalized == "cpu":
        return "cpu"
    if normalized in {"cuda", "cuda:0", "gpu"}:
        try:
            import torch
        except Exception as exc:
            raise RuntimeError(f"CUDA was requested but PyTorch is unavailable: {exc}") from exc
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but no CUDA device is available")
        return "cuda:0"
    raise ValueError("Supported device modes are auto, cpu, and cuda")


def diagnose_model(
    model: ProviderModelDefinition,
    requested_device: DeviceMode | str,
) -> ProviderDiagnosis:
    versions, missing = _runtime_versions(model.required_packages)
    if missing:
        return ProviderDiagnosis(
            ready=False,
            resolved_device=None,
            runtime_versions=versions,
            missing_packages=tuple(missing),
            failure_reason="Missing required provider packages: " + ", ".join(missing),
        )
    try:
        resolved = resolve_device(requested_device)
    except (RuntimeError, ValueError) as exc:
        return ProviderDiagnosis(
            ready=False,
            resolved_device=None,
            runtime_versions=versions,
            failure_reason=str(exc),
        )
    device_kind = DeviceMode.CUDA if resolved.startswith("cuda") else DeviceMode.CPU
    if device_kind not in model.supported_devices:
        return ProviderDiagnosis(
            ready=False,
            resolved_device=resolved,
            runtime_versions=versions,
            failure_reason=f"{model.model_id} does not support {device_kind.value} execution.",
        )
    return ProviderDiagnosis(
        ready=True,
        resolved_device=resolved,
        runtime_versions=versions,
    )

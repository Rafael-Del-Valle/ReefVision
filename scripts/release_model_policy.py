"""Offline release validation for catalog definitions and intended model resources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

MODEL_POLICY = "architecture_first_no_pretrained_weights"
WEIGHT_SUFFIXES = {
    ".pt",
    ".pth",
    ".ckpt",
    ".safetensors",
    ".engine",
    ".onnx",
    ".bin",
    ".h5",
    ".hdf5",
    ".pb",
    ".tflite",
}
MODEL_DIRECTORIES = {
    "models",
    "bundled-models",
    "provider-models",
    "catalog-models",
    "checkpoints",
    "weights",
}
ACQUISITION_STATUSES = {"base_bundled_checkpoint", "optional_network_download"}
# SentencePiece 0.2.1 Unicode normalization character maps, not trained checkpoints.
# Verified with SentencePieceNormalizer(rule_name=...) on full-width ABC input.
# Exact paths AND hashes are required; there is no generic .bin/.pth exemption.
NON_MODEL_RUNTIME_ASSETS = {
    "sentencepiece/package_data/nfkc_cf.bin": (
        "60833ec11201446659c3549c183b18f024c4007628cc6b3a4e91ae007697b826"
    ),
    "sentencepiece/package_data/nfkc.bin": (
        "52f11028ff8a7df3e009d94a8b6a54d4a8a17132efb4ccc1c9a0a41e432bd91e"
    ),
    "sentencepiece/package_data/nmt_nfkc_cf.bin": (
        "22c292c76f503795f30c85d79d30a7f572fff4f49e00392d2d60f4f93e941a1e"
    ),
    "sentencepiece/package_data/nmt_nfkc.bin": (
        "79372c41389c2b9b29bc171017ab5400e352debd686b02670a42bec709015074"
    ),
}


def audit_catalog(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise RuntimeError(f"Invalid model catalog: {path}")
    failures = []
    for entry in payload["models"]:
        if not isinstance(entry, dict):
            failures.append("malformed catalog entry")
            continue
        identifier = entry.get("catalog_id", "unknown")
        if entry.get("selection_kind") == "managed_catalog_model":
            failures.append(f"{identifier}: downloadable managed catalog model")
        if entry.get("desktop_package_status") in ACQUISITION_STATUSES:
            failures.append(f"{identifier}: weight acquisition package status")
        if entry.get("expected_files"):
            failures.append(f"{identifier}: weight installation manifest must be empty")
        for field in ("source_url", "checkpoint_url", "download_url", "pretrained_source_url"):
            if entry.get(field):
                failures.append(f"{identifier}: automatic source in {field}")
        for field in (
            "auto_download",
            "auto_install",
            "requires_auto_install",
            "pretrained_weights",
        ):
            if entry.get(field) is True:
                failures.append(f"{identifier}: {field} enabled")
        for field in ("checkpoint_source", "download_source_type"):
            if entry.get(field) in {
                "trusted_https_release",
                "huggingface",
                "huggingface_hub",
                "url",
            }:
                failures.append(f"{identifier}: acquisition source in {field}")
        if entry.get("selection_kind") == "architecture":
            for field in ("architecture_id", "architecture_config", "config_identifier"):
                value = str(entry.get(field) or "")
                if any(suffix.lower() in WEIGHT_SUFFIXES for suffix in Path(value).suffixes):
                    failures.append(f"{identifier}: architecture references trained weights")
    if failures:
        raise RuntimeError(
            "Model catalog violates the no-pretrained policy:\n" + "\n".join(failures)
        )
    return payload


def audit_manifest(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("manifest_version") != 1
        or payload.get("model_policy") != MODEL_POLICY
        or payload.get("assets") != {}
        or payload.get("provider_assets") != {}
        or any(
            payload.get(key) != 0
            for key in ("asset_count", "provider_asset_count", "total_size_bytes")
        )
    ):
        raise RuntimeError(f"Model manifest must declare the empty weight-free policy: {path}")


def audit_model_root(root: Path) -> None:
    """Strict recursive validation of an explicitly designated model resource directory."""
    if root.is_symlink() or getattr(root, "is_junction", lambda: False)():
        raise RuntimeError(f"Model resource links are not permitted: {root}")
    if not root.is_dir():
        raise RuntimeError(f"Model bundle directory is missing: {root}")
    for path in root.rglob("*"):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise RuntimeError(f"Model resource links are not permitted: {path}")
        if path.is_file() and any(suffix.lower() in WEIGHT_SUFFIXES for suffix in path.suffixes):
            raise RuntimeError(f"Prohibited model weight asset: {path}")
        if path.is_file() and path.name == "manifest.json":
            audit_manifest(path)


def audit_runtime_root(root: Path) -> None:
    """Reject weight formats except specifically verified non-model runtime assets."""
    if not root.is_dir():
        raise RuntimeError(f"Packaged runtime directory is missing: {root}")
    for path in root.rglob("*"):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise RuntimeError(f"Packaged resource links are not permitted: {path}")
        if path.is_dir() and path.name.lower() in MODEL_DIRECTORIES:
            audit_model_root(path)
        if path.is_file() and any(suffix.lower() in WEIGHT_SUFFIXES for suffix in path.suffixes):
            verified_nonmodel = any(
                path.as_posix().endswith("/" + relative)
                and hashlib.sha256(path.read_bytes()).hexdigest() == expected
                for relative, expected in NON_MODEL_RUNTIME_ASSETS.items()
            )
            if not verified_nonmodel:
                raise RuntimeError(f"Prohibited runtime model weight asset: {path}")
        if path.is_file() and path.name == "model_catalog.json":
            audit_catalog(path)

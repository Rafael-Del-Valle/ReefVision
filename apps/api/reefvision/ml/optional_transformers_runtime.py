"""Opt-in, revision-pinned local runtime for large optional Transformers models."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError


@dataclass(frozen=True, slots=True)
class OptionalModelSpec:
    provider_id: str
    display_name: str
    repo_id: str
    revision: str
    weight_filename: str
    weight_sha256: str | None
    allow_patterns: tuple[str, ...]
    license_summary: str


OPTIONAL_MODEL_SPECS: dict[str, OptionalModelSpec] = {
    "grounding_dino": OptionalModelSpec(
        provider_id="grounding_dino",
        display_name="Grounding DINO Tiny",
        repo_id="IDEA-Research/grounding-dino-tiny",
        revision="a2bb814dd30d776dcf7e30523b00659f4f141c71",
        weight_filename="model.safetensors",
        weight_sha256="1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3",
        allow_patterns=(
            "config.json",
            "model.safetensors",
            "preprocessor_config.json",
            "added_tokens.json",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.txt",
        ),
        license_summary=(
            "Apache-2.0 upstream model repository; verify use requirements for research deployment."
        ),
    ),
    "sam2": OptionalModelSpec(
        provider_id="sam2",
        display_name="SAM 2.1 Hiera Small",
        repo_id="facebook/sam2.1-hiera-small",
        revision="e07df6aa19f5c6545121551bf89957b7663ee715",
        weight_filename="model.safetensors",
        weight_sha256="0a4067b11ce1e23d5229203f11c718a823060d15a4b23fa2372a7d4b77cbbc60",
        allow_patterns=(
            "config.json",
            "model.safetensors",
            "preprocessor_config.json",
            "processor_config.json",
            "video_preprocessor_config.json",
        ),
        license_summary="Apache-2.0 upstream model repository.",
    ),
    "smolvlm": OptionalModelSpec(
        provider_id="smolvlm",
        display_name="SmolVLM 256M Instruct",
        repo_id="HuggingFaceTB/SmolVLM-256M-Instruct",
        revision="cee7dc33d83ff2ddec17238b7aba85145169e631",
        weight_filename="model.safetensors",
        weight_sha256="74dea5904032e5ae99a2e0eef5179e6ac0f1dedc3ab0c7c2a5d4d387c843203e",
        allow_patterns=(
            "config.json",
            "generation_config.json",
            "model.safetensors",
            "preprocessor_config.json",
            "processor_config.json",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
        ),
        license_summary="Apache-2.0 upstream model repository.",
    ),
    "video_depth_anything": OptionalModelSpec(
        provider_id="video_depth_anything",
        display_name="Metric Video Depth Anything Small",
        repo_id="depth-anything/Metric-Video-Depth-Anything-Small",
        revision="273d090f2ce17df50c2872d82c8322c45da5b4dd",
        weight_filename="metric_video_depth_anything_vits.pth",
        weight_sha256="3c28432b4e1f0d7bb31cad5151b6313b49457db5aa58d82e85bfb0f8b1311b33",
        allow_patterns=("metric_video_depth_anything_vits.pth",),
        license_summary=(
            "Apache-2.0 Metric Video Depth Anything Small checkpoint. "
            "Model-estimated metric depth requires underwater validation before "
            "ReefVision may present it as calibrated physical measurement."
        ),
    ),
    "scale_label_ocr": OptionalModelSpec(
        provider_id="scale_label_ocr",
        display_name="TrOCR Small Printed",
        repo_id="microsoft/trocr-small-printed",
        revision="f9cfe12588652d93a67f197794a0f0da1b52e19f",
        weight_filename="model.safetensors",
        weight_sha256="49350a39968df83e5a1adc90fc0ede02ff247671aed70b842af350fd4a7103f3",
        allow_patterns=(
            "config.json",
            "generation_config.json",
            "model.safetensors",
            "preprocessor_config.json",
            "sentencepiece.bpe.model",
            "special_tokens_map.json",
            "tokenizer_config.json",
            "vocab.json",
            "merges.txt",
        ),
        license_summary="MIT upstream model repository.",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def optional_model_root(settings: Settings, provider_id: str) -> Path:
    return settings.resolved_data_dir / "provider-models" / provider_id


def _manifest_path(settings: Settings, provider_id: str) -> Path:
    return optional_model_root(settings, provider_id) / ".reefvision-model.json"


def _transformers_version() -> str | None:
    try:
        return version("transformers")
    except PackageNotFoundError:
        return None


def _weight_matches_spec(path: Path, spec: OptionalModelSpec) -> bool:
    if not path.is_file():
        return False
    if spec.weight_sha256 is None:
        return True
    try:
        resolved_name = path.resolve().name.casefold()
    except OSError:
        resolved_name = ""
    if resolved_name == spec.weight_sha256.casefold():
        return True
    return _sha256(path) == spec.weight_sha256


def _cached_huggingface_snapshot(spec: OptionalModelSpec) -> Path | None:
    try:
        from huggingface_hub import snapshot_download
    except Exception:
        return None
    try:
        cached = Path(
            snapshot_download(
                repo_id=spec.repo_id,
                revision=spec.revision,
                allow_patterns=list(spec.allow_patterns),
                local_files_only=True,
            )
        )
    except Exception:
        return None
    weight = cached / spec.weight_filename
    return cached if _weight_matches_spec(weight, spec) else None


def remove_optional_model_cache(settings: Settings, provider_id: str) -> None:
    spec = OPTIONAL_MODEL_SPECS.get(provider_id)
    if spec is None:
        raise ValidationError(f"Unknown optional model provider: {provider_id}")

    shutil.rmtree(optional_model_root(settings, provider_id), ignore_errors=True)

    try:
        from huggingface_hub import scan_cache_dir

        cache = scan_cache_dir()
        revisions: list[str] = []
        for repo in cache.repos:
            if repo.repo_type == "model" and repo.repo_id == spec.repo_id:
                for revision in repo.revisions:
                    if revision.commit_hash == spec.revision:
                        revisions.append(revision.commit_hash)
        if revisions:
            cache.delete_revisions(*revisions).execute()
    except Exception:
        return


def optional_model_status(settings: Settings, provider_id: str) -> dict[str, Any]:
    spec = OPTIONAL_MODEL_SPECS.get(provider_id)
    if spec is None:
        raise ValidationError(f"Unknown optional model provider: {provider_id}")

    target = optional_model_root(settings, provider_id)
    local_weight = target / spec.weight_filename
    manifest = _manifest_path(settings, provider_id)
    transformers_version = _transformers_version()

    cached_path: Path | None = None
    cache_source: str | None = None
    verified = False
    reason: str | None = None

    if local_weight.is_file():
        cached_path = target
        cache_source = "reefvision"
        if not manifest.is_file():
            reason = "Model files exist but ReefVision provenance metadata is missing."
        else:
            try:
                stored = json.loads(manifest.read_text(encoding="utf-8"))
                stored_model = stored.get("model", {})
                provenance_ok = (
                    stored_model.get("repo_id") == spec.repo_id
                    and stored_model.get("revision") == spec.revision
                    and stored_model.get("weight_sha256") == spec.weight_sha256
                )
                if provenance_ok and _weight_matches_spec(local_weight, spec):
                    verified = True
                elif not provenance_ok:
                    reason = (
                        "Cached model provenance does not match the pinned "
                        "ReefVision specification."
                    )
                else:
                    reason = "Cached model weight checksum is invalid."
            except (OSError, ValueError, TypeError):
                reason = "Cached model provenance metadata could not be validated."
    else:
        external = _cached_huggingface_snapshot(spec)
        if external is not None:
            cached_path = external
            cache_source = "huggingface"
            verified = True
        else:
            reason = "Optional model is not cached yet."

    ready = verified and transformers_version is not None
    if verified and transformers_version is None:
        reason = "The model is cached and verified, but Transformers is unavailable."

    return {
        "provider_id": provider_id,
        "repo_id": spec.repo_id,
        "revision": spec.revision,
        "transformers_version": transformers_version,
        "cached": cached_path is not None,
        "verified": verified,
        "ready": ready,
        "path": str(cached_path or target),
        "cache_source": cache_source,
        "reason": reason,
        "license_summary": spec.license_summary,
    }


def ensure_optional_model(
    settings: Settings,
    provider_id: str,
    *,
    allow_download: bool,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    spec = OPTIONAL_MODEL_SPECS.get(provider_id)
    if spec is None:
        raise ValidationError(f"Unknown optional model provider: {provider_id}")
    if _transformers_version() is None:
        raise ValidationError("Transformers is required for this provider runtime")

    status = optional_model_status(settings, provider_id)
    if status["ready"]:
        existing = Path(str(status["path"]))
        weight = existing / spec.weight_filename
        if _weight_matches_spec(weight, spec):
            return existing

    target = optional_model_root(settings, provider_id)
    if target.exists() and any(target.iterdir()) and not allow_download:
        raise ValidationError(
            status["reason"]
            or (
                "The optional model cache is incomplete. Enable explicit model "
                "download to repair it."
            )
        )
    if not allow_download:
        raise ValidationError(
            "This optional model is not installed. Install it from Models & AI "
            "→ Model Hub before running this provider."
        )

    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import snapshot_download
        from tqdm.auto import tqdm  # type: ignore[import-untyped]
    except Exception as exc:
        raise ValidationError(f"huggingface_hub download runtime is unavailable: {exc}") from exc

    class _ReefVisionSnapshotProgress(tqdm):  # type: ignore[misc]
        def update(self, n: int | float = 1) -> bool | None:
            result = super().update(n)
            if progress_callback is not None:
                total = int(self.total or 0)
                current = min(int(self.n), total) if total > 0 else int(self.n)
                progress_callback(current, total)
            return result  # type: ignore[no-any-return]

    try:
        snapshot_download(
            repo_id=spec.repo_id,
            revision=spec.revision,
            local_dir=target,
            allow_patterns=list(spec.allow_patterns),
            local_files_only=False,
            max_workers=4,
            tqdm_class=_ReefVisionSnapshotProgress,
        )
    except Exception as exc:
        raise ValidationError(
            f"Could not download the pinned {spec.display_name} files: {exc}"
        ) from exc

    weight = target / spec.weight_filename
    if not weight.is_file():
        raise ValidationError(f"Downloaded {spec.display_name} is missing {spec.weight_filename}")
    if not _weight_matches_spec(weight, spec):
        shutil.rmtree(target, ignore_errors=True)
        raise ValidationError(
            f"Downloaded {spec.display_name} failed checksum verification; the cache was removed."
        )

    _manifest_path(settings, provider_id).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model": asdict(spec),
                "transformers_version": _transformers_version(),
                "cache_source": "reefvision",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def resolve_torch_device(requested: str) -> str:
    try:
        import torch
    except Exception as exc:
        raise ValidationError(f"PyTorch is unavailable: {exc}") from exc
    normalized = requested.strip().lower()
    if normalized in {"", "auto"}:
        return "cuda" if torch.cuda.is_available() else "cpu"
    if normalized in {"cuda", "cuda:0", "0"}:
        if not torch.cuda.is_available():
            raise ValidationError("CUDA was requested but is not available")
        return "cuda"
    if normalized == "cpu":
        return "cpu"
    raise ValidationError("Supported devices are auto, cpu, and cuda")

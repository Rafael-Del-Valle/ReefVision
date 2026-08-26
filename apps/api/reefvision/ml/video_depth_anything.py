"""Pinned Metric Video Depth Anything Small runtime for ReefVision Scientific 3D."""

from __future__ import annotations

import gc
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.ml.optional_transformers_runtime import OPTIONAL_MODEL_SPECS, ensure_optional_model

PROVIDER_ID = "video_depth_anything"
UPSTREAM_SOURCE_COMMIT = "4f5ae23172ba60fd7bc11ef671cca678842c7072"
UPSTREAM_SOURCE_LICENSE = "Apache-2.0"
MODEL_CONFIG = {
    "encoder": "vits",
    "features": 64,
    "out_channels": [48, 96, 192, 384],
}


@dataclass(slots=True)
class VideoMetricDepthInference:
    depths: NDArray[np.float32]
    fps: float
    input_size_used: int
    device: str
    model_repo: str
    model_revision: str
    model_sha256: str | None
    source_commit: str | None
    decoded_frame_count: int
    warnings: list[str]


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _packaged_source_root() -> Path | None:
    bundle_root = vars(sys).get("_MEIPASS")
    if not bundle_root:
        return None
    return Path(str(bundle_root)).resolve() / "provider-runtime" / "video-depth-anything" / "source"


def validate_video_depth_anything_source(source_root: Path) -> Path:
    resolved = source_root.expanduser().resolve()
    architecture = resolved / "video_depth_anything" / "video_depth.py"
    temporal = resolved / "video_depth_anything" / "dpt_temporal.py"
    license_path = resolved / "LICENSE"
    manifest_path = resolved.parent / "source-manifest.json"

    if not architecture.is_file():
        raise ValidationError("Pinned Video Depth Anything source is missing video_depth.py")
    if not temporal.is_file():
        raise ValidationError("Pinned Video Depth Anything source is missing dpt_temporal.py")
    if not license_path.is_file():
        raise ValidationError("Pinned Video Depth Anything source is missing LICENSE")
    if not manifest_path.is_file():
        raise ValidationError("Pinned Video Depth Anything source provenance manifest is missing")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValidationError(
            "Pinned Video Depth Anything source provenance manifest is invalid"
        ) from exc

    if manifest.get("provider") != "video_depth_anything":
        raise ValidationError("Pinned Video Depth Anything source manifest has the wrong provider")
    if manifest.get("commit") != UPSTREAM_SOURCE_COMMIT:
        raise ValidationError("Pinned Video Depth Anything source commit does not match ReefVision")
    if manifest.get("license") != UPSTREAM_SOURCE_LICENSE:
        raise ValidationError(
            "Pinned Video Depth Anything source license does not match ReefVision"
        )

    compatibility = manifest.get("reefvision_compatibility_patch")
    if (
        not isinstance(compatibility, dict)
        or compatibility.get("upstream_behavior_preserved") is not True
    ):
        raise ValidationError(
            "Pinned Video Depth Anything ReefVision compatibility provenance is missing"
        )

    license_text = license_path.read_text(
        encoding="utf-8",
        errors="replace",
    )
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        raise ValidationError("Pinned Video Depth Anything source LICENSE is not Apache-2.0")

    temporal_text = temporal.read_text(
        encoding="utf-8",
        errors="replace",
    )
    if "EasyDict" in temporal_text:
        raise ValidationError("Pinned Video Depth Anything source still requires EasyDict")
    if "motion_module_kwargs = dict(" not in temporal_text:
        raise ValidationError("Pinned Video Depth Anything compatibility patch is not present")

    return resolved


def _source_root(settings: Settings) -> Path:
    candidates: list[Path] = []

    configured = os.environ.get("REEFVISION_VIDEO_DEPTH_ANYTHING_SOURCE")
    if configured:
        candidates.append(Path(configured).expanduser())

    packaged = _packaged_source_root()
    if packaged is not None:
        candidates.append(packaged)

    candidates.extend(
        [
            settings.resolved_data_dir / "provider-runtime" / "video-depth-anything" / "source",
            _repository_root()
            / ".desktop"
            / "provider-runtime"
            / "video-depth-anything"
            / "source",
        ]
    )

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if (resolved / "video_depth_anything" / "video_depth.py").is_file():
            return validate_video_depth_anything_source(resolved)

    raise ValidationError(
        "Pinned Video Depth Anything source is unavailable. Packaged ReefVision "
        "builds include the pinned source automatically; source-development "
        "builds must install the pinned source and ReefVision compatibility "
        "patch before Scientific 3D inference."
    )


def _source_commit(source_root: Path) -> str | None:
    manifest = source_root.parent / "source-manifest.json"
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    commit = payload.get("commit")
    return str(commit) if commit else None


def _resolve_device(requested: str) -> str:
    import torch

    normalized = requested.strip().casefold()
    if normalized in {"", "auto"}:
        return "cuda" if torch.cuda.is_available() else "cpu"
    if normalized.startswith("cuda"):
        if not torch.cuda.is_available():
            raise ValidationError("CUDA was requested for Scientific 3D but is unavailable")
        return "cuda"
    if normalized == "cpu":
        return "cpu"
    raise ValidationError("Scientific 3D device must be auto, cpu, or cuda")


def _read_video_frames(video_path: Path, max_res: int) -> NDArray[np.uint8]:
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValidationError("Managed video could not be opened for metric depth inference")
    frames: list[NDArray[np.uint8]] = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width = frame.shape[:2]
            if max(height, width) > max_res:
                scale = max_res / max(height, width)
                resized_width = max(2, round(width * scale))
                resized_height = max(2, round(height * scale))
                frame = cv2.resize(
                    frame,
                    (resized_width, resized_height),
                    interpolation=cv2.INTER_AREA,
                )
            frames.append(np.asarray(frame, dtype=np.uint8))
    finally:
        capture.release()
    if not frames:
        raise ValidationError("Managed video contains no decodable frames")
    return np.stack(frames, axis=0)


def _fallback_input_sizes(requested: int, enabled: bool) -> list[int]:
    sizes = [requested]
    if not enabled:
        return sizes
    for candidate in (448, 392, 336):
        if candidate < requested and candidate not in sizes:
            sizes.append(candidate)
    return sizes


class MetricVideoDepthAnythingProvider:
    provider_id = PROVIDER_ID
    provider_version = "4f5ae23172ba60fd7bc11ef671cca678842c7072"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def infer(
        self,
        video_path: Path,
        *,
        expected_frame_count: int,
        expected_fps: float,
        input_size: int,
        max_res: int,
        device: str,
        allow_model_download: bool,
        allow_resolution_fallback: bool,
    ) -> VideoMetricDepthInference:
        import torch

        source_root = _source_root(self.settings)
        spec = OPTIONAL_MODEL_SPECS[PROVIDER_ID]
        model_root = ensure_optional_model(
            self.settings,
            PROVIDER_ID,
            allow_download=allow_model_download,
        )
        checkpoint = model_root / spec.weight_filename
        if not checkpoint.is_file():
            raise ValidationError(
                "Verified Metric Video Depth Anything Small checkpoint is missing"
            )

        frames = _read_video_frames(video_path, max_res)
        warnings: list[str] = []
        if frames.shape[0] != expected_frame_count:
            warnings.append(
                "Decoded frame count differs from container metadata: "
                f"decoded={frames.shape[0]}, metadata={expected_frame_count}."
            )

        resolved_device = _resolve_device(device)
        previous_path = list(sys.path)
        model: Any | None = None
        try:
            sys.path.insert(0, str(source_root))
            from video_depth_anything.video_depth import (  # type: ignore[import-not-found]
                VideoDepthAnything,
            )

            model = VideoDepthAnything(**MODEL_CONFIG, metric=True)
            state = torch.load(checkpoint, map_location="cpu", weights_only=True)
            model.load_state_dict(state, strict=True)
            model = model.to(resolved_device).eval()

            last_error: RuntimeError | None = None
            for candidate_size in _fallback_input_sizes(input_size, allow_resolution_fallback):
                try:
                    depths, fps = model.infer_video_depth(
                        frames,
                        expected_fps,
                        input_size=candidate_size,
                        device=resolved_device,
                        fp32=resolved_device != "cuda",
                    )
                    if candidate_size != input_size:
                        warnings.append(
                            "CUDA memory fallback reduced Video Depth Anything input_size "
                            f"from {input_size} to {candidate_size}."
                        )
                    return VideoMetricDepthInference(
                        depths=np.asarray(depths, dtype=np.float32),
                        fps=float(fps),
                        input_size_used=candidate_size,
                        device=resolved_device,
                        model_repo=spec.repo_id,
                        model_revision=spec.revision,
                        model_sha256=spec.weight_sha256,
                        source_commit=_source_commit(source_root),
                        decoded_frame_count=int(frames.shape[0]),
                        warnings=warnings,
                    )
                except RuntimeError as exc:
                    if resolved_device != "cuda" or "out of memory" not in str(exc).casefold():
                        raise
                    last_error = exc
                    torch.cuda.empty_cache()
            raise ValidationError(
                "Metric Video Depth Anything exhausted CUDA memory at all configured "
                "Scientific 3D fallback resolutions."
            ) from last_error
        finally:
            sys.path[:] = previous_path
            if model is not None:
                del model
            del frames
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

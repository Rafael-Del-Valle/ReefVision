"""Optional SLEAP-NN pose registration and video-inference helpers."""

from __future__ import annotations

import json
import math
import shutil
import zipfile
from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, TypedDict

from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import (
    DetectionModelMetadata,
    DetectionPrediction,
    DetectionSettings,
)

SLEAP_NN_PROVIDER_ID = "sleap_nn"
SLEAP_NN_SUPPORTED_VERSION = "0.3.3"
SLEAP_IO_SUPPORTED_VERSION = "0.9.2"
SLEAP_BUNDLE_FORMAT = "reefvision_sleap_nn"
SLEAP_BUNDLE_MANIFEST = "reefvision-sleap-nn-model.json"


class SleapNNRuntimeStatus(TypedDict):
    ready: bool
    sleap_nn_version: str | None
    sleap_io_version: str | None
    issues: list[str]


@dataclass(frozen=True)
class SleapNNBundleManifest:
    class_name: str
    model_paths: tuple[str, ...]
    landmark_labels: tuple[str, ...]
    instance_mode: str
    provider_version: str


def _installed_version(distribution: str) -> str | None:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def sleap_nn_runtime_status() -> SleapNNRuntimeStatus:
    nn_version = _installed_version("sleap-nn")
    io_version = _installed_version("sleap-io")
    ready = (
        nn_version == SLEAP_NN_SUPPORTED_VERSION
        and io_version == SLEAP_IO_SUPPORTED_VERSION
    )
    issues: list[str] = []
    if nn_version != SLEAP_NN_SUPPORTED_VERSION:
        issues.append(
            f"sleap-nn {SLEAP_NN_SUPPORTED_VERSION} is required "
            f"(found {nn_version or 'missing'})"
        )
    if io_version != SLEAP_IO_SUPPORTED_VERSION:
        issues.append(
            f"sleap-io {SLEAP_IO_SUPPORTED_VERSION} is required "
            f"(found {io_version or 'missing'})"
        )
    return {
        "ready": ready,
        "sleap_nn_version": nn_version,
        "sleap_io_version": io_version,
        "issues": issues,
    }


def _safe_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValidationError("SLEAP-NN bundle contains an unsafe archive path")
    return normalized


def read_sleap_nn_bundle_manifest(bundle_path: Path) -> SleapNNBundleManifest:
    if not bundle_path.is_file() or bundle_path.suffix.casefold() != ".zip":
        raise ValidationError("SLEAP-NN registration requires a ReefVision .zip bundle")
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            names = {_safe_member_name(item.filename) for item in archive.infolist()}
            if SLEAP_BUNDLE_MANIFEST not in names:
                raise ValidationError(
                    f"SLEAP-NN bundle is missing {SLEAP_BUNDLE_MANIFEST}"
                )
            raw = json.loads(archive.read(SLEAP_BUNDLE_MANIFEST).decode("utf-8"))
    except ValidationError:
        raise
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("SLEAP-NN bundle metadata is invalid") from exc

    if not isinstance(raw, dict) or raw.get("format") != SLEAP_BUNDLE_FORMAT:
        raise ValidationError("The selected ZIP is not a ReefVision SLEAP-NN bundle")
    if raw.get("provider_id") != SLEAP_NN_PROVIDER_ID:
        raise ValidationError("SLEAP-NN bundle provider metadata is invalid")

    class_name = str(raw.get("class_name") or "").strip()
    if not class_name:
        raise ValidationError("SLEAP-NN bundle class_name is required")

    model_paths_raw = raw.get("model_paths")
    if not isinstance(model_paths_raw, list) or len(model_paths_raw) not in {1, 2}:
        raise ValidationError("SLEAP-NN bundle requires one or two model_paths")
    model_paths = tuple(str(item).strip().strip("/") for item in model_paths_raw)
    if any(not item or ".." in Path(item).parts for item in model_paths):
        raise ValidationError("SLEAP-NN bundle model_paths are invalid")

    labels_raw = raw.get("landmark_labels")
    if not isinstance(labels_raw, list) or not labels_raw:
        raise ValidationError("SLEAP-NN bundle landmark_labels are required")
    landmark_labels = tuple(str(item).strip() for item in labels_raw)
    if any(not item for item in landmark_labels):
        raise ValidationError("SLEAP-NN landmark labels cannot be blank")

    instance_mode = str(raw.get("instance_mode") or "multi").strip().casefold()
    if instance_mode not in {"single", "multi"}:
        raise ValidationError("SLEAP-NN instance_mode must be single or multi")

    provider_version = str(
        raw.get("provider_version") or SLEAP_NN_SUPPORTED_VERSION
    ).strip()
    if provider_version != SLEAP_NN_SUPPORTED_VERSION:
        raise ValidationError(
            "SLEAP-NN bundle provider_version must match the validated "
            f"{SLEAP_NN_SUPPORTED_VERSION} runtime"
        )

    with zipfile.ZipFile(bundle_path) as archive:
        archive_names = [
            _safe_member_name(item.filename) for item in archive.infolist()
        ]
        for model_path in model_paths:
            prefix = model_path.rstrip("/") + "/"
            children = [
                name for name in archive_names if name.startswith(prefix)
            ]
            if not children:
                raise ValidationError(
                    f"SLEAP-NN model directory is missing from bundle: {model_path}"
                )
            basenames = {Path(name).name for name in children}
            if "best.ckpt" not in basenames:
                raise ValidationError(
                    f"SLEAP-NN model directory lacks best.ckpt: {model_path}"
                )
            if not {"training_config.yaml", "training_config.json"} & basenames:
                raise ValidationError(
                    "SLEAP-NN model directory lacks training_config.yaml/json: "
                    f"{model_path}"
                )

    return SleapNNBundleManifest(
        class_name=class_name,
        model_paths=model_paths,
        landmark_labels=landmark_labels,
        instance_mode=instance_mode,
        provider_version=provider_version,
    )


def extract_sleap_nn_bundle(
    bundle_path: Path,
) -> tuple[SleapNNBundleManifest, tuple[Path, ...]]:
    manifest = read_sleap_nn_bundle_manifest(bundle_path)
    destination = bundle_path.parent / f".{bundle_path.stem}.bundle"
    if destination.is_dir():
        resolved = tuple(destination / item for item in manifest.model_paths)
        if all(path.is_dir() for path in resolved):
            return manifest, resolved
        shutil.rmtree(destination, ignore_errors=True)

    temporary = Path(mkdtemp(prefix=f".{bundle_path.stem}.", dir=bundle_path.parent))
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            for item in archive.infolist():
                name = _safe_member_name(item.filename)
                target = (temporary / name).resolve()
                if not target.is_relative_to(temporary.resolve()):
                    raise ValidationError("SLEAP-NN bundle path escaped extraction root")
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return manifest, tuple(destination / item for item in manifest.model_paths)


def normalize_sleap_keypoints(raw_points: Any) -> tuple[tuple[float, float, float], ...]:
    rows = raw_points.tolist() if hasattr(raw_points, "tolist") else list(raw_points)
    normalized: list[tuple[float, float, float]] = []
    for row in rows:
        values = list(row)
        if len(values) < 2:
            normalized.append((0.0, 0.0, 0.0))
            continue
        x = float(values[0])
        y = float(values[1])
        confidence = float(values[2]) if len(values) >= 3 else 1.0
        if (
            not math.isfinite(x)
            or not math.isfinite(y)
            or not math.isfinite(confidence)
            or x < 0
            or y < 0
            or confidence <= 0
        ):
            normalized.append((0.0, 0.0, 0.0))
            continue
        normalized.append((x, y, min(confidence, 1.0)))
    return tuple(normalized)


def keypoint_bbox(
    keypoints: tuple[tuple[float, float, float], ...],
) -> tuple[float, float, float, float] | None:
    visible = [(x, y) for x, y, confidence in keypoints if confidence > 0]
    if not visible:
        return None
    xs = [point[0] for point in visible]
    ys = [point[1] for point in visible]
    x_min = max(0.0, min(xs) - 1.0)
    y_min = max(0.0, min(ys) - 1.0)
    x_max = max(xs) + 1.0
    y_max = max(ys) + 1.0
    return x_min, y_min, max(1.0, x_max - x_min), max(1.0, y_max - y_min)


class SleapNNPoseRegistrationProvider:
    provider_name = SLEAP_NN_PROVIDER_ID
    provider_version = SLEAP_NN_SUPPORTED_VERSION

    def inspect_model(self, model_path: Path) -> DetectionModelMetadata:
        manifest = read_sleap_nn_bundle_manifest(model_path)
        return DetectionModelMetadata(
            framework="sleap_nn",
            task="pose",
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            class_labels=[manifest.class_name],
            input_size=None,
            metadata={
                "trusted_checkpoint": True,
                "automatic_downloads_disabled": True,
                "explicit_checkpoint_required": True,
                "registered_execution_runtime": "pytorch",
                "proposal_geometry": "keypoints+derived_bbox",
                "pose_keypoint_shape": [len(manifest.landmark_labels), 3],
                "pose_landmark_labels": list(manifest.landmark_labels),
                "sleap_instance_mode": manifest.instance_mode,
                "sleap_model_paths": list(manifest.model_paths),
                "sleap_bundle_format": SLEAP_BUNDLE_FORMAT,
            },
        )

    def load_model(self, model_path: Path, device: str) -> None:
        del device
        read_sleap_nn_bundle_manifest(model_path)

    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[DetectionPrediction]:
        del image_path, settings
        raise ValidationError(
            "SLEAP-NN pose execution is exposed through ReefVision video tracking"
        )

    def unload_model(self) -> None:
        return


def require_sleap_nn_runtime() -> None:
    status = sleap_nn_runtime_status()
    if status["ready"]:
        return
    raise ValidationError(
        "SLEAP-NN optional runtime is not ready: "
        + "; ".join(str(item) for item in status["issues"])
    )


def sleap_predictor_types() -> tuple[Any, Any]:
    require_sleap_nn_runtime()
    try:
        inference = import_module("sleap_nn.inference")
        tracking = import_module("sleap_nn.inference.tracking")
    except Exception as exc:
        raise ValidationError(f"SLEAP-NN runtime could not be imported: {exc}") from exc
    return inference.Predictor, tracking.TrackerConfig

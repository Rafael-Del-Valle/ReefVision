"""Provider-neutral still-image pose evaluation runtimes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from reefvision.db.models import ModelRegistration
from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import resolve_torch_device
from reefvision.ml.sleap_nn_provider import sleap_nn_runtime_status


@dataclass(frozen=True, slots=True)
class PoseEvaluationLandmark:
    landmark_id: str
    name: str
    occurrence_index: int


@dataclass(frozen=True, slots=True)
class PoseEvaluationSchema:
    schema_id: str
    revision: int
    content_hash: str
    landmarks: tuple[PoseEvaluationLandmark, ...]


@dataclass(frozen=True, slots=True)
class NormalizedLandmarkPrediction:
    landmark_id: str
    name: str
    occurrence_index: int
    x: float
    y: float
    confidence: float
    visibility_state: str


@dataclass(frozen=True, slots=True)
class NormalizedPosePrediction:
    landmarks: tuple[NormalizedLandmarkPrediction, ...]
    bbox: tuple[float, float, float, float] | None
    schema_id: str
    schema_revision: int
    native_integrity_hash: str | None


class PoseEvaluationProviderExclusion(ValidationError):
    """A provider/model cannot be scored without fabricating comparable output."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PoseEvaluationRuntime(Protocol):
    resolved_device: str
    visibility_metrics_available: bool

    def predict(self, image: Image.Image) -> NormalizedPosePrediction: ...

    def close(self) -> None: ...


def _reefpose_predictor_from_checkpoint(path: Path, *, device: str) -> Any:
    from reefvision.ml.reefpose.inference import ReefPosePredictor

    return ReefPosePredictor.from_checkpoint(path, device=device)


def _load_ultralytics_model(path: Path) -> Any:
    try:
        from ultralytics import YOLO  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - depends on optional runtime
        raise PoseEvaluationProviderExclusion(
            "provider_runtime_unavailable",
            f"Ultralytics evaluation runtime is unavailable: {exc}",
        ) from exc
    return YOLO(str(path))


def _resolve_ultralytics_device(device: str) -> str | int:
    return resolve_torch_device(device)


def _close_torch_runtime() -> None:
    try:  # pragma: no cover - cache cleanup depends on CUDA availability
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


class _ReefPoseEvaluationRuntime:
    visibility_metrics_available = True

    def __init__(
        self,
        model: ModelRegistration,
        checkpoint_path: Path,
        schema: PoseEvaluationSchema,
        device: str,
    ) -> None:
        self._model = model
        self._schema = schema
        self._predictor = _reefpose_predictor_from_checkpoint(checkpoint_path, device=device)
        self.resolved_device = str(self._predictor.device)

    def predict(self, image: Image.Image) -> NormalizedPosePrediction:
        prediction = self._predictor.predict(image, confidence_threshold=0.0)
        if (
            prediction.anatomy_schema_id != self._schema.schema_id
            or int(prediction.anatomy_schema_revision) != self._schema.revision
        ):
            raise PoseEvaluationProviderExclusion(
                "schema_mismatch",
                "The ReefPose checkpoint prediction schema does not match the evaluation schema",
            )
        expected_hash = str(
            (self._model.metadata_json or {}).get("reefpose_anatomy_integrity_hash") or ""
        )
        if expected_hash and prediction.anatomy_integrity_hash != expected_hash:
            raise PoseEvaluationProviderExclusion(
                "checkpoint_integrity_mismatch",
                "The ReefPose checkpoint anatomy integrity hash does not match registration",
            )
        return NormalizedPosePrediction(
            landmarks=tuple(
                NormalizedLandmarkPrediction(
                    landmark_id=str(item.landmark_id),
                    name=str(item.name),
                    occurrence_index=int(item.occurrence_index),
                    x=float(item.x),
                    y=float(item.y),
                    confidence=float(item.confidence),
                    visibility_state=str(item.visibility_state),
                )
                for item in prediction.landmarks
            ),
            bbox=(
                (
                    float(prediction.bbox[0]),
                    float(prediction.bbox[1]),
                    float(prediction.bbox[2]),
                    float(prediction.bbox[3]),
                )
                if prediction.bbox is not None
                else None
            ),
            schema_id=str(prediction.anatomy_schema_id),
            schema_revision=int(prediction.anatomy_schema_revision),
            native_integrity_hash=str(prediction.anatomy_integrity_hash),
        )

    def close(self) -> None:
        self._predictor = None
        _close_torch_runtime()


class _UltralyticsEvaluationRuntime:
    visibility_metrics_available = False

    def __init__(
        self,
        checkpoint_path: Path,
        schema: PoseEvaluationSchema,
        device: str,
    ) -> None:
        self._schema = schema
        self._model = _load_ultralytics_model(checkpoint_path)
        if str(getattr(self._model, "task", "pose")) != "pose":
            raise PoseEvaluationProviderExclusion(
                "incompatible_model_task",
                "The registered Ultralytics checkpoint is not a pose model",
            )
        self._device = _resolve_ultralytics_device(device)
        self.resolved_device = "cuda:0" if self._device == 0 else str(self._device)

    def predict(self, image: Image.Image) -> NormalizedPosePrediction:
        results = self._model.predict(
            source=np.asarray(image.convert("RGB")),
            conf=0.0,
            device=self._device,
            verbose=False,
        )
        if len(results) != 1:
            raise PoseEvaluationProviderExclusion(
                "invalid_provider_output",
                "Ultralytics returned an invalid result count for one image",
            )
        result = results[0]
        keypoints = getattr(result, "keypoints", None)
        xy_tensor = getattr(keypoints, "xy", None)
        rows = xy_tensor.tolist() if xy_tensor is not None else []
        if not rows:
            return NormalizedPosePrediction(
                landmarks=(),
                bbox=None,
                schema_id=self._schema.schema_id,
                schema_revision=self._schema.revision,
                native_integrity_hash=None,
            )
        if len(rows) != 1:
            raise PoseEvaluationProviderExclusion(
                "multiple_animals",
                "Single-animal evaluation cannot score multiple Ultralytics instances",
            )
        points = rows[0]
        if len(points) != len(self._schema.landmarks):
            raise PoseEvaluationProviderExclusion(
                "landmark_count_mismatch",
                "Ultralytics output landmark count does not match the evaluation schema",
            )
        confidence_tensor = getattr(keypoints, "conf", None)
        confidence_rows = confidence_tensor.tolist() if confidence_tensor is not None else []
        confidences = confidence_rows[0] if confidence_rows else [1.0] * len(points)
        landmarks: list[NormalizedLandmarkPrediction] = []
        for index, (definition, point) in enumerate(
            zip(self._schema.landmarks, points, strict=True)
        ):
            x, y = float(point[0]), float(point[1])
            confidence = float(confidences[index]) if index < len(confidences) else 1.0
            if not all(math.isfinite(value) for value in (x, y, confidence)):
                raise PoseEvaluationProviderExclusion(
                    "invalid_provider_output",
                    "Ultralytics returned a non-finite keypoint",
                )
            landmarks.append(
                NormalizedLandmarkPrediction(
                    landmark_id=definition.landmark_id,
                    name=definition.name,
                    occurrence_index=definition.occurrence_index,
                    x=x,
                    y=y,
                    confidence=max(0.0, min(1.0, confidence)),
                    visibility_state="visible" if confidence > 0 else "absent",
                )
            )
        boxes = getattr(getattr(result, "boxes", None), "xyxy", None)
        box_rows = boxes.tolist() if boxes is not None else []
        bbox = None
        if box_rows:
            if len(box_rows[0]) != 4:
                raise PoseEvaluationProviderExclusion(
                    "invalid_provider_output",
                    "Ultralytics returned an invalid instance bounding box",
                )
            bbox = (
                float(box_rows[0][0]),
                float(box_rows[0][1]),
                float(box_rows[0][2]),
                float(box_rows[0][3]),
            )
        return NormalizedPosePrediction(
            landmarks=tuple(landmarks),
            bbox=bbox,
            schema_id=self._schema.schema_id,
            schema_revision=self._schema.revision,
            native_integrity_hash=None,
        )

    def close(self) -> None:
        self._model = None
        _close_torch_runtime()


def create_pose_evaluation_runtime(
    model: ModelRegistration,
    checkpoint_path: Path,
    schema: PoseEvaluationSchema,
    device: str,
) -> PoseEvaluationRuntime:
    provider = str(model.provider_name).strip().casefold()
    if provider == "reefpose":
        return _ReefPoseEvaluationRuntime(model, checkpoint_path, schema, device)
    if provider == "ultralytics":
        return _UltralyticsEvaluationRuntime(checkpoint_path, schema, device)
    if provider == "sleap_nn":
        status = sleap_nn_runtime_status()
        if not status["ready"]:
            raise PoseEvaluationProviderExclusion(
                "provider_runtime_unavailable",
                "SLEAP-NN evaluation runtime is unavailable: "
                + "; ".join(str(issue) for issue in status["issues"]),
            )
        raise PoseEvaluationProviderExclusion(
            "still_frame_unsupported",
            "SLEAP-NN still-image evaluation is not supported by the validated runtime adapter",
        )
    raise PoseEvaluationProviderExclusion(
        "unsupported_provider",
        f"Pose evaluation does not support provider {model.provider_name!r}",
    )

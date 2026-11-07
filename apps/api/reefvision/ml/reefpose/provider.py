"""ReefVision provider adapter for native ReefPose checkpoints."""

from __future__ import annotations

from pathlib import Path

from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import (
    DetectionModelMetadata,
    DetectionPrediction,
    DetectionSettings,
    PixelBox,
    PoseKeypointPrediction,
    require_local_checkpoint_path,
)
from reefvision.ml.reefpose.checkpoints import load_checkpoint
from reefvision.ml.reefpose.errors import ReefPoseError
from reefvision.ml.reefpose.inference import ReefPosePredictor

REEFPOSE_PROVIDER_ID = "reefpose"
REEFPOSE_PROVIDER_VERSION = "1.0"


def _validation_error(exc: Exception) -> ValidationError:
    return ValidationError(f"ReefPose checkpoint is invalid: {exc}")


class ReefPoseRegistrationProvider:
    """Register and execute trusted local ReefPose-S checkpoints."""

    provider_name = REEFPOSE_PROVIDER_ID
    provider_version = REEFPOSE_PROVIDER_VERSION

    def __init__(self) -> None:
        self._predictor: ReefPosePredictor | None = None
        self._class_label = "animal"

    def inspect_model(self, model_path: Path) -> DetectionModelMetadata:
        require_local_checkpoint_path(
            model_path,
            provider_label="ReefPose",
            allowed_suffixes={".pt", ".pth"},
        )
        try:
            state = load_checkpoint(model_path, device="cpu")
        except ReefPoseError as exc:
            raise _validation_error(exc) from exc
        class_label = str(state.training_config.get("class_label") or "animal").strip()
        if not class_label:
            raise ValidationError("ReefPose checkpoint class_label cannot be blank")
        schema = state.schema
        return DetectionModelMetadata(
            framework="reefpose",
            task="pose",
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            class_labels=[class_label],
            input_size={
                "width": state.model.config.input_width,
                "height": state.model.config.input_height,
            },
            metadata={
                "trusted_checkpoint": True,
                "automatic_downloads_disabled": True,
                "explicit_checkpoint_required": True,
                "registered_execution_runtime": "pytorch",
                "proposal_geometry": "keypoints+derived_bbox",
                "architecture": state.model.architecture_name,
                "architecture_version": state.model.architecture_version,
                "pose_keypoint_shape": [schema.keypoint_count, 3],
                "pose_landmark_labels": list(schema.expanded_names),
                "reefpose_anatomy_schema": schema.to_dict(),
                "reefpose_anatomy_integrity_hash": schema.integrity_hash,
                "checkpoint_epoch": state.epoch,
                "checkpoint_global_step": state.global_step,
            },
        )

    def load_model(self, model_path: Path, device: str) -> None:
        require_local_checkpoint_path(
            model_path,
            provider_label="ReefPose",
            allowed_suffixes={".pt", ".pth"},
        )
        try:
            state = load_checkpoint(model_path, device="cpu")
            self._class_label = str(
                state.training_config.get("class_label") or "animal"
            ).strip()
            self._predictor = ReefPosePredictor.from_checkpoint(model_path, device=device)
        except ReefPoseError as exc:
            raise _validation_error(exc) from exc

    def predict(
        self,
        image_path: Path,
        settings: DetectionSettings,
    ) -> list[DetectionPrediction]:
        if self._predictor is None:
            raise ValidationError("The ReefPose model is not loaded")
        try:
            pose = self._predictor.predict(
                image_path,
                confidence_threshold=settings.confidence_threshold,
            )
        except ReefPoseError as exc:
            raise ValidationError(f"ReefPose inference failed: {exc}") from exc
        if pose.bbox is None:
            return []
        x_min, y_min, x_max, y_max = pose.bbox
        keypoints = tuple(
            PoseKeypointPrediction(
                landmark_id=item.landmark_id,
                name=item.name,
                occurrence_index=item.occurrence_index,
                x=item.x,
                y=item.y,
                confidence=item.confidence,
                visibility_state=item.visibility_state,
            )
            for item in pose.landmarks
        )
        return [
            DetectionPrediction(
                label=self._class_label,
                class_index=0,
                confidence=pose.confidence,
                box=PixelBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
                keypoints=keypoints,
                pose_schema={
                    "schema_id": pose.anatomy_schema_id,
                    "schema_revision": pose.anatomy_schema_revision,
                    "content_hash": pose.anatomy_integrity_hash,
                },
            )
        ]

    def unload_model(self) -> None:
        self._predictor = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return


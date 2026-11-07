from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import torch
from PIL import Image

from reefvision.domain.errors import ValidationError
from reefvision.jobs.inference import _pose_prediction_provenance, _validate_model_prediction
from reefvision.ml.provider_hub import (
    detection_provider_for_name,
    get_model_provider,
    provider_for_registration,
)
from reefvision.ml.providers import DetectionSettings, PixelBox, PoseKeypointPrediction
from reefvision.ml.reefpose.checkpoints import save_checkpoint
from reefvision.ml.reefpose.model import ReefPoseConfig, ReefPoseS
from reefvision.ml.reefpose.provider import REEFPOSE_PROVIDER_ID, ReefPoseRegistrationProvider
from reefvision.ml.reefpose.schema import AnatomySchema, LandmarkDefinition


def _checkpoint(path: Path) -> None:
    schema = AnatomySchema(
        schema_id="reefpose-schema",
        name="Jellyfish",
        revision=4,
        landmarks=(
            LandmarkDefinition(landmark_id="bell", name="bell_center"),
            LandmarkDefinition(
                landmark_id="tentacle-0",
                name="tentacle",
                occurrence_index=0,
                group="appendages",
            ),
            LandmarkDefinition(
                landmark_id="tentacle-1",
                name="tentacle",
                occurrence_index=1,
                group="appendages",
            ),
        ),
    )
    model = ReefPoseS(
        ReefPoseConfig(
            num_keypoints=3,
            input_height=64,
            input_width=64,
            base_channels=8,
        )
    )
    visibility_layer = model.visibility_head[-1]
    assert isinstance(visibility_layer, torch.nn.Linear)
    torch.nn.init.zeros_(visibility_layer.weight)
    torch.nn.init.constant_(visibility_layer.bias, 10.0)
    save_checkpoint(
        path,
        model=model,
        schema=schema,
        epoch=0,
        global_step=1,
        training_config={"class_label": "jellyfish"},
    )


class ReefPoseProviderTests(unittest.TestCase):
    def test_checkpoint_inspection_and_inference_preserve_anatomy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            checkpoint = root / "reefpose.pt"
            image_path = root / "animal.png"
            _checkpoint(checkpoint)
            Image.new("RGB", (100, 50), color=(40, 80, 120)).save(image_path)
            provider = ReefPoseRegistrationProvider()

            metadata = provider.inspect_model(checkpoint)
            provider.load_model(checkpoint, "cpu")
            predictions = provider.predict(
                image_path,
                DetectionSettings(confidence_threshold=0.0, iou_threshold=0.5, device="cpu"),
            )
            provider.unload_model()

            self.assertEqual(metadata.framework, "reefpose")
            self.assertEqual(metadata.task, "pose")
            self.assertEqual(metadata.provider_name, REEFPOSE_PROVIDER_ID)
            self.assertEqual(metadata.class_labels, ["jellyfish"])
            self.assertEqual(metadata.metadata["pose_keypoint_shape"], [3, 3])
            self.assertEqual(
                metadata.metadata["pose_landmark_labels"], ["bell_center", "tentacle", "tentacle"]
            )
            self.assertEqual(len(predictions), 1)
            self.assertEqual(len(predictions[0].keypoints or ()), 3)
            self.assertEqual(predictions[0].pose_schema["schema_revision"], 4)
            for keypoint in predictions[0].keypoints or ():
                self.assertGreaterEqual(keypoint.x, 0.0)
                self.assertLessEqual(keypoint.x, 100.0)
                self.assertGreaterEqual(keypoint.y, 0.0)
                self.assertLessEqual(keypoint.y, 50.0)

    def test_provider_hub_registers_native_reefpose(self) -> None:
        descriptor = get_model_provider(REEFPOSE_PROVIDER_ID)

        self.assertEqual(descriptor.supported_tasks, ("pose",))
        self.assertTrue(descriptor.training_support)
        self.assertTrue(descriptor.registerable)
        self.assertIsInstance(
            provider_for_registration("detector", provider_name=REEFPOSE_PROVIDER_ID),
            ReefPoseRegistrationProvider,
        )
        self.assertIsInstance(
            detection_provider_for_name(REEFPOSE_PROVIDER_ID),
            ReefPoseRegistrationProvider,
        )

    def test_pose_keypoints_are_validated_and_serialized_for_provenance(self) -> None:
        keypoint = PoseKeypointPrediction(
            landmark_id="bell",
            name="bell_center",
            occurrence_index=0,
            x=12.0,
            y=8.0,
            confidence=0.9,
            visibility_state="visible",
        )
        image = SimpleNamespace(width_px=20, height_px=10)

        _validate_model_prediction(
            image,
            label="jellyfish",
            class_index=0,
            confidence=0.9,
            box=PixelBox(1.0, 1.0, 18.0, 9.0),
            keypoints=(keypoint,),
        )
        provenance = _pose_prediction_provenance(
            (keypoint,),
            {"schema_id": "schema-1", "schema_revision": 1, "content_hash": "a" * 64},
        )
        self.assertEqual(provenance["pose_landmarks"][0]["landmark_id"], "bell")
        self.assertEqual(provenance["pose_schema"]["schema_id"], "schema-1")

        with self.assertRaisesRegex(ValidationError, "source image"):
            _validate_model_prediction(
                image,
                label="jellyfish",
                class_index=0,
                confidence=0.9,
                box=PixelBox(1.0, 1.0, 18.0, 9.0),
                keypoints=(
                    PoseKeypointPrediction(
                        landmark_id="bell",
                        name="bell_center",
                        occurrence_index=0,
                        x=21.0,
                        y=8.0,
                        confidence=0.9,
                        visibility_state="visible",
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import torch

from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.geometry import ImageTransform, letterbox_tensor
from reefvision.ml.reefpose.model import ReefPoseConfig, ReefPoseS


class ReefPoseModelTests(unittest.TestCase):
    def test_configurable_model_emits_multiscale_heatmaps_and_visibility(self) -> None:
        config = ReefPoseConfig(
            num_keypoints=7,
            input_height=128,
            input_width=160,
            base_channels=8,
        )
        model = ReefPoseS(config)
        inputs = torch.randn(2, 3, 128, 160)

        features = model.extract_features(inputs)
        output = model(inputs)

        self.assertEqual(len(features), 4)
        self.assertEqual([tuple(item.shape[-2:]) for item in features], [
            (32, 40),
            (16, 20),
            (8, 10),
            (4, 5),
        ])
        self.assertEqual(tuple(output.heatmaps.shape), (2, 7, 32, 40))
        self.assertEqual(tuple(output.visibility_logits.shape), (2, 7))

    def test_model_is_trainable_on_cpu(self) -> None:
        model = ReefPoseS(
            ReefPoseConfig(
                num_keypoints=3,
                input_height=64,
                input_width=64,
                base_channels=8,
            )
        )

        output = model(torch.randn(2, 3, 64, 64))
        loss = output.heatmaps.square().mean() + output.visibility_logits.square().mean()
        loss.backward()

        gradients = [parameter.grad for parameter in model.parameters() if parameter.requires_grad]
        self.assertTrue(gradients)
        self.assertTrue(all(gradient is not None for gradient in gradients))
        self.assertGreater(sum(parameter.numel() for parameter in model.parameters()), 10_000)

    def test_invalid_model_dimensions_fail_closed(self) -> None:
        with self.assertRaisesRegex(ReefPoseValidationError, "divisible"):
            ReefPoseConfig(num_keypoints=2, input_height=65, input_width=64)


class ImageGeometryTests(unittest.TestCase):
    def test_non_square_odd_image_coordinates_round_trip(self) -> None:
        transform = ImageTransform.for_source(
            source_width=101,
            source_height=57,
            input_width=160,
            input_height=128,
        )
        points = torch.tensor([[0.0, 0.0], [50.25, 27.5], [100.0, 56.0]])

        restored = transform.input_to_source(transform.source_to_input(points))

        torch.testing.assert_close(restored, points, atol=1e-5, rtol=0)
        self.assertEqual(transform.resized_width, 160)
        self.assertEqual(transform.resized_height, 90)
        self.assertEqual(transform.pad_top + transform.pad_bottom, 38)

    def test_crop_and_heatmap_coordinates_restore_to_full_source(self) -> None:
        transform = ImageTransform.for_source(
            source_width=200,
            source_height=100,
            input_width=128,
            input_height=128,
            crop_box=(50.0, 20.0, 150.0, 80.0),
        )
        source_point = torch.tensor([[100.0, 50.0]])

        heatmap_point = transform.source_to_heatmap(source_point, 32, 32)
        restored = transform.heatmap_to_source(heatmap_point, 32, 32)

        torch.testing.assert_close(restored, source_point, atol=1e-5, rtol=0)

    def test_letterbox_tensor_matches_recorded_transform(self) -> None:
        source = torch.ones(3, 57, 101)
        resized, transform = letterbox_tensor(source, input_height=128, input_width=160)

        self.assertEqual(tuple(resized.shape), (3, 128, 160))
        self.assertEqual(float(resized[:, 0, :].sum()), 0.0)
        center = transform.source_to_input(torch.tensor([[50.0, 28.0]]))
        self.assertGreater(float(resized[:, int(center[0, 1]), int(center[0, 0])].sum()), 0.0)


if __name__ == "__main__":
    unittest.main()


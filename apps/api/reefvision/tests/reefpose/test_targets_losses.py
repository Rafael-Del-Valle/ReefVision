from __future__ import annotations

import unittest

import torch

from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.losses import ReefPoseLoss
from reefvision.ml.reefpose.model import ReefPoseOutput
from reefvision.ml.reefpose.targets import generate_gaussian_heatmaps


class GaussianTargetTests(unittest.TestCase):
    def test_gaussian_peaks_at_landmark_and_visibility_controls_weight(self) -> None:
        targets = generate_gaussian_heatmaps(
            torch.tensor([[3.0, 4.0], [6.0, 2.0], [0.0, 0.0]]),
            torch.tensor([2, 1, 0]),
            height=8,
            width=10,
            sigma=1.0,
        )

        self.assertEqual(tuple(targets.heatmaps.shape), (3, 8, 10))
        self.assertAlmostEqual(float(targets.heatmaps[0, 4, 3]), 1.0)
        self.assertAlmostEqual(float(targets.heatmaps[1, 2, 6]), 1.0)
        torch.testing.assert_close(targets.heatmap_weights, torch.tensor([1.0, 0.5, 0.0]))
        torch.testing.assert_close(targets.visibility_targets, torch.tensor([1.0, 1.0, 0.0]))
        self.assertEqual(float(targets.heatmaps[2].sum()), 0.0)

    def test_fractional_centers_are_not_rounded_before_gaussian_generation(self) -> None:
        targets = generate_gaussian_heatmaps(
            torch.tensor([[2.5, 2.5]]),
            torch.tensor([2]),
            height=6,
            width=6,
            sigma=1.0,
        )

        self.assertAlmostEqual(float(targets.heatmaps[0, 2, 2]), 0.7788008, places=5)
        self.assertAlmostEqual(float(targets.heatmaps[0, 3, 3]), 0.7788008, places=5)

    def test_visible_out_of_frame_point_is_rejected(self) -> None:
        with self.assertRaisesRegex(ReefPoseValidationError, "outside"):
            generate_gaussian_heatmaps(
                torch.tensor([[10.0, 1.0]]),
                torch.tensor([2]),
                height=8,
                width=10,
                sigma=1.0,
            )


class ReefPoseLossTests(unittest.TestCase):
    def test_absent_heatmap_is_masked_but_visibility_is_supervised(self) -> None:
        targets = generate_gaussian_heatmaps(
            torch.tensor([[2.0, 2.0], [0.0, 0.0]]),
            torch.tensor([2, 0]),
            height=4,
            width=4,
            sigma=1.0,
        ).batched()
        criterion = ReefPoseLoss(visibility_loss_weight=1.0)
        baseline = ReefPoseOutput(
            heatmaps=torch.zeros(1, 2, 4, 4),
            visibility_logits=torch.zeros(1, 2),
        )
        changed_absent_heatmap = ReefPoseOutput(
            heatmaps=torch.cat(
                [torch.zeros(1, 1, 4, 4), torch.full((1, 1, 4, 4), 20.0)], dim=1
            ),
            visibility_logits=torch.zeros(1, 2),
        )
        changed_visibility = ReefPoseOutput(
            heatmaps=torch.zeros(1, 2, 4, 4),
            visibility_logits=torch.tensor([[0.0, 10.0]]),
        )

        base_loss = criterion(baseline, targets)
        absent_loss = criterion(changed_absent_heatmap, targets)
        visibility_loss = criterion(changed_visibility, targets)

        self.assertAlmostEqual(float(base_loss.heatmap), float(absent_loss.heatmap), places=6)
        self.assertGreater(float(visibility_loss.visibility), float(base_loss.visibility))

    def test_loss_backward_produces_finite_gradients(self) -> None:
        targets = generate_gaussian_heatmaps(
            torch.tensor([[1.0, 1.0], [2.0, 2.0]]),
            torch.tensor([2, 1]),
            height=4,
            width=4,
            sigma=1.0,
        ).batched()
        heatmaps = torch.randn(1, 2, 4, 4, requires_grad=True)
        visibility = torch.randn(1, 2, requires_grad=True)

        result = ReefPoseLoss()(ReefPoseOutput(heatmaps, visibility), targets)
        result.total.backward()

        self.assertTrue(torch.isfinite(result.total))
        self.assertTrue(torch.isfinite(heatmaps.grad).all())
        self.assertTrue(torch.isfinite(visibility.grad).all())


if __name__ == "__main__":
    unittest.main()


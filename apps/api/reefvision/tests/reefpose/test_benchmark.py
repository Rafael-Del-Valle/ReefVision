from __future__ import annotations

import unittest

import torch

from reefvision.ml.reefpose.benchmark import BenchmarkConfig, run_benchmark
from reefvision.ml.reefpose.errors import ReefPoseValidationError
from reefvision.ml.reefpose.model import ReefPoseConfig


class ReefPoseBenchmarkTests(unittest.TestCase):
    def test_cpu_benchmark_reports_complete_synthetic_contract(self) -> None:
        result = run_benchmark(
            BenchmarkConfig(
                model=ReefPoseConfig(
                    num_keypoints=3,
                    input_height=64,
                    input_width=64,
                    base_channels=8,
                ),
                device="cpu",
                batch_size=1,
                warmup_iterations=1,
                inference_iterations=2,
                training_steps=2,
                seed=42,
            )
        )

        self.assertEqual(result["schema_version"], "reefpose-benchmark-0001")
        self.assertTrue(result["synthetic_fixture"])
        self.assertFalse(result["biological_accuracy_validated"])
        self.assertEqual(result["configuration"]["seed"], 42)
        self.assertEqual(result["runtime"]["device_type"], "cpu")
        self.assertGreater(result["model"]["parameter_count"], 10_000)
        self.assertGreater(result["inference"]["mean_latency_ms"], 0.0)
        self.assertGreater(result["inference"]["images_per_second"], 0.0)
        self.assertEqual(result["inference"]["peak_gpu_memory_bytes"], 0)
        self.assertGreater(result["training"]["steps_per_second"], 0.0)
        self.assertGreater(result["training"]["images_per_second"], 0.0)

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA is not available")
    def test_cuda_benchmark_reports_gpu_memory(self) -> None:
        result = run_benchmark(
            BenchmarkConfig(
                model=ReefPoseConfig(
                    num_keypoints=3,
                    input_height=64,
                    input_width=64,
                    base_channels=8,
                ),
                device="cuda",
                batch_size=2,
                warmup_iterations=1,
                inference_iterations=2,
                training_steps=2,
                seed=42,
            )
        )

        self.assertEqual(result["runtime"]["device_type"], "cuda")
        self.assertIn("RTX 3090", result["runtime"]["device_name"])
        self.assertGreater(result["inference"]["peak_gpu_memory_bytes"], 0)
        self.assertGreater(result["training"]["peak_gpu_memory_bytes"], 0)

    def test_invalid_benchmark_iterations_are_rejected(self) -> None:
        with self.assertRaisesRegex(ReefPoseValidationError, "iterations"):
            BenchmarkConfig(
                model=ReefPoseConfig(
                    num_keypoints=1,
                    input_height=64,
                    input_width=64,
                    base_channels=8,
                ),
                inference_iterations=0,
            )


if __name__ == "__main__":
    unittest.main()

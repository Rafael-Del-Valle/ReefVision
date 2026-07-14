"""nnU-Net v2 provider wrapper.

Runs the official command-line tools in a subprocess so nnU-Net remains isolated
from ReefVision's primary Python package graph.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from reefvision.ml.provider_contract import ProviderRequest, ProviderResult


class NnUNetV2Provider:
    provider_id = "nnunetv2"
    supported_tasks = frozenset({"semantic_segment", "nnunet_train"})

    def preflight(self, request: ProviderRequest) -> list[str]:
        blockers: list[str] = []
        if shutil.which("nnUNetv2_plan_and_preprocess") is None:
            blockers.append("nnUNetv2 command-line tools were not found.")
        for name in ("nnUNet_raw", "nnUNet_preprocessed", "nnUNet_results"):
            if not os.environ.get(name):
                blockers.append(f"Environment variable {name} is not configured.")
        return blockers

    def train(self, request: ProviderRequest) -> ProviderResult:
        blockers = self.preflight(request)
        if blockers:
            raise ValueError("; ".join(blockers))

        dataset_id = str(request.parameters["dataset_id"])
        configuration = str(request.parameters.get("configuration", "2d"))
        fold = str(request.parameters.get("fold", "0"))

        subprocess.run(
            ["nnUNetv2_plan_and_preprocess", "-d", dataset_id, "--verify_dataset_integrity"],
            check=True,
        )
        subprocess.run(
            ["nnUNetv2_train", dataset_id, configuration, fold],
            check=True,
        )
        return ProviderResult(
            artifacts={"results_root": os.environ["nnUNet_results"]},  # noqa: SIM112
            metadata={
                "provider": self.provider_id,
                "dataset_id": dataset_id,
                "configuration": configuration,
                "fold": fold,
            },
        )

    def infer(self, request: ProviderRequest) -> ProviderResult:
        blockers = self.preflight(request)
        if blockers:
            raise ValueError("; ".join(blockers))
        if request.source_path is None or request.output_dir is None:
            raise ValueError("Input and output directories are required.")

        dataset_id = str(request.parameters["dataset_id"])
        configuration = str(request.parameters.get("configuration", "2d"))
        fold = str(request.parameters.get("fold", "0"))
        subprocess.run(
            [
                "nnUNetv2_predict",
                "-i",
                str(request.source_path),
                "-o",
                str(request.output_dir),
                "-d",
                dataset_id,
                "-c",
                configuration,
                "-f",
                fold,
            ],
            check=True,
        )
        return ProviderResult(
            artifacts={"prediction_dir": str(request.output_dir)},
            metadata={"provider": self.provider_id},
        )

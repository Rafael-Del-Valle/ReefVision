"""Ultralytics adapter for detection, instance segmentation, classification, and tracking."""
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from pathlib import Path
from typing import Any

from reefvision.ml.provider_contract import ProviderRequest, ProviderResult


class UltralyticsMultitaskProvider:
    provider_id = "ultralytics"
    supported_tasks = frozenset({"detect", "instance_segment", "classify", "track"})

    def preflight(self, request: ProviderRequest) -> list[str]:
        if request.task not in self.supported_tasks:
            return [f"Unsupported Ultralytics task: {request.task}"]
        return []

    def train(self, request: ProviderRequest) -> ProviderResult:
        blockers = self.preflight(request)
        if blockers:
            raise ValueError("; ".join(blockers))
        if request.task == "track":
            raise ValueError("Tracking is inference-only; train the detector first.")
        if request.dataset_path is None:
            raise ValueError("A dataset path is required for training.")

        from ultralytics import YOLO

        parameters = dict(request.parameters)
        model_ref = (
            str(request.checkpoint_path)
            if request.checkpoint_path is not None
            else str(parameters.pop("architecture"))
        )
        yolo_task = {
            "detect": "detect",
            "instance_segment": "segment",
            "classify": "classify",
        }[request.task]
        model = YOLO(model_ref, task=yolo_task)
        result = model.train(
            data=str(request.dataset_path),
            project=str(request.output_dir) if request.output_dir else None,
            **parameters,
        )
        save_dir = Path(str(result.save_dir))
        best = save_dir / "weights" / "best.pt"
        return ProviderResult(
            artifacts={"run_dir": str(save_dir), "best_checkpoint": str(best)},
            metadata={"provider": self.provider_id, "task": request.task},
        )

    def infer(self, request: ProviderRequest) -> ProviderResult:
        blockers = self.preflight(request)
        if blockers:
            raise ValueError("; ".join(blockers))
        if request.checkpoint_path is None:
            raise ValueError("A checkpoint is required.")
        if request.source_path is None:
            raise ValueError("An image or video source is required.")

        from ultralytics import YOLO

        parameters = dict(request.parameters)
        model = YOLO(str(request.checkpoint_path))
        if request.task == "track":
            results: Any = model.track(
                source=str(request.source_path),
                persist=True,
                tracker=str(parameters.pop("tracker", "bytetrack.yaml")),
                project=str(request.output_dir) if request.output_dir else None,
                save=True,
                **parameters,
            )
        else:
            results = model.predict(
                source=str(request.source_path),
                project=str(request.output_dir) if request.output_dir else None,
                save=True,
                **parameters,
            )
        return ProviderResult(
            artifacts={"result_count": str(len(results))},
            metadata={"provider": self.provider_id, "task": request.task},
        )

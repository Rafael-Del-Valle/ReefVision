"""Native AdamW/AMP training loop for ReefPose-S."""

from __future__ import annotations

import json
import platform
import random
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch

from reefvision.ml.reefpose.checkpoints import load_checkpoint, save_checkpoint
from reefvision.ml.reefpose.errors import ReefPoseCancelledError, ReefPoseValidationError
from reefvision.ml.reefpose.losses import ReefPoseLoss
from reefvision.ml.reefpose.model import ReefPoseS
from reefvision.ml.reefpose.schema import AnatomySchema
from reefvision.ml.reefpose.targets import ReefPoseTargets

CancellationCheck = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class ReefPoseTrainingConfig:
    epochs: int = 50
    learning_rate: float = 3e-4
    weight_decay: float = 1e-4
    device: str = "auto"
    amp: bool = True
    seed: int = 1337
    output_dir: Path = Path("reefpose-run")
    gradient_clip_norm: float | None = 5.0
    heatmap_loss_weight: float = 1.0
    visibility_loss_weight: float = 0.1
    deterministic: bool = True

    def __post_init__(self) -> None:
        if self.epochs < 1:
            raise ReefPoseValidationError("ReefPose training epochs must be at least 1")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ReefPoseValidationError("ReefPose optimizer configuration is invalid")
        if self.gradient_clip_norm is not None and self.gradient_clip_norm <= 0:
            raise ReefPoseValidationError("Gradient clip norm must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "epochs": self.epochs,
            "learning_rate": self.learning_rate,
            "weight_decay": self.weight_decay,
            "device": self.device,
            "amp": self.amp,
            "seed": self.seed,
            "output_dir": str(self.output_dir),
            "gradient_clip_norm": self.gradient_clip_norm,
            "heatmap_loss_weight": self.heatmap_loss_weight,
            "visibility_loss_weight": self.visibility_loss_weight,
            "deterministic": self.deterministic,
        }


@dataclass(slots=True)
class ReefPoseTrainingResult:
    completed_epochs: int
    global_step: int
    last_checkpoint: Path
    best_checkpoint: Path
    metrics_history: list[dict[str, float]] = field(default_factory=list)


def resolve_device(requested: str) -> torch.device:
    normalized = requested.strip().casefold()
    if normalized in {"", "auto"}:
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if normalized == "cpu":
        return torch.device("cpu")
    if normalized in {"cuda", "cuda:0", "gpu", "0"}:
        if not torch.cuda.is_available():
            raise ReefPoseValidationError("CUDA was requested but is not available")
        return torch.device("cuda:0")
    if normalized.startswith("cuda:") and normalized[5:].isdigit():
        index = int(normalized[5:])
        if not torch.cuda.is_available() or index >= torch.cuda.device_count():
            raise ReefPoseValidationError("Requested CUDA device is not available")
        return torch.device(f"cuda:{index}")
    raise ReefPoseValidationError("ReefPose device must be auto, cpu, cuda, or cuda:N")


class ReefPoseTrainer:
    def __init__(
        self,
        model: ReefPoseS,
        schema: AnatomySchema,
        config: ReefPoseTrainingConfig,
    ) -> None:
        if model.config.num_keypoints != schema.keypoint_count:
            raise ReefPoseValidationError("ReefPose model and anatomy landmark counts differ")
        self.model = model
        self.schema = schema
        self.config = config
        self.device = resolve_device(config.device)
        self.amp_enabled = config.amp and self.device.type == "cuda"
        self.model.to(self.device)
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=config.learning_rate,
            weight_decay=config.weight_decay,
        )
        self.scaler = torch.amp.GradScaler(  # type: ignore[attr-defined]
            "cuda", enabled=self.amp_enabled
        )
        self.criterion = ReefPoseLoss(
            heatmap_loss_weight=config.heatmap_loss_weight,
            visibility_loss_weight=config.visibility_loss_weight,
        )
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.config.output_dir / "training.jsonl"
        self.reproducibility = self._configure_reproducibility()

    def _configure_reproducibility(self) -> dict[str, Any]:
        random.seed(self.config.seed)
        np.random.seed(self.config.seed)
        torch.manual_seed(self.config.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(self.config.seed)
        if self.config.deterministic:
            torch.use_deterministic_algorithms(True, warn_only=True)
        return {
            "seed": self.config.seed,
            "deterministic": self.config.deterministic,
            "python_version": sys.version,
            "platform": platform.platform(),
            "torch_version": str(torch.__version__),
            "numpy_version": str(np.__version__),
            "cuda_version": torch.version.cuda,
            "cudnn_version": torch.backends.cudnn.version(),  # type: ignore[no-untyped-call]
            "device": str(self.device),
            "anatomy_integrity_hash": self.schema.integrity_hash,
        }

    def _batch_targets(self, batch: dict[str, Any]) -> tuple[torch.Tensor, ReefPoseTargets]:
        required = {"image", "heatmaps", "heatmap_weights", "visibility_targets"}
        if not required.issubset(batch):
            raise ReefPoseValidationError("ReefPose training batch is missing required tensors")
        images = batch["image"].to(self.device, non_blocking=True)
        targets = ReefPoseTargets(
            heatmaps=batch["heatmaps"].to(self.device, non_blocking=True),
            heatmap_weights=batch["heatmap_weights"].to(self.device, non_blocking=True),
            visibility_targets=batch["visibility_targets"].to(self.device, non_blocking=True),
        )
        return images, targets

    def _run_epoch(
        self,
        batches: Iterable[dict[str, Any]],
        *,
        training: bool,
        cancellation_check: CancellationCheck | None,
    ) -> tuple[dict[str, float], int]:
        self.model.train(training)
        totals = {"loss": 0.0, "heatmap_loss": 0.0, "visibility_loss": 0.0}
        batch_count = 0
        for batch in batches:
            if cancellation_check is not None and cancellation_check():
                raise ReefPoseCancelledError("ReefPose training was cancelled")
            images, targets = self._batch_targets(batch)
            if training:
                self.optimizer.zero_grad(set_to_none=True)
            with (
                torch.set_grad_enabled(training),
                torch.amp.autocast(  # type: ignore[attr-defined]
                    device_type=self.device.type,
                    enabled=self.amp_enabled,
                ),
            ):
                losses = self.criterion(self.model(images), targets)
            if training:
                self.scaler.scale(losses.total).backward()
                if self.config.gradient_clip_norm is not None:
                    self.scaler.unscale_(self.optimizer)
                    torch.nn.utils.clip_grad_norm_(
                        self.model.parameters(), self.config.gradient_clip_norm
                    )
                self.scaler.step(self.optimizer)
                self.scaler.update()
            totals["loss"] += float(losses.total.detach())
            totals["heatmap_loss"] += float(losses.heatmap.detach())
            totals["visibility_loss"] += float(losses.visibility.detach())
            batch_count += 1
        if batch_count == 0:
            raise ReefPoseValidationError("ReefPose training partition is empty")
        return ({key: value / batch_count for key, value in totals.items()}, batch_count)

    def _append_log(self, payload: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()

    def _save(
        self,
        path: Path,
        *,
        epoch: int,
        global_step: int,
        metrics: dict[str, float],
        extra_reproducibility: dict[str, Any] | None = None,
    ) -> None:
        save_checkpoint(
            path,
            model=self.model,
            schema=self.schema,
            epoch=epoch,
            global_step=global_step,
            metrics=metrics,
            optimizer=self.optimizer,
            scaler=self.scaler,
            training_config=self.config.to_dict(),
            reproducibility={**self.reproducibility, **(extra_reproducibility or {})},
        )

    def fit(
        self,
        training_batches: Iterable[dict[str, Any]],
        *,
        validation_batches: Iterable[dict[str, Any]] | None = None,
        cancellation_check: CancellationCheck | None = None,
        resume_from: Path | None = None,
    ) -> ReefPoseTrainingResult:
        start_epoch = 0
        global_step = 0
        best_loss = float("inf")
        history: list[dict[str, float]] = []
        if resume_from is not None:
            state = load_checkpoint(
                resume_from,
                device=self.device,
                model=self.model,
                optimizer=self.optimizer,
                scaler=self.scaler,
                expected_schema_hash=self.schema.integrity_hash,
            )
            start_epoch = state.epoch + 1
            global_step = state.global_step
            best_loss = float(state.metrics.get("selection_loss", float("inf")))
        if start_epoch >= self.config.epochs:
            raise ReefPoseValidationError("Checkpoint already reached the configured epoch count")

        last_checkpoint = self.config.output_dir / "last.pt"
        best_checkpoint = self.config.output_dir / "best.pt"
        current_epoch = start_epoch - 1
        latest_metrics: dict[str, float] = {}
        try:
            for epoch in range(start_epoch, self.config.epochs):
                current_epoch = epoch
                train_metrics, steps = self._run_epoch(
                    training_batches,
                    training=True,
                    cancellation_check=cancellation_check,
                )
                global_step += steps
                metrics = {f"train_{key}": value for key, value in train_metrics.items()}
                if validation_batches is not None:
                    validation_metrics, _ = self._run_epoch(
                        validation_batches,
                        training=False,
                        cancellation_check=cancellation_check,
                    )
                    metrics.update(
                        {f"validation_{key}": value for key, value in validation_metrics.items()}
                    )
                    selection_loss = validation_metrics["loss"]
                else:
                    selection_loss = train_metrics["loss"]
                metrics["selection_loss"] = selection_loss
                latest_metrics = metrics
                history.append(dict(metrics))
                self._save(
                    last_checkpoint,
                    epoch=epoch,
                    global_step=global_step,
                    metrics=metrics,
                )
                if selection_loss <= best_loss:
                    best_loss = selection_loss
                    self._save(
                        best_checkpoint,
                        epoch=epoch,
                        global_step=global_step,
                        metrics=metrics,
                    )
                self._append_log(
                    {
                        "schema_version": "reefpose-training-log-0001",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "epoch": epoch,
                        "global_step": global_step,
                        "device": str(self.device),
                        "amp_enabled": self.amp_enabled,
                        "metrics": metrics,
                    }
                )
        except ReefPoseCancelledError:
            self._save(
                self.config.output_dir / "cancelled.pt",
                epoch=current_epoch,
                global_step=global_step,
                metrics=latest_metrics,
                extra_reproducibility={"cancelled": True},
            )
            raise
        return ReefPoseTrainingResult(
            completed_epochs=self.config.epochs,
            global_step=global_step,
            last_checkpoint=last_checkpoint,
            best_checkpoint=best_checkpoint,
            metrics_history=history,
        )

"""Offline execution policy for the pinned Ultralytics training runtime.

Hooks are permanent, idempotent provider policy, not temporary patches: concurrent
workers must never restore a download-capable implementation. Local checkpoints
remain loadable. Architecture construction and all training use explicit inputs.
"""

from __future__ import annotations

import subprocess
import sys
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn, cast

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.ml.dependencies import configure_provider_runtime


def _deny_download(*args: Any, **kwargs: Any) -> NoReturn:
    raise ValidationError("Automatic downloads are disabled; register an existing local model")


def _local_asset(file: str | Path, *args: Any, **kwargs: Any) -> str:
    path = Path(file)
    if "://" in str(file) or not path.is_absolute() or not path.is_file():
        _deny_download()
    return str(path)


def _local_font(*args: Any, **kwargs: Any) -> Path:
    from matplotlib import font_manager

    return Path(font_manager.findfont("DejaVu Sans"))


def _offline_amp_check(model: Any) -> bool:
    # Upstream checks AMP against downloaded COCO weights. ReefVision requires
    # fp32 until a provider check using only the researcher's model is available.
    return False


def _no_update_check(*args: Any, **kwargs: Any) -> None:
    return None


def _run_local_trial(command: list[str], **kwargs: Any) -> Any:
    if command[:3] != [sys.executable, "-m", "ultralytics.cfg.__init__"]:
        raise ValidationError("Unrecognized Ultralytics tuning subprocess")
    return subprocess.run([sys.executable, "-m", __name__, *command[3:]], **kwargs)


def configure_local_training_runtime(settings: Settings | None = None) -> None:
    configure_provider_runtime(settings)
    checks = import_module("ultralytics.utils.checks")
    downloads = import_module("ultralytics.utils.downloads")
    trainer = import_module("ultralytics.engine.trainer")
    data_utils = import_module("ultralytics.data.utils")
    tasks = import_module("ultralytics.nn.tasks")
    tuner = import_module("ultralytics.engine.tuner")
    vars(checks)["check_pip_update_available"] = _no_update_check
    vars(checks)["check_font"] = _local_font
    vars(data_utils)["check_font"] = _local_font
    vars(checks)["check_amp"] = _offline_amp_check
    vars(trainer)["check_amp"] = _offline_amp_check
    vars(downloads)["safe_download"] = _deny_download
    vars(downloads)["download"] = _deny_download
    vars(downloads)["attempt_download_asset"] = _local_asset
    vars(tasks)["attempt_download_asset"] = _local_asset
    vars(data_utils)["safe_download"] = _deny_download
    vars(data_utils)["download"] = _deny_download
    # Native tuning launches a fresh interpreter; install the same policy there.
    vars(tuner)["subprocess"] = SimpleNamespace(run=_run_local_trial)


def architecture_source(source: str) -> str:
    if "://" in source or Path(source).suffix.lower() not in {".yaml", ".yml"}:
        raise ValidationError("Random initialization requires a local architecture YAML")
    return source


def local_training_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    result = dict(arguments)
    if result.get("pretrained", False) is not False:
        raise ValidationError("pretrained must be False; select a registered model explicitly")
    for key in ("cfg", "model", "resume"):
        if result.get(key):
            raise ValidationError(f"Training '{key}' is controlled by ReefVision initialization")
    result.update(pretrained=False, amp=False)
    return result


@lru_cache(maxsize=1)
def pose_trainer_class() -> type[Any]:
    """Honor val=False even during upstream final-epoch/final checkpoint hooks."""
    parent = import_module("ultralytics.models.yolo.pose.train").PoseTrainer

    def validate(self: Any) -> tuple[dict[str, Any], float]:
        if self.args.val:
            return cast(tuple[dict[str, Any], float], parent.validate(self))
        fitness = -float(self.loss.detach().cpu().sum())
        if self.best_fitness is None or fitness > self.best_fitness:
            self.best_fitness = fitness
        return {}, fitness

    def final_eval(self: Any) -> None:
        if self.args.val:
            parent.final_eval(self)

    return type("LocalPoseTrainer", (parent,), {"validate": validate, "final_eval": final_eval})


if __name__ == "__main__":
    configure_local_training_runtime()
    import_module("ultralytics.cfg").entrypoint()

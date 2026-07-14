"""Trusted local PyTorch plugin loading.

This is intentionally disabled by default because importing a Python module
executes code. Enable only for checkpoints and modules you control.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from typing import Any, cast

from torch import nn

Factory = Callable[[dict[str, Any]], nn.Module]


def load_model_factory(module_name: str, factory_name: str) -> Factory:
    if os.environ.get("REEFVISION_ALLOW_CUSTOM_PYTORCH", "false").lower() != "true":
        raise PermissionError(
            "Custom PyTorch plugins are disabled. Set "
            "REEFVISION_ALLOW_CUSTOM_PYTORCH=true only for trusted local code."
        )
    if not module_name.startswith("reefvision_custom_models."):
        raise PermissionError(
            "Custom model modules must live under the reefvision_custom_models package."
        )
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name, None)
    if factory is None or not callable(factory):
        raise ValueError(f"Factory {factory_name!r} was not found in {module_name!r}.")
    return cast(Factory, factory)

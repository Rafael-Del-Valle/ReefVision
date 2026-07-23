from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.ml.training_devices import resolve_training_device


def _torch(*, available: bool = True, count: int = 4):
    return SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: available,
            device_count=lambda: count,
        )
    )


def test_training_device_resolver_accepts_single_and_multi_gpu_lists(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", _torch())

    assert resolve_training_device("auto") == 0
    assert resolve_training_device("cuda:2") == 2
    assert resolve_training_device("2") == 2
    assert resolve_training_device("cuda:2,cuda:1") == "2,1"
    assert resolve_training_device("0,3") == "0,3"
    assert resolve_training_device("cpu") == "cpu"


def test_training_device_resolver_rejects_duplicates_and_unavailable_devices(
    monkeypatch,
) -> None:
    monkeypatch.setitem(sys.modules, "torch", _torch(count=2))

    with pytest.raises(ValidationError, match="unique"):
        resolve_training_device("0,cuda:0")
    with pytest.raises(ValidationError, match="unavailable"):
        resolve_training_device("0,2")

    monkeypatch.setitem(sys.modules, "torch", _torch(available=False, count=0))
    with pytest.raises(ValidationError, match="not available"):
        resolve_training_device("cuda:0")

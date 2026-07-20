from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from reefvision.config import Settings
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.services import assist


def descriptor(status: str, package_status: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        provider_id="segment_anything",
        registerable=True,
        availability_status=status,
        availability_reason=None,
        required_packages=(
            SimpleNamespace(distribution_name="segment-anything", status=package_status),
        ),
    )


def test_ready_segment_anything_provider(monkeypatch) -> None:
    monkeypatch.setattr(assist, "get_model_provider", lambda *_args: descriptor("ready"))
    assist._require_ready_assist_provider(cast(Settings, object()), "segment_anything")


@pytest.mark.parametrize(
    ("status", "package_status", "message"),
    [
        ("dependency_missing", "missing", "dependencies are missing"),
        ("dependency_incompatible", "incompatible", "dependencies are incompatible"),
    ],
)
def test_segment_anything_dependency_failures(
    monkeypatch, status: str, package_status: str, message: str
) -> None:
    monkeypatch.setattr(
        assist, "get_model_provider", lambda *_args: descriptor(status, package_status)
    )
    with pytest.raises(ValidationError, match=message):
        assist._require_ready_assist_provider(cast(Settings, object()), "segment_anything")


def test_unsupported_assist_provider(monkeypatch) -> None:
    def missing(*_args):
        raise NotFoundError("missing")

    monkeypatch.setattr(assist, "get_model_provider", missing)
    with pytest.raises(ValidationError, match="Unsupported Prompt Assist provider"):
        assist._require_ready_assist_provider(cast(Settings, object()), "unknown")

"""Startup must never import legacy installer models or change researcher files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reefvision.config import Settings
from reefvision.services import bundled_models


@pytest.mark.parametrize("provider", [False, True])
def test_legacy_bundled_weights_are_not_seeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: bool
) -> None:
    bundle = tmp_path / "old-bundle"
    bundle.mkdir()
    weight = bundle / "model.pt"
    weight.write_bytes(b"old installer weights")
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "assets": {} if provider else {"old/model": {"relative_path": "model.pt"}},
                "provider_assets": {"smolvlm": {"files": [{"relative_path": "model.pt"}]}}
                if provider
                else {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("REEFVISION_BUNDLED_MODELS_DIR", str(bundle))
    settings = Settings(env="test", data_dir=tmp_path / "fresh-profile")
    assert bundled_models.install_bundled_catalog_models(settings) == ([], [])
    assert not settings.resolved_data_dir.exists()
    assert weight.read_bytes() == b"old installer weights"


def test_startup_preserves_registered_and_cached_models(tmp_path: Path) -> None:
    settings = Settings(env="test", data_dir=tmp_path / "existing-profile")
    registered = settings.resolved_data_dir / "models" / "registered" / "researcher.pt"
    cached = settings.resolved_data_dir / "models" / "catalog-models" / "legacy.pt"
    for model in (registered, cached):
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(model.name.encode())
    before = {
        p.relative_to(settings.resolved_data_dir): p.read_bytes()
        for p in settings.resolved_data_dir.rglob("*")
        if p.is_file()
    }
    assert bundled_models.install_bundled_catalog_models(settings) == ([], [])
    after = {
        p.relative_to(settings.resolved_data_dir): p.read_bytes()
        for p in settings.resolved_data_dir.rglob("*")
        if p.is_file()
    }
    assert after == before

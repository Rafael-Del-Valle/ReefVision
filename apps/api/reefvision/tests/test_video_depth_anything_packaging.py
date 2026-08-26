from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.ml import video_depth_anything as vda

EXPECTED_COMMIT = "4f5ae23172ba60fd7bc11ef671cca678842c7072"
RESOLVER_NAME = "_source_root"


def _resolver():
    return getattr(vda, RESOLVER_NAME)


def _write_source(root: Path, *, commit: str = EXPECTED_COMMIT) -> Path:
    source = root / "provider-runtime" / "video-depth-anything" / "source"
    package = source / "video_depth_anything"
    package.mkdir(parents=True)
    (package / "video_depth.py").write_text(
        "# architecture\n",
        encoding="utf-8",
    )
    (package / "dpt_temporal.py").write_text(
        "motion_module_kwargs = dict(\n",
        encoding="utf-8",
    )
    (source / "LICENSE").write_text(
        "Apache License\nVersion 2.0\n",
        encoding="utf-8",
    )
    manifest = {
        "provider": "video_depth_anything",
        "repository": "DepthAnything/Video-Depth-Anything",
        "commit": commit,
        "license": "Apache-2.0",
        "reefvision_compatibility_patch": {
            "upstream_behavior_preserved": True,
        },
    }
    (source.parent / "source-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return source


def test_packaged_vda_source_precedes_legacy_data_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packaged_root = tmp_path / "bundle"
    packaged_source = _write_source(packaged_root)
    _write_source(tmp_path / "legacy")
    settings = Settings(data_dir=tmp_path / "legacy")

    monkeypatch.setattr(sys, "_MEIPASS", str(packaged_root), raising=False)
    monkeypatch.delenv(
        "REEFVISION_VIDEO_DEPTH_ANYTHING_SOURCE",
        raising=False,
    )

    assert _resolver()(settings) == packaged_source.resolve()


def test_explicit_vda_source_override_remains_highest_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packaged_root = tmp_path / "bundle"
    _write_source(packaged_root)
    override_source = _write_source(tmp_path / "override")
    settings = Settings(data_dir=tmp_path / "data")

    monkeypatch.setattr(sys, "_MEIPASS", str(packaged_root), raising=False)
    monkeypatch.setenv(
        "REEFVISION_VIDEO_DEPTH_ANYTHING_SOURCE",
        str(override_source),
    )

    assert _resolver()(settings) == override_source.resolve()


def test_vda_source_validation_rejects_wrong_commit(tmp_path: Path) -> None:
    source = _write_source(tmp_path, commit="0" * 40)

    with pytest.raises(ValidationError, match="commit"):
        vda.validate_video_depth_anything_source(source)


def test_desktop_packaging_contract_bundles_vda_runtime() -> None:
    root = Path(__file__).resolve().parents[4]
    build = (root / "scripts" / "build-desktop-backend.ps1").read_text(encoding="utf-8")
    desktop = (root / "apps" / "api" / "reefvision" / "desktop.py").read_text(encoding="utf-8")

    assert '"${VdaRuntimeRoot};provider-runtime/video-depth-anything"' in build
    assert EXPECTED_COMMIT in build
    assert "source-manifest.json" in build
    assert "reefvision_compatibility_patch" in build
    assert "resolve_video_depth_anything_source(settings)" in desktop

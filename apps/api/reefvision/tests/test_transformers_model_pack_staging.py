from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest


def _load_stager() -> ModuleType:
    script = Path(__file__).parents[4] / "scripts" / "stage-transformers-provider-models.py"
    specification = importlib.util.spec_from_file_location(
        "reefvision_transformers_model_pack_stager",
        script,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def test_snapshot_matching_reuses_only_complete_exact_files(tmp_path: Path) -> None:
    stager = _load_stager()
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(b"weights")
    remote_files = [
        {"relative_path": "config.json", "size_bytes": 3},
        {"relative_path": "model.safetensors", "size_bytes": 7},
    ]

    matches = cast(Any, stager._snapshot_matches_remote)
    assert matches(snapshot, remote_files) is True

    (snapshot / "model.safetensors").write_bytes(b"truncated")
    assert matches(snapshot, remote_files) is False

    (snapshot / "model.safetensors").unlink()
    assert matches(snapshot, remote_files) is False


def test_download_state_requires_same_repository_and_revision(tmp_path: Path) -> None:
    stager = _load_stager()
    state_path = tmp_path / stager._DOWNLOAD_STATE_NAME
    state_path.write_text(
        '{"repo_id":"example/model","resolved_revision":"abc123"}\n',
        encoding="utf-8",
    )
    matches = cast(Any, stager._download_state_matches)

    assert matches(tmp_path, repo_id="example/model", revision="abc123") is True
    assert matches(tmp_path, repo_id="example/other", revision="abc123") is False
    assert matches(tmp_path, repo_id="example/model", revision="different") is False


def test_disk_preflight_reports_required_additional_space(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stager = _load_stager()
    temporary = tmp_path / "model.part"
    temporary.mkdir()
    (temporary / "partial.bin").write_bytes(b"x" * 10)
    monkeypatch.setattr(
        stager.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=100, used=75, free=25),
    )

    with pytest.raises(RuntimeError, match="Free at least 15.00 B more"):
        cast(Any, stager._assert_download_space)(
            output_root=tmp_path,
            temporary=temporary,
            repo_id="example/model",
            remote_files=[{"relative_path": "model.bin", "size_bytes": 30}],
            reserve_bytes=20,
        )


def test_snapshot_file_inventory_ignores_resume_metadata(tmp_path: Path) -> None:
    stager = _load_stager()
    (tmp_path / "config.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "weights.bin").write_bytes(b"abc")
    (tmp_path / stager._DOWNLOAD_STATE_NAME).write_text("{}\n", encoding="utf-8")
    (tmp_path / stager._SNAPSHOT_MARKER_NAME).write_text("{}\n", encoding="utf-8")
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "metadata").write_text("ignored\n", encoding="utf-8")

    records = cast(Any, stager._snapshot_files)(tmp_path)
    assert [record["relative_path"] for record in records] == [
        "config.json",
        "weights.bin",
    ]

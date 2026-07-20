from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from reefvision.config import Settings
from reefvision.storage import models


def test_verified_model_path_cache_reuses_and_invalidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkpoint = tmp_path / "sam.pth"
    checkpoint.write_bytes(b"first-checkpoint")
    expected, _ = models.hash_model_file(checkpoint)
    calls = 0
    original_hash = models.hash_model_file

    def counted_hash(path: Path) -> tuple[str, int]:
        nonlocal calls
        calls += 1
        return original_hash(path)

    monkeypatch.setattr(models, "hash_model_file", counted_hash)
    monkeypatch.setattr(
        models,
        "resolve_managed_project_path",
        lambda _settings, _managed_path: checkpoint,
    )
    settings = cast(Settings, object())

    assert (
        models.resolve_verified_model_path(settings, "managed/sam.pth", expected_sha256=expected)
        == checkpoint
    )
    assert (
        models.resolve_verified_model_path(settings, "managed/sam.pth", expected_sha256=expected)
        == checkpoint
    )
    assert calls == 1

    checkpoint.write_bytes(b"other-checkpoint")
    stat = checkpoint.stat()
    os.utime(checkpoint, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    replacement, _ = original_hash(checkpoint)
    assert (
        models.resolve_verified_model_path(settings, "managed/sam.pth", expected_sha256=replacement)
        == checkpoint
    )
    assert calls == 2

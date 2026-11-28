from pathlib import Path

import pytest

from reefvision.config import Settings
from reefvision.domain.errors import ConflictError
from reefvision.storage.projects import filesystem_io_path
from reefvision.storage.training_resume import (
    capture_checkpoints,
    retire_previous_pair,
    verify_resume_checkpoint,
)


def test_publish_verify_and_retire_checkpoint_pairs_in_a_deep_project(
    test_settings: Settings,
) -> None:
    root = test_settings.resolved_data_dir
    relative = Path("projects") / ("deep-study-" * 8) / ("training-" * 8) / "reefpose"
    source = root / relative / "working"
    target = root / relative / "checkpoints"
    filesystem_io_path(source).mkdir(parents=True)
    filesystem_io_path(source / "last.pt").write_bytes(b"last")
    filesystem_io_path(source / "best.pt").write_bytes(b"best")

    previous = capture_checkpoints(test_settings, source, target)
    current = capture_checkpoints(test_settings, source, target)
    for snapshot in (previous, current):
        assert snapshot["resume_checkpoint_path"].startswith(relative.as_posix() + "/checkpoints/")
        verify_resume_checkpoint(test_settings, snapshot, relative.as_posix())

    retire_previous_pair(
        test_settings, target, previous["resume_checkpoint_path"], current["resume_checkpoint_path"]
    )
    assert not filesystem_io_path(root / previous["resume_checkpoint_path"]).parent.exists()
    verify_resume_checkpoint(test_settings, current, relative.as_posix())
    filesystem_io_path(root / current["resume_best_checkpoint_path"]).write_bytes(b"changed")
    with pytest.raises(ConflictError, match="checksum changed"):
        verify_resume_checkpoint(test_settings, current, relative.as_posix())

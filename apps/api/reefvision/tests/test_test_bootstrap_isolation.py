"""Collection must not initialize the user's default application data directory."""

import os
import subprocess
import sys
from pathlib import Path


def test_collection_isolates_default_app_and_cleans_bootstrap_resources(tmp_path: Path) -> None:
    developer_data = tmp_path / ".reefvision"
    developer_data.mkdir()
    sentinel = developer_data / "keep.txt"
    sentinel.write_text("developer data must remain unchanged", encoding="utf-8")
    # Also protect against settings inherited from a local .env file.
    (tmp_path / ".env").write_text(
        "REEFVISION_ENV=development\n"
        f"REEFVISION_DATABASE_URL=sqlite:///{(developer_data / 'user.db').as_posix()}\n",
        encoding="utf-8",
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("REEFVISION_")
        and key not in {"YOLO_CONFIG_DIR", "YOLO_AUTOINSTALL", "MPLBACKEND"}
    }
    target = Path(__file__).with_name("test_training_architecture_validation.py")
    script = """
import logging
import os
import sys
from pathlib import Path

import pytest
from reefvision.config import get_settings

keys = (
    "REEFVISION_ENV", "REEFVISION_DATA_DIR", "REEFVISION_DATABASE_URL",
    "REEFVISION_BACKGROUND_WORKER_ENABLED", "REEFVISION_CONFIG_DIR",
    "YOLO_CONFIG_DIR", "YOLO_AUTOINSTALL", "MPLBACKEND",
)
before = {key: os.environ.get(key) for key in keys}
original = get_settings()  # Exercise an already populated settings cache too.
assert pytest.main([sys.argv[1], "--collect-only", "-q"]) == 0
import reefvision.main as main

assert list((Path.cwd() / ".reefvision").iterdir()) == [Path.cwd() / ".reefvision/keep.txt"]
bootstrap = main.app.state.settings
assert bootstrap.env == "test"
assert bootstrap.background_worker_enabled is False
assert bootstrap.resolved_data_dir != original.resolved_data_dir
assert not bootstrap.resolved_data_dir.exists(), "bootstrap temporary directory leaked"
assert {key: os.environ.get(key) for key in keys} == before
assert get_settings().resolved_data_dir == original.resolved_data_dir
assert get_settings().env == original.env
assert not any(
    str(getattr(handler, "baseFilename", "")).startswith(str(bootstrap.resolved_data_dir))
    for handler in logging.getLogger().handlers
), "bootstrap log handler leaked"
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(target)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel.read_text(encoding="utf-8") == "developer data must remain unchanged"

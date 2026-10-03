import logging
import os
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings, clear_settings_cache
from reefvision.db.base import Base

_BOOTSTRAP_ENV_KEYS = (
    "REEFVISION_ENV",
    "REEFVISION_DATA_DIR",
    "REEFVISION_DATABASE_URL",
    "REEFVISION_BACKGROUND_WORKER_ENABLED",
    "REEFVISION_CONFIG_DIR",
    "YOLO_CONFIG_DIR",
    "YOLO_AUTOINSTALL",
    "MPLBACKEND",
)


def _load_test_create_app():
    """Import the default FastAPI module without touching developer data."""
    previous_environment = {key: os.environ.get(key) for key in _BOOTSTRAP_ENV_KEYS}
    root_logger = logging.getLogger()
    previous_root_level = root_logger.level
    bootstrap_root = Path(tempfile.mkdtemp(prefix="reefvision-pytest-bootstrap-")).resolve()

    try:
        os.environ["REEFVISION_ENV"] = "test"
        os.environ["REEFVISION_DATA_DIR"] = str(bootstrap_root)
        os.environ["REEFVISION_DATABASE_URL"] = (
            f"sqlite:///{(bootstrap_root / 'bootstrap.db').as_posix()}"
        )
        os.environ["REEFVISION_BACKGROUND_WORKER_ENABLED"] = "false"

        clear_settings_cache()
        import reefvision.main as main

        main.app.state.engine.dispose()

        for handler in list(root_logger.handlers):
            filename = str(getattr(handler, "baseFilename", ""))
            if filename and filename.startswith(str(bootstrap_root)):
                root_logger.removeHandler(handler)
                handler.close()

        return main.create_app
    finally:
        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        clear_settings_cache()
        root_logger.setLevel(previous_root_level)
        shutil.rmtree(bootstrap_root, ignore_errors=True)


create_app = _load_test_create_app()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--pose-interop-integration",
        action="store_true",
        default=False,
        help="Execute synthetic pose interoperability tests with sleap-io==0.9.2",
    )
    parser.addoption(
        "--whaledrone-integration",
        action="store_true",
        default=False,
        help="Read an external WhaleDrone MP4/SRT pair (never downloads or copies data)",
    )
    parser.addoption(
        "--whaledrone-video", default=None, help="Original DJI video filename to validate"
    )
    parser.addoption("--whaledrone-frame-base", type=int, choices=[0, 1], default=None)
    parser.addoption("--whaledrone-takeoff-height-m", type=float, default=None)
    parser.addoption("--whaledrone-height-evidence", default=None)
    parser.addoption("--whaledrone-height-datum-verified", action="store_true", default=False)
    parser.addoption("--whaledrone-time-offset-s", type=float, default=0.0)
    parser.addoption("--whaledrone-time-offset-evidence", default=None)
    parser.addoption("--whaledrone-time-column", default=None)
    parser.addoption("--whaledrone-sync-evidence", default=None)
    parser.addoption("--whaledrone-camera-evidence", default=None)


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        data_dir=tmp_path / "reefvision-test-data",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        web_origin="http://testserver",
        background_worker_enabled=False,
    )


@pytest.fixture
def client(test_settings: Settings) -> Generator[TestClient, None, None]:
    app = create_app(test_settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as test_client:
        yield test_client
        Base.metadata.drop_all(app.state.engine)
        app.state.engine.dispose()

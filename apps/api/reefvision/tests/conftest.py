from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.main import create_app


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

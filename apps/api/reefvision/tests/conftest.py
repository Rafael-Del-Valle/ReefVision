from __future__ import annotations

import re
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.main import create_app

_INTEGRATION_HINTS = (
    "api",
    "backup",
    "desktop",
    "export",
    "import",
    "inference",
    "job",
    "migration",
    "route",
    "training",
    "video",
    "worker",
    "workflow",
)
_PHASE_PATTERN = re.compile(r"phase(?:_|-)?(10|[1-9])", re.IGNORECASE)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Attach stable suite and phase markers without rewriting every historical test.

    File-name classification keeps legacy tests compatible with strict markers while
    allowing CI to run fast unit tests, integration tests, or one roadmap phase.
    Explicit markers on a test always take precedence over the automatic suite marker.
    """

    for item in items:
        filename = Path(str(item.fspath)).name.casefold()
        if (
            item.get_closest_marker("unit") is None
            and item.get_closest_marker("integration") is None
        ):
            marker = (
                "integration" if any(token in filename for token in _INTEGRATION_HINTS) else "unit"
            )
            item.add_marker(getattr(pytest.mark, marker))
        match = _PHASE_PATTERN.search(filename)
        if match is not None:
            item.add_marker(getattr(pytest.mark, f"phase{match.group(1)}"))


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

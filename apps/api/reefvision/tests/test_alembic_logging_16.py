"""Preserve desktop migration diagnostics without changing Alembic CLI logging."""

from __future__ import annotations

import logging.config
import runpy
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from alembic import context
from alembic.config import Config

from reefvision import config as reefvision_config
from reefvision.desktop import resolve_alembic_paths


@pytest.mark.parametrize(
    ("configure_logger", "expected_calls"),
    [(False, 0), (True, 1)],
)
def test_alembic_env_respects_desktop_logger_opt_out(
    monkeypatch: pytest.MonkeyPatch,
    configure_logger: bool,
    expected_calls: int,
) -> None:
    """Execute the actual env.py in offline mode without touching a database."""
    alembic_ini, migrations = resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = configure_logger

    configured: list[str] = []
    monkeypatch.setattr(
        logging.config,
        "fileConfig",
        lambda *_args, **_kwargs: configured.append("configured"),
    )
    monkeypatch.setattr(context, "config", config, raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    monkeypatch.setattr(context, "configure", lambda **_kwargs: None)
    monkeypatch.setattr(context, "begin_transaction", lambda: nullcontext())
    monkeypatch.setattr(context, "run_migrations", lambda: None)
    monkeypatch.setattr(
        reefvision_config,
        "get_settings",
        lambda: SimpleNamespace(
            ensure_directories=lambda: None,
            resolved_database_url="sqlite:///:memory:",
        ),
    )

    runpy.run_path(str(migrations / "env.py"), run_name="reefvision_alembic_logging_test")

    assert len(configured) == expected_calls

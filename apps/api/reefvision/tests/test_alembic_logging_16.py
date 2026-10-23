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


def test_alembic_env_honors_desktop_pinned_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A desktop migration must not silently target a different settings DB."""
    alembic_ini, migrations = resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = False
    config.attributes["desktop_database_url"] = "sqlite:///desktop-preflight.sqlite"

    configured_urls: list[str] = []
    monkeypatch.setattr(context, "config", config, raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    monkeypatch.setattr(
        context,
        "configure",
        lambda **kwargs: configured_urls.append(kwargs["url"]),
    )
    monkeypatch.setattr(context, "begin_transaction", lambda: nullcontext())
    monkeypatch.setattr(context, "run_migrations", lambda: None)
    monkeypatch.setattr(
        reefvision_config,
        "get_settings",
        lambda: pytest.fail("Desktop migration must not re-resolve Settings"),
    )

    runpy.run_path(str(migrations / "env.py"), run_name="reefvision_alembic_pin_test")

    assert configured_urls == ["sqlite:///desktop-preflight.sqlite"]
    assert config.get_main_option("sqlalchemy.url") == "sqlite:///desktop-preflight.sqlite"


@pytest.mark.parametrize("invalid_url", ["", "   ", 123])
def test_alembic_env_rejects_invalid_pinned_database_url(
    monkeypatch: pytest.MonkeyPatch,
    invalid_url: object,
) -> None:
    alembic_ini, migrations = resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = False
    config.attributes["desktop_database_url"] = invalid_url
    monkeypatch.setattr(context, "config", config, raising=False)
    monkeypatch.setattr(
        reefvision_config,
        "get_settings",
        lambda: pytest.fail("Invalid pinned URL must not fall back to Settings"),
    )

    with pytest.raises(RuntimeError, match="Invalid pinned desktop Alembic database URL"):
        runpy.run_path(str(migrations / "env.py"), run_name="reefvision_alembic_pin_invalid_test")

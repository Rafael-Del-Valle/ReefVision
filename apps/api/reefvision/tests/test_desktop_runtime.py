"""Tests for Windows desktop startup and event-loop configuration."""

import asyncio
import builtins
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from reefvision import desktop
from reefvision.config import Settings, clear_settings_cache


def test_frozen_windows_sidecar_uses_selector_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = object()
    policy_factory = Mock(return_value=policy)
    set_policy = Mock()

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(desktop, "is_frozen_bundle", lambda: True)
    monkeypatch.setattr(
        asyncio,
        "WindowsSelectorEventLoopPolicy",
        policy_factory,
        raising=False,
    )
    monkeypatch.setattr(asyncio, "set_event_loop_policy", set_policy)

    desktop.configure_windows_event_loop_policy()

    policy_factory.assert_called_once_with()
    set_policy.assert_called_once_with(policy)


def test_non_frozen_process_keeps_default_event_loop_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_policy = Mock()

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(desktop, "is_frozen_bundle", lambda: False)
    monkeypatch.setattr(asyncio, "set_event_loop_policy", set_policy)

    desktop.configure_windows_event_loop_policy()

    set_policy.assert_not_called()


def test_non_windows_process_keeps_default_event_loop_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_policy = Mock()

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(desktop, "is_frozen_bundle", lambda: True)
    monkeypatch.setattr(asyncio, "set_event_loop_policy", set_policy)

    desktop.configure_windows_event_loop_policy()

    set_policy.assert_not_called()


@pytest.mark.parametrize(
    ("platform", "frozen", "stats_available", "expected_imports"),
    [
        ("win32", False, True, ["scipy.stats"]),
        ("win32", False, False, ["scipy.stats"]),
        ("win32", True, True, ["scipy.linalg", "scipy.sparse.linalg", "scipy.stats"]),
        ("win32", True, False, ["scipy.linalg", "scipy.sparse.linalg", "scipy.stats"]),
        ("linux", True, True, []),
    ],
)
def test_desktop_preloads_scipy_on_main_thread_before_serving(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    platform: str,
    frozen: bool,
    stats_available: bool,
    expected_imports: list[str],
) -> None:
    events: list[str] = []
    imports = {
        "scipy.linalg": SimpleNamespace(blas=SimpleNamespace(__name__="blas")),
        "scipy.sparse.linalg": SimpleNamespace(eigsh=SimpleNamespace(__name__="eigsh")),
        "scipy.stats": SimpleNamespace(t=SimpleNamespace(name="t")),
    }

    def import_scipy(name: str, *args: Any, **kwargs: Any) -> Any:
        if name not in imports:
            return original_import(name, *args, **kwargs)
        assert threading.current_thread() is threading.main_thread()
        events.append(name)
        if name == "scipy.stats" and not stats_available:
            raise ModuleNotFoundError("SciPy statistics are unavailable", name=name)
        return imports[name]

    async def run_api_server(_: Settings, _options: desktop.DesktopLaunchOptions) -> int:
        events.append("serve")
        return 0

    original_import = builtins.__import__
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(desktop, "is_frozen_bundle", lambda: frozen)
    monkeypatch.setattr(desktop, "configure_windows_event_loop_policy", lambda: None)
    monkeypatch.setattr(desktop, "run_api_server", run_api_server)
    monkeypatch.setattr(desktop, "build_settings", lambda _: Settings(data_dir=tmp_path))
    monkeypatch.setattr(builtins, "__import__", import_scipy)

    assert desktop.main(["--data-dir", str(tmp_path), "--skip-migrations"]) == 0
    assert events == [*expected_imports, "serve"]


def test_normal_desktop_launch_overrides_inherited_safe_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("REEFVISION_SAFE_MODE", "true")
    monkeypatch.setenv("REEFVISION_BACKGROUND_WORKER_ENABLED", "false")

    clear_settings_cache()
    try:
        settings = desktop.build_settings(
            desktop.DesktopLaunchOptions(
                host="127.0.0.1",
                port=48123,
                data_dir=tmp_path / "normal-desktop",
                log_file=None,
                context_file=None,
                run_migrations=False,
                safe_mode=False,
            )
        )

        assert settings.safe_mode is False
        assert settings.background_worker_enabled is True
    finally:
        clear_settings_cache()


def test_explicit_desktop_safe_mode_disables_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("REEFVISION_SAFE_MODE", "false")
    monkeypatch.setenv("REEFVISION_BACKGROUND_WORKER_ENABLED", "true")

    clear_settings_cache()
    try:
        settings = desktop.build_settings(
            desktop.DesktopLaunchOptions(
                host="127.0.0.1",
                port=48123,
                data_dir=tmp_path / "safe-desktop",
                log_file=None,
                context_file=None,
                run_migrations=False,
                safe_mode=True,
            )
        )

        assert settings.safe_mode is True
        assert settings.background_worker_enabled is False
    finally:
        clear_settings_cache()

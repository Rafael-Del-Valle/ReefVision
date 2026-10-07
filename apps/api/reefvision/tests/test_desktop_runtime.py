"""Tests for the packaged Windows desktop event-loop configuration."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from reefvision import desktop


def test_frozen_windows_sidecar_uses_selector_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = object()
    policy_factory = Mock(return_value=policy)
    set_policy = Mock()

    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop, "is_frozen_bundle", lambda: True)
    monkeypatch.setattr(
        desktop.asyncio,
        "WindowsSelectorEventLoopPolicy",
        policy_factory,
        raising=False,
    )
    monkeypatch.setattr(desktop.asyncio, "set_event_loop_policy", set_policy)

    desktop.configure_windows_event_loop_policy()

    policy_factory.assert_called_once_with()
    set_policy.assert_called_once_with(policy)


def test_non_frozen_process_keeps_default_event_loop_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_policy = Mock()

    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop, "is_frozen_bundle", lambda: False)
    monkeypatch.setattr(desktop.asyncio, "set_event_loop_policy", set_policy)

    desktop.configure_windows_event_loop_policy()

    set_policy.assert_not_called()


def test_non_windows_process_keeps_default_event_loop_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_policy = Mock()

    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setattr(desktop, "is_frozen_bundle", lambda: True)
    monkeypatch.setattr(desktop.asyncio, "set_event_loop_policy", set_policy)

    desktop.configure_windows_event_loop_policy()

    set_policy.assert_not_called()


def test_normal_desktop_launch_overrides_inherited_safe_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("REEFVISION_SAFE_MODE", "true")
    monkeypatch.setenv("REEFVISION_BACKGROUND_WORKER_ENABLED", "false")

    desktop.clear_settings_cache()
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
        desktop.clear_settings_cache()


def test_explicit_desktop_safe_mode_disables_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("REEFVISION_SAFE_MODE", "false")
    monkeypatch.setenv("REEFVISION_BACKGROUND_WORKER_ENABLED", "true")

    desktop.clear_settings_cache()
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
        desktop.clear_settings_cache()

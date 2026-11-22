import asyncio
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from reefvision.config import Settings, clear_settings_cache
from reefvision.desktop import (
    DesktopLaunchOptions,
    build_settings,
    parse_args,
    project_root,
    require_scale_assistant_marker_runtime,
    resolve_alembic_paths,
    resolve_server_port,
    run_api_server,
    watch_shutdown_stream,
    write_runtime_port,
    write_self_test_result,
)


def test_resolve_alembic_paths_in_source_tree() -> None:
    alembic_ini, migrations = resolve_alembic_paths(project_root())

    assert alembic_ini.is_file()
    assert migrations.is_dir()


def test_build_settings_applies_desktop_launch_options(tmp_path: Path) -> None:
    previous_env = {
        key: os.environ.get(key)
        for key in (
            "REEFVISION_ENV",
            "REEFVISION_API_HOST",
            "REEFVISION_API_PORT",
            "REEFVISION_DATA_DIR",
        )
    }
    clear_settings_cache()
    try:
        settings = build_settings(
            DesktopLaunchOptions(
                host="127.0.0.1",
                port=48123,
                data_dir=tmp_path / "desktop-data",
                log_file=None,
                context_file=None,
                run_migrations=False,
            )
        )

        assert settings.env == "desktop"
        assert settings.api_host == "127.0.0.1"
        assert settings.api_port == 48123
        assert settings.resolved_data_dir == (tmp_path / "desktop-data").resolve()
    finally:
        clear_settings_cache()
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_parse_args_enables_packaged_self_test_without_starting_server() -> None:
    options = parse_args(
        [
            "--self-test",
            "--safe-mode",
            "--data-dir",
            "C:/reefvision-self-test",
            "--log-file",
            "C:/reefvision-self-test.log",
        ]
    )

    assert options.self_test is True
    assert options.safe_mode is True
    assert options.run_migrations is True
    assert options.data_dir == Path("C:/reefvision-self-test")
    assert options.log_file == Path("C:/reefvision-self-test.log")


def test_parse_args_enables_packaged_provider_hardware_acceptance() -> None:
    options = parse_args(
        [
            "--provider-hardware-acceptance",
            "--safe-mode",
            "--data-dir",
            "C:/reefvision-provider-acceptance",
        ]
    )

    assert options.provider_hardware_acceptance is True
    assert options.safe_mode is True
    assert options.data_dir == Path("C:/reefvision-provider-acceptance")



@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "::", "192.168.1.9", "research.example", ""],
)
def test_desktop_refuses_remote_or_unresolved_host_before_startup(
    host: str, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as cli_error:
        parse_args(["--host", host, "--data-dir", str(tmp_path / "research")])
    assert cli_error.value.code == 2

    # Programmatic callers cannot bypass the CLI's network security boundary.
    options = DesktopLaunchOptions(
        host=host,
        port=0,
        data_dir=tmp_path / "research",
        log_file=None,
        context_file=None,
        run_migrations=False,
    )
    with pytest.raises(ValueError, match="loopback"):
        build_settings(options)
    assert not (tmp_path / "research").exists()


@pytest.mark.parametrize("host", ["127.0.0.1", "127.13.2.4", "::1", "localhost"])
def test_desktop_accepts_only_explicit_loopback_host(host: str) -> None:
    assert parse_args(["--host", host]).host == host


def test_desktop_server_rejects_remote_settings_before_app_creation(tmp_path: Path) -> None:
    # Even a direct run_api_server call must refuse a non-loopback bind.
    settings = Settings(
        env="desktop",
        api_host="0.0.0.0",
        data_dir=tmp_path / "science-data",
    )
    options = DesktopLaunchOptions(
        host="127.0.0.1",
        port=0,
        data_dir=settings.data_dir,
        log_file=None,
        context_file=tmp_path / "published-port.txt",
        run_migrations=False,
    )
    with pytest.raises(ValueError, match="loopback"):
        asyncio.run(run_api_server(settings, options))
    assert not options.context_file.exists()



def test_scale_assistant_marker_runtime_accepts_opencv_contrib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(aruco=SimpleNamespace()))

    require_scale_assistant_marker_runtime()


def test_scale_assistant_marker_runtime_rejects_base_opencv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace())

    with pytest.raises(RuntimeError, match="opencv-contrib"):
        require_scale_assistant_marker_runtime()


def test_resolve_server_port_reads_ephemeral_listener() -> None:
    listener = SimpleNamespace(getsockname=lambda: ("127.0.0.1", 48177))
    active_server = SimpleNamespace(sockets=[listener])
    server = SimpleNamespace(servers=[active_server])

    assert resolve_server_port(server, requested_port=0) == 48177


def test_resolve_server_port_falls_back_to_requested_port() -> None:
    server = SimpleNamespace(servers=[])

    assert resolve_server_port(server, requested_port=48123) == 48123


def test_write_runtime_port_creates_parent_directory(tmp_path: Path) -> None:
    context_file = tmp_path / "runtime" / "backend-port.txt"

    write_runtime_port(context_file, 48177)

    assert context_file.read_text(encoding="utf-8").strip() == "48177"


def test_watch_shutdown_stream_stops_server_on_shutdown_command() -> None:
    server = SimpleNamespace(should_exit=False)

    watch_shutdown_stream(io.StringIO("shutdown\n"), server)

    assert server.should_exit is True


def test_watch_shutdown_stream_stops_server_on_eof() -> None:
    server = SimpleNamespace(should_exit=False)

    watch_shutdown_stream(io.StringIO(""), server)

    assert server.should_exit is True


def test_write_self_test_result_records_packaged_version(tmp_path: Path) -> None:
    result = write_self_test_result(
        tmp_path,
        version="1.0.1",
        openapi_path_count=147,
    )

    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload == {
        "application_version": "1.0.1",
        "openapi_path_count": 147,
        "status": "PASS",
    }

import io
import os
from pathlib import Path
from types import SimpleNamespace

from reefvision.config import clear_settings_cache
from reefvision.desktop import (
    DesktopLaunchOptions,
    build_settings,
    parse_args,
    project_root,
    resolve_alembic_paths,
    resolve_server_port,
    watch_shutdown_stream,
    write_runtime_port,
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

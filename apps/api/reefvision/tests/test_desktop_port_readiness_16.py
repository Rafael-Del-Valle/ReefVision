"""Regression coverage for fail-closed local desktop port publication."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from reefvision import desktop
from reefvision.config import Settings


def _started_listener(port: int) -> SimpleNamespace:
    listener = SimpleNamespace(getsockname=lambda: ("127.0.0.1", port))
    return SimpleNamespace(
        started=True,
        should_exit=False,
        servers=[SimpleNamespace(sockets=[listener])],
    )


def test_ready_port_publication_succeeds_for_ephemeral_listener(tmp_path: Path) -> None:
    server = _started_listener(48177)
    context_file = tmp_path / "gui" / "backend-port.txt"

    asyncio.run(desktop.publish_runtime_port_when_ready(server, context_file, 0))

    assert context_file.read_text(encoding="utf-8") == "48177\n"
    assert server.should_exit is False


def test_unavailable_listener_refuses_gui_ready_signal(tmp_path: Path) -> None:
    server = SimpleNamespace(started=True, should_exit=False, servers=[])
    context_file = tmp_path / "gui" / "backend-port.txt"

    with pytest.raises(RuntimeError, match="did not expose its loopback port"):
        asyncio.run(desktop.publish_runtime_port_when_ready(server, context_file, 0))

    assert server.should_exit is True
    assert not context_file.exists()


def test_unwritable_ready_file_stops_running_api_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed GUI handshake must not leave an unowned scientific write API."""
    blocked_parent = tmp_path / "existing-file-not-a-directory"
    blocked_parent.write_text("preserved researcher context", encoding="utf-8")
    context_file = blocked_parent / "backend-port.txt"
    state: dict[str, object] = {}

    class LocalServer:
        def __init__(self, _config: object) -> None:
            self.started = False
            self.should_exit = False
            self.servers = [
                SimpleNamespace(
                    sockets=[SimpleNamespace(getsockname=lambda: ("127.0.0.1", 48177))]
                )
            ]
            state["server"] = self

        async def serve(self) -> None:
            self.started = True
            for _ in range(400):
                if self.should_exit:
                    return
                await asyncio.sleep(0.01)
            pytest.fail("Server remained active after failed desktop readiness publication")

    monkeypatch.setattr(desktop.uvicorn, "Server", LocalServer)
    monkeypatch.setattr(desktop, "start_shutdown_monitor", lambda _server: None)
    monkeypatch.setattr("reefvision.main.create_app", lambda _settings: object())
    settings = Settings(
        env="desktop",
        api_host="127.0.0.1",
        api_port=0,
        data_dir=tmp_path / "scientific-data",
    )
    options = desktop.DesktopLaunchOptions(
        host="127.0.0.1",
        port=0,
        data_dir=tmp_path / "scientific-data",
        log_file=None,
        context_file=context_file,
        run_migrations=False,
    )

    with pytest.raises(FileExistsError):
        asyncio.run(asyncio.wait_for(desktop.run_api_server(settings, options), timeout=3))

    server = state["server"]
    assert isinstance(server, LocalServer)
    assert server.should_exit is True
    assert blocked_parent.read_text(encoding="utf-8") == "preserved researcher context"
    assert not context_file.exists()

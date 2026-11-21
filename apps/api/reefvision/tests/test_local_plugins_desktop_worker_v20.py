"""Exercise the native plugin worker from the real desktop API process."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

import httpx

from reefvision.tests.test_local_plugins_v20 import PLUGINS, package


def test_cold_plugin_install_from_desktop_process(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / ".reefvision-disposable-qa").touch()
    context = tmp_path / "port.txt"
    log_path = tmp_path / "desktop.log"
    api_root = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "PYTHONPATH": str(api_root),
        "TMP": str(tmp_path),
        "TEMP": str(tmp_path),
        "YOLO_OFFLINE": "true",
        "CUDA_VISIBLE_DEVICES": "-1",
    }
    with (
        log_path.open("wb") as log,
        subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "reefvision.desktop",
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--data-dir",
                str(profile),
                "--context-file",
                str(context),
            ],
            cwd=api_root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ) as sidecar,
    ):
        try:
            _check_desktop_plugin_install(sidecar, context, profile, log_path)
        finally:
            if sidecar.poll() is None and sidecar.stdin is not None:
                sidecar.stdin.write(b"shutdown\n")
                sidecar.stdin.flush()
                try:
                    sidecar.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    sidecar.kill()
                    sidecar.wait(timeout=10)


def _check_desktop_plugin_install(
    sidecar: subprocess.Popen[bytes], context: Path, profile: Path, log: Path
) -> None:
    with httpx.Client(trust_env=False) as client:
        deadline = monotonic() + 45
        while monotonic() < deadline and sidecar.poll() is None:
            try:
                port = int(context.read_text(encoding="utf-8"))
                origin = f"http://127.0.0.1:{port}"
                version = client.get(f"{origin}/api/v1/system/version", timeout=1)
                if version.is_success:
                    break
            except (OSError, ValueError, httpx.HTTPError):
                pass
            sleep(0.1)
        else:
            raise AssertionError(log.read_text(encoding="utf-8", errors="replace"))
        assert Path(version.json()["data_dir"]).resolve() == profile.resolve()
        response = client.post(origin + PLUGINS, json=package("f64.const 0.5"), timeout=25)
        assert response.status_code == 201, response.text
        record = response.json()
        assert record["available"] and not record["enabled"]
        assert client.get(origin + PLUGINS).json() == {"items": [record], "total": 1}

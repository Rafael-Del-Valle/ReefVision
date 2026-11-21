"""Start an offline desktop service for a specified profile and close only the owned process."""

import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from reefvision.storage.worker_lock import worker_leadership
from reefvision_sdk import AutomationError, ReefVision


def _matching_service(port: int, profile: Path) -> ReefVision | None:
    if not 1 <= port <= 65535:
        return None
    client = ReefVision(f"http://127.0.0.1:{port}/api/v1", timeout=3)
    try:
        system = client.system()
    except (AutomationError, ValueError, KeyError):
        return None
    if Path(system.get("data_dir", "")).resolve() != profile:
        return None
    if not str(system.get("application_version", "")).startswith("2.") or system.get("safe_mode"):
        raise AutomationError(
            "The open profile requires a writable ReefVision 2.0 service.", status=409
        )
    return ReefVision(client.api_url)


@contextmanager
def profile_service(profile: Path, timeout: float) -> Iterator[ReefVision]:
    if not profile.is_absolute():
        raise AutomationError("Supply an absolute local profile directory.")
    profile = profile.resolve()
    runtime = profile / "runtime"
    with worker_leadership(runtime, filename="headless-session.lock") as owner:
        if not owner:
            raise AutomationError(
                "Another headless command is using this profile. Try again when it finishes.",
                status=409,
            )
        desktop_port = runtime / "backend-port.txt"
        try:
            existing = _matching_service(int(desktop_port.read_text().strip()), profile)
        except (OSError, ValueError):
            existing = None
        if existing is not None:
            yield existing
            return
        with tempfile.TemporaryDirectory(prefix="headless-", dir=runtime) as tmp:
            port_file = Path(tmp) / "port"
            command = [sys.executable]
            if not getattr(sys, "frozen", False):
                command.extend(["-m", "reefvision.desktop"])
            command += [
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--data-dir",
                str(profile),
                "--context-file",
                str(port_file),
            ]
            env = {
                **os.environ,
                "REEFVISION_DATA_DIR": str(profile),
                "REEFVISION_CONFIG_DIR": str(profile / "config"),
                "HF_HUB_OFFLINE": "1",
                "YOLO_OFFLINE": "true",
            }
            env.pop("REEFVISION_DATABASE_URL", None)
            logs = profile / "logs"
            logs.mkdir(exist_ok=True)
            with (logs / "automation-service.log").open("ab") as log:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                try:
                    until = time.monotonic() + min(timeout, 120)
                    while time.monotonic() < until and process.poll() is None:
                        try:
                            port = int(port_file.read_text().strip())
                        except (OSError, ValueError):
                            time.sleep(0.1)
                            continue
                        client = _matching_service(port, profile)
                        if client is not None:
                            yield client
                            return
                        time.sleep(0.1)
                    raise AutomationError(
                        "Cannot open the profile. See logs/automation-service.log.",
                        status=503,
                    )
                finally:
                    if process.stdin:
                        process.stdin.close()
                    try:
                        process.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=10)

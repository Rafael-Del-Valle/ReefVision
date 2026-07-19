#!/usr/bin/env python3
"""Launch a frozen ReefVision API sidecar and verify startup and clean shutdown."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def wait_for_port(context_file: Path, process: subprocess.Popen[str], timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            raise RuntimeError(
                f"Sidecar exited before publishing a port ({process.returncode})\n{stdout}\n{stderr}"
            )
        if context_file.is_file():
            value = context_file.read_text(encoding="utf-8").strip()
            if value.isdigit() and int(value) > 0:
                return int(value)
        time.sleep(0.1)
    raise TimeoutError("Sidecar did not publish a loopback port before the timeout")


def wait_for_health(port: int, timeout: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/api/v1/health"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("status") == "ok":
                    return payload
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.2)
    raise TimeoutError(f"Health endpoint did not become ready: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    executable = args.executable.resolve()
    if not executable.is_file():
        raise SystemExit(f"Packaged sidecar not found: {executable}")

    with tempfile.TemporaryDirectory(prefix="reefvision-sidecar-smoke-") as temporary:
        root = Path(temporary)
        context_file = root / "runtime-port.txt"
        log_file = root / "sidecar.jsonl"
        data_dir = root / "data"
        process = subprocess.Popen(
            [
                str(executable),
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--data-dir",
                str(data_dir),
                "--context-file",
                str(context_file),
                "--log-file",
                str(log_file),
                "--safe-mode",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            port = wait_for_port(context_file, process, args.timeout)
            payload = wait_for_health(port, args.timeout)
            print(json.dumps({"port": port, "health": payload}, indent=2))
            if process.stdin is None:
                raise RuntimeError("Sidecar stdin control channel is unavailable")
            process.stdin.write("shutdown\n")
            process.stdin.flush()
            return_code = process.wait(timeout=args.timeout)
            if return_code != 0:
                stdout, stderr = process.communicate(timeout=5)
                raise RuntimeError(
                    f"Sidecar returned {return_code} during clean shutdown\n{stdout}\n{stderr}"
                )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

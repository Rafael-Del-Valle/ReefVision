"""Structured CLI output stays UTF-8 through redirected machine streams."""

import json
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("pipe_encoding", ["cp1252", "utf-8"])
@pytest.mark.parametrize("exit_code", [0, 2, 3])
def test_console_emits_utf8_json_through_redirected_pipes(
    pipe_encoding: str, exit_code: int
) -> None:
    # Supply a representative scientific comparison message without starting workers.
    payload = {"message": "Overlap ≥ 0.5 for Récif 海"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from reefvision import automation_cli; "
                "automation_cli.run = lambda _: (int(sys.argv[1]), sys.argv[2] + '\\n'); "
                "raise SystemExit(automation_cli.main([]))"
            ),
            str(exit_code),
            json.dumps(payload, ensure_ascii=False),
        ],
        env={**os.environ, "PYTHONIOENCODING": pipe_encoding},
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == exit_code, result.stderr
    received = result.stderr if exit_code == 2 else result.stdout
    assert (result.stdout if exit_code == 2 else result.stderr) == b""
    assert json.loads(received.decode("utf-8")) == payload
    assert "≥ 0.5 for Récif 海".encode() in received


def test_redirected_help_uses_utf8_with_a_windows_code_page() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "reefvision.automation_cli", "--help"],
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Help → Automation API".encode() in result.stdout
    assert result.stderr == b""

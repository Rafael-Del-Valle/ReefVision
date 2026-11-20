"""Live Windows loopback controls for the historical acceptance driver."""

from __future__ import annotations

import subprocess
import sys
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from acceptance_windows_qc_history import validate_listener_owner

FIXTURE = """
import socket
import sys

with socket.socket() as listener:
    listener.bind((sys.argv[1], 0))
    listener.listen()
    print(listener.getsockname()[1], flush=True)
    sys.stdin.read()
"""


@contextmanager
def fixture_listener(address: str = "127.0.0.1") -> Iterator[tuple[subprocess.Popen[str], int]]:
    with subprocess.Popen(
        [sys.executable, "-c", FIXTURE, address],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stdout is not None and process.stdin is not None
        try:
            port = int(process.stdout.readline())
            yield process, port
        finally:
            process.stdin.close()
            process.wait(timeout=10)


@unittest.skipUnless(sys.platform == "win32", "validates the Windows TCP owner table")
class ListenerOwnershipTests(unittest.TestCase):
    def test_live_owner_is_verified_even_when_powershell_times_out(self) -> None:
        shell_timeout = subprocess.TimeoutExpired("powershell", 12)
        with (
            fixture_listener() as (owner, port),
            patch.object(subprocess, "run", side_effect=shell_timeout),
        ):
            validate_listener_owner(port, owner)

    def test_unrelated_disposable_listener_is_rejected(self) -> None:
        with (
            fixture_listener() as (first, _),
            fixture_listener() as (_, foreign_port),
            self.assertRaisesRegex(RuntimeError, "does not belong to"),
        ):
            validate_listener_owner(foreign_port, first)

    def test_wildcard_listener_is_rejected_even_when_owned(self) -> None:
        with (
            fixture_listener("0.0.0.0") as (owner, port),
            self.assertRaisesRegex(RuntimeError, "loopback listener"),
        ):
            validate_listener_owner(port, owner)


if __name__ == "__main__":
    unittest.main()

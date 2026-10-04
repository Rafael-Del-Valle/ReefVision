from __future__ import annotations

import importlib.util
import socket
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def harness():
    path = Path(__file__).resolve().parents[4] / "scripts" / "phase11b-stress.py"
    spec = importlib.util.spec_from_file_location("phase11b_stress", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_loopback_host_detection_is_explicit(harness) -> None:
    assert harness.is_loopback_host("127.0.0.1") is True
    assert harness.is_loopback_host("::1") is True
    assert harness.is_loopback_host("localhost") is True
    assert harness.is_loopback_host("example.com") is False


def test_offline_guard_blocks_non_loopback_dns_without_real_network(harness) -> None:
    guard = harness.OfflineSocketGuard()

    with guard:
        with pytest.raises(OSError, match="Blocked non-loopback network access"):
            socket.getaddrinfo("example.com", 443)

        probe = socket.socket()
        try:
            with pytest.raises(OSError, match="Blocked non-loopback network access"):
                probe.connect(("203.0.113.1", 443))
        finally:
            probe.close()

    assert len(guard.attempts) == 2
    assert "example.com" in guard.attempts[0]
    assert "203.0.113.1" in guard.attempts[1]


def test_results_package_fixture_records_non_biological_cpu_run(harness) -> None:
    run = harness.results_run("project-id")

    assert run["device"] == "cpu"
    assert run["status"] == "completed"
    assert run["dataset_manifest_sha256"] == "a" * 64
    assert run["split_manifest_sha256"] == "b" * 64

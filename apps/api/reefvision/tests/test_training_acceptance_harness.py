"""Hardware gates must not mistake an ordinary crash for completed training."""

import runpy
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("mode", "exit_code", "status", "acted"),
    [
        ("normal", 0, "completed", False),
        ("cancel", 0, "cancelled", True),
        ("interrupt", 1, "training", True),
        ("interrupt_final", 73, "training", False),
    ],
)
def test_acceptance_checks_intended_exit_and_pre_recovery_state(
    mode: str,
    exit_code: int,
    status: str,
    acted: bool,
) -> None:
    harness = runpy.run_path(
        str(Path(__file__).resolve().parents[4] / "scripts" / "acceptance_training_lifecycle.py")
    )
    harness["assert_worker_outcome"](mode, exit_code, status, acted)


@pytest.mark.parametrize(
    ("mode", "exit_code", "status", "acted"),
    [
        ("normal", 1, "completed", False),
        ("normal", 0, "training", False),
        ("cancel", 0, "cancelled", False),
        ("cancel", 1, "cancelled", True),
        ("interrupt", 0, "completed", True),
        ("interrupt", 1, "training", False),
        ("interrupt_final", 0, "training", False),
        ("interrupt_final", 73, "completed", False),
    ],
)
def test_acceptance_rejects_crashes_and_unexercised_faults(
    mode: str,
    exit_code: int,
    status: str,
    acted: bool,
) -> None:
    harness = runpy.run_path(
        str(Path(__file__).resolve().parents[4] / "scripts" / "acceptance_training_lifecycle.py")
    )
    with pytest.raises(AssertionError):
        harness["assert_worker_outcome"](mode, exit_code, status, acted)

def test_acceptance_rejects_overly_deep_windows_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = runpy.run_path(
        str(Path(__file__).resolve().parents[4] / "scripts" / "acceptance_training_lifecycle.py")
    )
    monkeypatch.setattr(harness["sys"], "platform", "win32")
    deep = Path("C:/") / ("deep-output/" * 20)
    with pytest.raises(RuntimeError, match="too deep"):
        harness["validate_acceptance_output_root"](deep)

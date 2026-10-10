from __future__ import annotations

from pathlib import Path


def _script(name: str) -> str:
    return (Path(__file__).resolve().parents[4] / "scripts" / name).read_text(encoding="utf-8")


def test_phase11c_wrapper_remains_windows_powershell_ascii_safe() -> None:
    source = _script("phase11c-acceptance.ps1")

    source.encode("ascii")


def test_phase11c_wrapper_requires_plan_or_disposable_mode() -> None:
    source = _script("phase11c-acceptance.ps1")

    assert "-DisposableTest and -PlanOnly are mutually exclusive." in source
    assert "Choose -PlanOnly on a normal machine" in source
    assert '$Arguments += "-DisposableTest"' in source


def test_clean_install_harness_refuses_unmarked_destructive_use() -> None:
    source = _script("acceptance-windows-clean-install.ps1")

    assert "Refusing destructive MSI acceptance" in source
    assert ".reefvision-clean-install-acceptance" in source
    assert "Refusing to modify an existing ReefVision installation" in source
    assert "Administrator privileges are required" in source

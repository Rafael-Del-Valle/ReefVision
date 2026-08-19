from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def test_windows_provider_stack_uses_only_opencv_contrib_distribution() -> None:
    requirements = (
        ROOT / "requirements" / "providers-windows-cu121-py312.txt"
    ).read_text(encoding="utf-8")
    active_lines = [
        line.strip().casefold()
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert "opencv-contrib-python==4.12.0.88" in active_lines
    assert not any(line.startswith("opencv-python") for line in active_lines)
    assert not any(line.startswith("opencv-python-headless") for line in active_lines)
    assert not any(line.startswith("opencv-contrib-python-headless") for line in active_lines)


def test_bootstrap_resets_shared_cv2_namespace_before_pinned_install() -> None:
    bootstrap = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")

    assert "pip uninstall -y opencv-python opencv-python-headless" in bootstrap
    assert "opencv-contrib-python opencv-contrib-python-headless" in bootstrap
    assert "pip install --no-deps -r $ProviderRequirementsPath" in bootstrap
    assert "OpenCV distribution ownership OK" in bootstrap
    assert "require_scale_assistant_marker_runtime" in bootstrap


def test_pyinstaller_collects_contrib_metadata_and_preflights_aruco() -> None:
    build_script = (
        ROOT / "scripts" / "build-desktop-backend.ps1"
    ).read_text(encoding="utf-8")

    assert '"opencv-contrib-python"' in build_script
    assert '"opencv-python"' not in build_script
    assert '"cv2"' in build_script
    assert "require_scale_assistant_marker_runtime" in build_script


def test_desktop_self_test_requires_aruco_runtime() -> None:
    desktop = (
        ROOT / "apps" / "api" / "reefvision" / "desktop.py"
    ).read_text(encoding="utf-8")

    assert "def require_scale_assistant_marker_runtime" in desktop
    assert 'hasattr(cv2, "aruco")' in desktop
    assert "require_scale_assistant_marker_runtime()" in desktop

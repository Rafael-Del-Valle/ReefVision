from __future__ import annotations

from pathlib import Path

from reefvision.desktop import require_annotated_video_encoder_runtime

ROOT = Path(__file__).resolve().parents[4]


def test_imageio_ffmpeg_is_runtime_dependency() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"imageio-ffmpeg==0.6.0"' in pyproject


def test_pyinstaller_collects_annotated_video_encoder() -> None:
    build = (ROOT / "scripts" / "build-desktop-backend.ps1").read_text(encoding="utf-8")

    assert '"imageio_ffmpeg"' in build
    assert '"imageio-ffmpeg"' in build
    assert "Annotated-video libx264 runtime preflight failed." in build
    assert "PyInstaller/trim step omitted the imageio-ffmpeg executable." in build
    assert "Staged desktop backend omitted the imageio-ffmpeg executable." in build


def test_desktop_self_test_requires_annotated_video_encoder() -> None:
    desktop = (ROOT / "apps" / "api" / "reefvision" / "desktop.py").read_text(encoding="utf-8")

    assert "def require_annotated_video_encoder_runtime" in desktop

    start = desktop.index("def run_self_test(")
    section = desktop[start:]

    assert "require_annotated_video_encoder_runtime()" in section


def test_source_annotated_video_encoder_runtime() -> None:
    require_annotated_video_encoder_runtime()

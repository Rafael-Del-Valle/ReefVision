"""Guard against PyInstaller resolving Copernicus source under its spec directory."""

from pathlib import Path


def test_windows_installer_anchors_optional_copernicus_worker_to_source_root() -> None:
    """The worker must exist even when --specpath lives under .desktop/."""
    root = Path(__file__).resolve().parents[4]
    worker = root / "apps" / "api" / "reefvision" / "services" / "copernicus_worker.py"
    assert worker.is_file()

    packaging_script = (root / "scripts" / "build-desktop-backend.ps1").read_text(encoding="utf-8")
    assert (
        '$CopernicusWorkerPath = Join-Path $ApiRoot "reefvision\\services\\copernicus_worker.py"'
        in packaging_script
    )
    assert (
        "if (-not (Test-Path -LiteralPath $CopernicusWorkerPath -PathType Leaf))"
        in packaging_script
    )
    assert '"${CopernicusWorkerPath};reefvision/services"' in packaging_script
    assert (
        '"apps/api/reefvision/services/copernicus_worker.py;reefvision/services"'
        not in packaging_script
    )

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

from reefvision import __version__

ROOT = Path(__file__).resolve().parents[4]
BUILDER = ROOT / "scripts" / "build-automation-sdk-wheel.py"


def test_sdk_wheel_keeps_only_the_canonical_pure_python_source(tmp_path: Path) -> None:
    root = tmp_path / "source"
    package = root / "apps" / "api" / "reefvision_sdk"
    package.mkdir(parents=True)
    source = package / "__init__.py"
    source.write_text(
        f'"""Canonical isolated SDK fixture."""\n__version__ = "{__version__}"\n',
        encoding="utf-8",
    )
    (package / "local_developer_only.py").write_text("raise AssertionError\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "reefvision"\n'
        f'version = "{__version__}"\n'
        'requires-python = ">=3.11"\nlicense = "AGPL-3.0-only"\n',
        encoding="utf-8",
    )
    (root / "LICENSE").write_text("Fixture license\n", encoding="utf-8")
    output = tmp_path / "distribution"
    command = [sys.executable, str(BUILDER), "--root", str(root)]
    built = subprocess.run(
        [*command, "--output", str(output)], capture_output=True, text=True, check=False
    )
    assert built.returncode == 0, built.stdout + built.stderr
    (wheel,) = output.glob("*.whl")
    assert wheel.name == f"reefvision_sdk-{__version__}-py3-none-any.whl"
    with ZipFile(wheel) as archive:
        files = archive.namelist()
        assert [item for item in files if item.endswith(".py")] == ["reefvision_sdk/__init__.py"]
        assert archive.read("reefvision_sdk/__init__.py") == source.read_bytes()
        dist = f"reefvision_sdk-{__version__}.dist-info"
        assert b"Root-Is-Purelib: true" in archive.read(f"{dist}/WHEEL")
        assert b"Requires-Dist:" not in archive.read(f"{dist}/METADATA")
        assert archive.read(f"{dist}/licenses/LICENSE") == (root / "LICENSE").read_bytes()
    verified = subprocess.run(
        [*command, "--verify-wheel", str(wheel)], capture_output=True, text=True, check=False
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    source.write_text(
        f'"""Different canonical bytes."""\n__version__ = "{__version__}"\n',
        encoding="utf-8",
    )
    stale = subprocess.run(
        [*command, "--verify-wheel", str(wheel)], capture_output=True, text=True, check=False
    )
    assert stale.returncode != 0 and "canonical SDK source" in stale.stderr

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


def test_stage_standard_desktop_from_build_environment_with_optional_codec(tmp_path: Path) -> None:
    source = tmp_path / "dist" / "reefvision-api"
    destination = tmp_path / "resources" / "reefvision-api"
    files = {
        "reefvision-api.exe": b"frozen fixture",
        "_internal/sleap_io-0.9.2.dist-info/entry_points.txt": (
            b"[console_scripts]\nsio=vendor:main"
        ),
        "_internal/sleap-nn-0.3.3.egg-info/PKG-INFO": b"Name: sleap-nn",
        "_internal/sleap-1.4.1.dist-info/METADATA": b"Name: sleap",
        "_internal/numpy-2.2.6.dist-info/METADATA": b"Name: numpy",
        "_internal/reefvision/data/sleap_io-0.9.2.dist-info/history.json": b"history",
        "_internal/alembic/migrations/env.py": b"migration fixture",
    }
    for name, contents in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    stage = runpy.run_path(str(SCRIPTS / "stage-desktop-backend.py"))["stage"]
    stage(source, destination)

    shipped = {
        "reefvision-api.exe",
        "_internal/numpy-2.2.6.dist-info/METADATA",
        "_internal/reefvision/data/sleap_io-0.9.2.dist-info/history.json",
        "_internal/alembic/migrations/env.py",
    }
    assert {
        p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()
    } == shipped
    for name, contents in files.items():
        assert (source / name).read_bytes() == contents
    for name in shipped:
        assert (destination / name).read_bytes() == files[name]
    with pytest.raises(FileExistsError):
        stage(source, destination)

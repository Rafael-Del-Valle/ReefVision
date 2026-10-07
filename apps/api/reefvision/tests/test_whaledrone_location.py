from pathlib import Path

import pytest

from reefvision.tests.whaledrone import get_whaledrone_root


def test_optional_external_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("REEFVISION_WHALEDRONE_ROOT", raising=False)
    assert get_whaledrone_root() is None
    monkeypatch.setenv("REEFVISION_WHALEDRONE_ROOT", str(tmp_path / "missing"))
    assert get_whaledrone_root() is None
    monkeypatch.setenv("REEFVISION_WHALEDRONE_ROOT", str(tmp_path))
    assert get_whaledrone_root() == tmp_path.resolve()
    monkeypatch.setenv("REEFVISION_WHALEDRONE_ROOT", str(Path(__file__).resolve().parent))
    assert get_whaledrone_root() is None
